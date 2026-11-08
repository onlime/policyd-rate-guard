#!/bin/sh
set -e
# Postfix needs a resolver config in its spool for the (non-chrooted) services as well
cp /etc/resolv.conf /etc/hosts /var/spool/postfix/etc/ 2>/dev/null || true
postfix check
exec postfix start-fg
