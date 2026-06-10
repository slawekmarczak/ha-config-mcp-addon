FROM ghcr.io/home-assistant/base-python:3.13-alpine3.22

LABEL \
    io.hass.version="1.0.0" \
    io.hass.type="app" \
    io.hass.arch="aarch64|amd64"

RUN apk add --no-cache \
    git \
    openssh-client \
    bash

RUN pip3 install --break-system-packages fastmcp

COPY rootfs /

RUN chmod +x /run.sh

CMD ["/run.sh"]
