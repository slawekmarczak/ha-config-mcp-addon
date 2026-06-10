ARG BUILD_FROM
FROM $BUILD_FROM

RUN apk add --no-cache \
    python3 \
    py3-pip \
    git \
    openssh-client \
    bash

RUN pip3 install --break-system-packages fastmcp

COPY rootfs /

RUN chmod +x /run.sh

CMD ["/run.sh"]
