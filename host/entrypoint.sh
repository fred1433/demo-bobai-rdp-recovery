#!/bin/sh
set -e
: "${CLERK_PASSWORD:?CLERK_PASSWORD must be set (scripts/up.sh generates one per run)}"
echo "clerk:${CLERK_PASSWORD}" | chpasswd
[ -f /etc/ssl/private/ssl-cert-snakeoil.key ] || make-ssl-cert generate-default-snakeoil --force-overwrite
[ -f /srv/data/faults.json ] || echo '{"save_latency": 2.5, "index_delay": 0}' > /srv/data/faults.json
echo "${HOST_TZ:-UTC}" > /srv/tz
chown -R clerk:clerk /srv/data
rm -f /var/run/xrdp/*.pid /var/run/xrdp-sesman.pid 2>/dev/null || true
/usr/sbin/xrdp-sesman
exec /usr/sbin/xrdp --nodaemon
