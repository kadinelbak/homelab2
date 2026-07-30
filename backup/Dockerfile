FROM alpine:3.20

RUN apk add --no-cache \
    bash \
    ca-certificates \
    coreutils \
    findutils \
    postgresql16-client \
    restic \
    tzdata \
    util-linux

COPY run-backup.sh /usr/local/bin/run-backup.sh
COPY exclude-list /etc/homelab-backup/exclude-list

RUN chmod 0755 /usr/local/bin/run-backup.sh

ENTRYPOINT ["/usr/local/bin/run-backup.sh"]
