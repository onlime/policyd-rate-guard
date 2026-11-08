# Postfix 3.10 from Debian 13 with Cyrus SASL (sasldb), for end-to-end tests only.
FROM debian:trixie-slim

RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        postfix libsasl2-modules sasl2-bin \
    && rm -rf /var/lib/apt/lists/*

COPY main.cf /etc/postfix/main.cf
COPY smtpd.conf /etc/postfix/sasl/smtpd.conf
COPY entrypoint.sh /entrypoint.sh

RUN for user in test01 test02 test03; do \
        echo Example1234 | saslpasswd2 -c -p -u example.com "$user"; \
    done \
    && chown root:postfix /etc/sasldb2 && chmod 0640 /etc/sasldb2 \
    && echo mx.example.test > /etc/mailname \
    && postconf -M submission/inet='submission inet n - n - - smtpd' \
    && postconf -P 'submission/inet/syslog_name=postfix/submission' \
    # no chroot, so the smtpd processes can resolve the "policyd" container name
    && postconf -F 'smtp/inet/chroot=n' \
    && chmod 0755 /entrypoint.sh

EXPOSE 25 587
CMD ["/entrypoint.sh"]
