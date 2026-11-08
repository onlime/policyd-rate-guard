# Development and end-to-end test image. It installs like the Ansible role does on Debian 13:
# Debian's Python, a venv, and the app with its dependencies as binary wheels.
FROM debian:trixie-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 python3-venv ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --system --no-create-home --shell /usr/sbin/nologin policyd-rate-guard

WORKDIR /opt/policyd-rate-guard
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
COPY database ./database
RUN python3 -m venv venv \
    && venv/bin/pip install --no-cache-dir --disable-pip-version-check --only-binary=:all: .

USER policyd-rate-guard
EXPOSE 10033
CMD ["/opt/policyd-rate-guard/venv/bin/python", "-m", "policyd_rate_guard", "serve"]
