FROM python:3.12-slim

ARG TEMODAR_AGENT_IMAGE_VERSION=unknown
ARG TEMODAR_AGENT_IMAGE_TAG=unknown
ARG TEMODAR_AGENT_IMAGE_BUILD=

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    TEMODAR_AGENT_HOST=0.0.0.0 \
    TEMODAR_AGENT_PORT=8080 \
    TEMODAR_AGENT_IMAGE_VERSION=${TEMODAR_AGENT_IMAGE_VERSION} \
    TEMODAR_AGENT_IMAGE_TAG=${TEMODAR_AGENT_IMAGE_TAG} \
    TEMODAR_AGENT_IMAGE_BUILD=${TEMODAR_AGENT_IMAGE_BUILD}

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    bash \
    ca-certificates \
    git \
    gosu \
    nodejs \
    npm \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN python -m pip install --upgrade pip && python -m pip install -r requirements.txt

COPY . .
RUN npm --prefix /app/ai/node_runner ci && npm --prefix /app/ai/node_runner run build

RUN mkdir -p /licenses && \
    cp /app/LICENSE /licenses/Temodar-Agent-Apache-2.0.txt && \
    cp /app/THIRD_PARTY_LICENSES.md /licenses/THIRD_PARTY_LICENSES.md && \
    cp /app/licenses/LGPL-2.1.txt /licenses/LGPL-2.1.txt && \
    cp /app/licenses/SEMGREP_SOURCE_NOTICE.txt /licenses/SEMGREP_SOURCE_NOTICE.txt

RUN useradd -m -u 10001 appuser && \
    mkdir -p /app/Plugins /app/semgrep_results /app/sessions /home/appuser/.temodar-agent && \
    chown -R appuser:appuser /app /home/appuser

RUN chmod +x /app/docker-entrypoint.sh

EXPOSE 8080

HEALTHCHECK --interval=10s --timeout=3s --start-period=20s --retries=6 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=2)"

ENTRYPOINT ["/app/docker-entrypoint.sh"]
CMD ["python", "temodar-agent.py"]
