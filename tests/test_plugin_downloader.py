import io
import zipfile
from pathlib import Path

from downloaders.plugin_downloader import PluginDownloader


class _FakeResponse:
    def __init__(self, chunks=None, *, is_redirect=False, location=None, status_code=200):
        self._chunks = chunks or []
        self.is_redirect = is_redirect
        self.status_code = status_code
        self.headers = {}
        if location is not None:
            self.headers["Location"] = location

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def iter_content(self, chunk_size=8192):
        del chunk_size
        for chunk in self._chunks:
            yield chunk


class _FakeSession:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def get(self, url, stream=True, timeout=60, allow_redirects=False):
        self.calls.append(
            {
                "url": url,
                "stream": stream,
                "timeout": timeout,
                "allow_redirects": allow_redirects,
            }
        )
        if not self._responses:
            raise RuntimeError("No fake response available")
        return self._responses.pop(0)


def _build_zip_bytes(*, slug: str, filename: str = "plugin.php", content: bytes = b"<?php echo 'ok';") -> bytes:
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(f"{slug}/{filename}", content)
    return payload.getvalue()


def test_download_and_extract_succeeds_with_relative_redirect(monkeypatch, tmp_path):
    slug = "akismet"
    archive_bytes = _build_zip_bytes(slug=slug)
    calls = []

    class _PinnedResponse:
        def __init__(self, *, status, location=None, body=b""):
            self.status = status
            self._location = location
            self._body = io.BytesIO(body)

        def getheader(self, name, default=None):
            if name.lower() == "location":
                return self._location if self._location is not None else default
            return default

        def read(self, chunk_size=8192):
            return self._body.read(chunk_size)

        def close(self):
            return None

    class _PinnedConnection:
        def close(self):
            return None

    responses = [
        (_PinnedConnection(), _PinnedResponse(status=302, location="/plugin.zip")),
        (_PinnedConnection(), _PinnedResponse(status=200, body=archive_bytes)),
    ]

    monkeypatch.setattr("downloaders.plugin_downloader.get_session", lambda: object())
    monkeypatch.setattr(
        PluginDownloader,
        "_validate_url",
        lambda self, url: ("downloads.wordpress.org", ["93.184.216.34"]),
    )

    def fake_open(self, url, hostname, validated_ips):
        calls.append({"url": url, "hostname": hostname, "validated_ips": validated_ips})
        return responses.pop(0)

    monkeypatch.setattr(PluginDownloader, "_open_pinned_response", fake_open)

    downloader = PluginDownloader(base_dir=str(tmp_path))
    extracted = downloader.download_and_extract(
        "https://downloads.wordpress.org/plugin/akismet.latest.zip",
        slug,
        verbose=False,
    )

    assert extracted is not None
    assert extracted.exists()
    plugin_file = extracted / "plugin.php"
    assert plugin_file.exists()
    assert plugin_file.read_text(encoding="utf-8") == "<?php echo 'ok';"
    assert len(calls) == 2
    assert calls[0]["url"].startswith("https://downloads.wordpress.org/plugin/")
    assert calls[1]["url"] == "https://downloads.wordpress.org/plugin.zip"


def test_download_and_extract_returns_none_on_zip_slip(monkeypatch, tmp_path):
    slug = "akismet"

    malicious_payload = io.BytesIO()
    with zipfile.ZipFile(malicious_payload, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("../escape.php", b"<?php // bad")

    class _PinnedResponse:
        def __init__(self, body):
            self.status = 200
            self._body = io.BytesIO(body)

        def getheader(self, name, default=None):
            return default

        def read(self, chunk_size=8192):
            return self._body.read(chunk_size)

        def close(self):
            return None

    class _PinnedConnection:
        def close(self):
            return None

    monkeypatch.setattr("downloaders.plugin_downloader.get_session", lambda: object())
    monkeypatch.setattr(
        PluginDownloader,
        "_validate_url",
        lambda self, url: ("downloads.wordpress.org", ["93.184.216.34"]),
    )
    monkeypatch.setattr(
        PluginDownloader,
        "_open_pinned_response",
        lambda self, url, hostname, validated_ips: (_PinnedConnection(), _PinnedResponse(malicious_payload.getvalue())),
    )

    downloader = PluginDownloader(base_dir=str(tmp_path))
    extracted = downloader.download_and_extract(
        "https://downloads.wordpress.org/plugin/akismet.latest.zip",
        slug,
        verbose=False,
    )

    assert extracted is None
    plugin_dir = Path(tmp_path) / "Plugins" / slug
    assert not plugin_dir.exists()
