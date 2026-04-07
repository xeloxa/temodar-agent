"""
Temodar Agent Plugin Downloader

Download and extract plugins for analysis.
"""

import http.client
import ipaddress
import logging
import os
import re
import shutil
import socket
import ssl
import zipfile
from pathlib import Path
from typing import List, Optional, Tuple
from urllib.parse import urljoin, urlparse

from infrastructure.http_client import get_session

logger = logging.getLogger("temodar_agent.downloaders.plugin")


class PluginDownloader:
    """Plugin downloader and extractor."""

    MAX_REDIRECTS = 5
    MAX_ZIP_ENTRIES = 20000
    MAX_SINGLE_FILE_SIZE = 50 * 1024 * 1024  # 50 MB per file
    MAX_TOTAL_UNCOMPRESSED_SIZE = 300 * 1024 * 1024  # 300 MB total
    MAX_COMPRESSION_RATIO = 1000  # Basic zip-bomb heuristic
    MAX_ZIP_DOWNLOAD_SIZE = 200 * 1024 * 1024

    def __init__(self, base_dir: str = "."):
        self.base_dir = Path(base_dir)
        self.plugins_dir = self.base_dir / "Plugins"
        self.plugins_dir.mkdir(exist_ok=True)

    def _sanitize_slug(self, slug: str) -> str:
        """Sanitize slug to prevent path traversal and unsafe filesystem writes."""
        raw = (slug or "").strip()
        if not raw:
            raise ValueError("Invalid slug: empty")
        if len(raw) > 100:
            raise ValueError("Invalid slug: too long")
        if not re.fullmatch(r"[a-zA-Z0-9_-]+", raw):
            raise ValueError("Invalid slug format")
        return raw

    def _ensure_within_base(self, target: Path, base: Path) -> None:
        """Ensure target path is inside base directory."""
        target_resolved = target.resolve()
        base_resolved = base.resolve()
        if os.path.commonpath([str(base_resolved), str(target_resolved)]) != str(
            base_resolved
        ):
            raise ValueError("Path traversal detected")

    def _validate_url(self, url: str) -> Tuple[str, List[str]]:
        """
        Validate URL to prevent SSRF attacks and return validated IPs.

        Returns:
            Tuple of (hostname, list_of_validated_ip_strings)
        """
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            raise ValueError(f"Invalid URL scheme: {parsed.scheme}")

        hostname = parsed.hostname
        if not hostname:
            raise ValueError("Invalid URL: Missing hostname")

        blocked_hostnames = {
            "metadata.google.internal",
            "metadata.goog",
            "169.254.169.254",
            "instance-data",
            "metadata",
        }
        if hostname.lower() in blocked_hostnames:
            raise ValueError(
                "SSRF Protection: Access to cloud metadata endpoint is blocked"
            )

        validated_ips: List[str] = []
        try:
            addr_infos = socket.getaddrinfo(hostname, None)
            if not addr_infos:
                raise ValueError(f"Could not resolve hostname: {hostname}")

            for info in addr_infos:
                ip_str = info[4][0]
                ip_obj = ipaddress.ip_address(ip_str)

                if ip_obj.is_loopback:
                    raise ValueError(
                        f"SSRF Protection: Access to loopback address {ip_str} is blocked"
                    )
                if ip_obj.is_private:
                    raise ValueError(
                        f"SSRF Protection: Access to private IP {ip_str} is blocked"
                    )
                if ip_obj.is_link_local:
                    raise ValueError(
                        f"SSRF Protection: Access to link-local address {ip_str} is blocked"
                    )
                if ip_obj.is_reserved:
                    raise ValueError(
                        f"SSRF Protection: Access to reserved IP {ip_str} is blocked"
                    )
                if ip_obj.is_multicast:
                    raise ValueError(
                        f"SSRF Protection: Access to multicast address {ip_str} is blocked"
                    )
                if str(ip_obj) == "169.254.169.254":
                    raise ValueError(
                        "SSRF Protection: Access to cloud metadata endpoint is blocked"
                    )
                if str(ip_obj) == "::1":
                    raise ValueError(
                        "SSRF Protection: Access to IPv6 localhost is blocked"
                    )

                validated_ips.append(ip_str)

        except socket.gaierror:
            raise ValueError(f"Could not resolve hostname: {hostname}")

        if not validated_ips:
            raise ValueError(f"No valid IP addresses resolved for: {hostname}")

        return hostname, validated_ips

    def _select_pinned_ip(self, validated_ips: List[str]) -> str:
        """Prefer IPv4 for URL/transport compatibility, fall back to IPv6."""
        for ip_str in validated_ips:
            if ipaddress.ip_address(ip_str).version == 4:
                return ip_str
        return validated_ips[0]

    def _open_pinned_response(self, url: str, hostname: str, validated_ips: List[str]):
        """Open a pinned HTTP(S) response without changing the TLS hostname."""
        parsed = urlparse(url)
        pinned_ip = self._select_pinned_ip(validated_ips)
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        path = parsed.path or "/"
        if parsed.query:
            path = f"{path}?{parsed.query}"

        class PinnedHTTPConnection(http.client.HTTPConnection):
            def __init__(self, pinned_addr: str, target_host: str, target_port: int, timeout: int):
                super().__init__(host=target_host, port=target_port, timeout=timeout)
                self._pinned_addr = pinned_addr
                self._target_port = target_port

            def connect(self):
                self.sock = socket.create_connection((self._pinned_addr, self._target_port), self.timeout)

        class PinnedHTTPSConnection(http.client.HTTPSConnection):
            def __init__(self, pinned_addr: str, target_host: str, target_port: int, timeout: int):
                context = ssl.create_default_context()
                super().__init__(host=target_host, port=target_port, timeout=timeout, context=context)
                self._pinned_addr = pinned_addr
                self._target_port = target_port
                self._context = context

            def connect(self):
                raw_sock = socket.create_connection((self._pinned_addr, self._target_port), self.timeout)
                self.sock = self._context.wrap_socket(raw_sock, server_hostname=self.host)

        if parsed.scheme == "https":
            connection = PinnedHTTPSConnection(pinned_ip, hostname, port, 60)
        else:
            connection = PinnedHTTPConnection(pinned_ip, hostname, port, 60)

        host_header = hostname if parsed.port is None else f"{hostname}:{parsed.port}"
        connection.request("GET", path, headers={"Host": host_header, "User-Agent": "TemodarAgent/1.0"})
        response = connection.getresponse()
        return connection, response

    def _validate_zip_archive(self, zip_ref: zipfile.ZipFile) -> None:
        """Validate ZIP to reduce zip-bomb and archive abuse risks."""
        members = zip_ref.infolist()
        if len(members) > self.MAX_ZIP_ENTRIES:
            raise ValueError("ZIP archive has too many entries")

        total_uncompressed = 0
        for member in members:
            total_uncompressed += member.file_size

            if member.file_size > self.MAX_SINGLE_FILE_SIZE:
                raise ValueError(
                    f"ZIP entry too large: {member.filename} ({member.file_size} bytes)"
                )

            if member.compress_size > 0:
                ratio = member.file_size / member.compress_size
                if ratio > self.MAX_COMPRESSION_RATIO:
                    raise ValueError(
                        f"Suspicious compression ratio in ZIP entry: {member.filename}"
                    )

        if total_uncompressed > self.MAX_TOTAL_UNCOMPRESSED_SIZE:
            raise ValueError("ZIP archive uncompressed size exceeds safety limits")

    def _download_zip_with_validated_redirects(self, *, session, download_url: str, zip_path: Path) -> None:
        del session  # Requests session retained for API compatibility; pinned transport is handled here.
        current_url = download_url

        for _ in range(self.MAX_REDIRECTS):
            hostname, validated_ips = self._validate_url(current_url)
            connection, response = self._open_pinned_response(current_url, hostname, validated_ips)

            try:
                if response.status in {301, 302, 303, 307, 308}:
                    location = response.getheader("Location", "")
                    if not location:
                        raise ValueError("Redirect response missing Location header")
                    current_url = urljoin(current_url, location)
                    response.close()
                    connection.close()
                    continue

                if response.status >= 400:
                    raise ValueError(f"HTTP {response.status}")

                total_downloaded = 0
                with open(zip_path, "wb") as file_handle:
                    while True:
                        chunk = response.read(8192)
                        if not chunk:
                            break
                        total_downloaded += len(chunk)
                        if total_downloaded > self.MAX_ZIP_DOWNLOAD_SIZE:
                            raise ValueError("ZIP archive exceeds download size limit")
                        file_handle.write(chunk)
                return
            finally:
                try:
                    response.close()
                finally:
                    connection.close()

        raise ValueError("Too many redirects")

    def _extract_archive(self, *, zip_path: Path, extract_path: Path) -> None:
        with zipfile.ZipFile(zip_path, "r") as zip_ref:
            self._validate_zip_archive(zip_ref)
            extract_base = extract_path.resolve()
            for member in zip_ref.infolist():
                member_path = (extract_path / member.filename).resolve()
                if os.path.commonpath([str(extract_base), str(member_path)]) != str(
                    extract_base
                ):
                    raise Exception(f"Zip Slip attempt detected: {member.filename}")
                zip_ref.extract(member, extract_path)

    def _normalize_extracted_directory(self, extract_path: Path) -> None:
        children = list(extract_path.iterdir())
        if len(children) != 1 or not children[0].is_dir():
            return
        temp_dir = extract_path.parent / "temp"
        children[0].rename(temp_dir)
        shutil.rmtree(extract_path)
        temp_dir.rename(extract_path)

    def _cleanup_failed_download(self, *, plugin_dir: Optional[Path]) -> None:
        if not plugin_dir or not plugin_dir.exists():
            return
        try:
            self._ensure_within_base(plugin_dir, self.plugins_dir)
            shutil.rmtree(plugin_dir, ignore_errors=True)
        except Exception:
            pass

    def download_and_extract(
        self, download_url: str, slug: str, verbose: bool = True
    ) -> Optional[Path]:
        """Download and extract a plugin, returning the path to extracted files."""
        session = get_session()
        safe_slug = slug
        plugin_dir: Optional[Path] = None
        zip_path: Optional[Path] = None
        extract_path: Optional[Path] = None

        try:
            safe_slug = self._sanitize_slug(slug)
            plugin_dir = self.plugins_dir / safe_slug
            zip_path = plugin_dir / f"{safe_slug}.zip"
            extract_path = plugin_dir / "source"
            self._ensure_within_base(plugin_dir, self.plugins_dir)
            self._ensure_within_base(extract_path, self.plugins_dir)
            plugin_dir.mkdir(exist_ok=True)

            if extract_path.exists():
                shutil.rmtree(extract_path, ignore_errors=True)
            if zip_path.exists():
                zip_path.unlink()

            if verbose:
                logger.info("Downloading plugin source", extra={"slug": safe_slug})
            self._download_zip_with_validated_redirects(
                session=session,
                download_url=download_url,
                zip_path=zip_path,
            )

            if verbose:
                logger.info("Extracting plugin source", extra={"slug": safe_slug})
            self._extract_archive(zip_path=zip_path, extract_path=extract_path)

            zip_path.unlink(missing_ok=True)
            self._normalize_extracted_directory(extract_path)

            if verbose:
                file_count = sum(1 for candidate in extract_path.rglob("*") if candidate.is_file())
                logger.info(
                    "Extracted plugin source",
                    extra={"slug": safe_slug, "file_count": file_count},
                )

            return extract_path

        except zipfile.BadZipFile:
            if verbose:
                logger.warning("Invalid ZIP file for plugin", extra={"slug": slug})
            if zip_path and zip_path.exists():
                zip_path.unlink()
            return None
        except Exception as exc:
            if verbose:
                logger.warning(
                    "Failed to download plugin source",
                    extra={"slug": slug},
                    exc_info=exc,
                )
            self._cleanup_failed_download(plugin_dir=plugin_dir)
            return None
