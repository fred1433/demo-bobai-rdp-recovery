#!/bin/sh
# Stop everything up.sh started.
cd "$(dirname "$0")/.."
[ -f .run/freerdp.pid ] && kill "$(cat .run/freerdp.pid)" 2>/dev/null
rm -f .run/freerdp.pid
docker rm -f rdp-demo-host rdp-demo-screen >/dev/null 2>&1
echo "bench down"
