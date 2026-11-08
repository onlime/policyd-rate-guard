# Development and end-to-end test image. It installs exactly like the Ansible role does on Debian 13:
# Debian's Python, a venv with hash-pinned binary wheels, the app loaded from the checkout via a .pth file.
FROM debian:trixie-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 python3-venv ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --system --no-create-home --shell /usr/sbin/nologin policyd-rate-guard

WORKDIR /opt/policyd-rate-guard
COPY requirements.txt ./
RUN python3 -m venv venv \
    && venv/bin/pip install --no-cache-dir --disable-pip-version-check \
        --require-hashes --only-binary=:all: --no-deps -r requirements.txt
COPY database ./database
COPY src ./src
RUN echo /opt/policyd-rate-guard/src \
    > "$(venv/bin/python -c 'import sysconfig; print(sysconfig.get_path("purelib"))')/policyd-rate-guard.pth" \
    && venv/bin/python -m compileall -q src

USER policyd-rate-guard
EXPOSE 10033
CMD ["/opt/policyd-rate-guard/venv/bin/python", "-m", "policyd_rate_guard", "serve"]
