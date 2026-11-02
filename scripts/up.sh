#!/bin/sh
# Start the test bench, all on 127.0.0.1:
#  - rdp-demo-host   : Linux xrdp host (Docker) running the synthetic application (port 3389)
#  - rdp-demo-screen : a virtual X monitor (Xvfb in Docker, port 6099) for the client side,
#                      so nothing is drawn on, captured from, or typed into the real desktop
#  - xfreerdp        : the real FreeRDP client, running on macOS, drawing into that monitor
set -e
cd "$(dirname "$0")/.."
mkdir -p .run runs/raw
[ -f .run/clerk_password ] || (LC_ALL=C tr -dc 'A-Za-z0-9' < /dev/urandom | head -c 20 > .run/clerk_password)
PW=$(cat .run/clerk_password)
export DISPLAY=127.0.0.1:99
if ! docker ps --format '{{.Names}}' | grep -qx rdp-demo-host; then
  docker rm -f rdp-demo-host >/dev/null 2>&1 || true
  docker run -d --name rdp-demo-host -p 127.0.0.1:3389:3389 -e CLERK_PASSWORD="$PW" rdp-demo-host >/dev/null
fi
if ! docker ps --format '{{.Names}}' | grep -qx rdp-demo-screen; then
  docker rm -f rdp-demo-screen >/dev/null 2>&1 || true
  docker run -d --name rdp-demo-screen -p 127.0.0.1:6099:6000 -v "$PWD/runs/raw:/rec" rdp-demo-screen >/dev/null
fi
sleep 3
if ! pgrep -f "xfreerdp /v:127.0.0.1:3389" >/dev/null; then
  nohup xfreerdp /v:127.0.0.1:3389 /u:clerk /p:"$PW" /size:1024x720 /bpp:24 -gfx \
     /cert:ignore -wallpaper /kbd:layout:0x409 /t:"Remote Desktop - case-host" > .run/freerdp.log 2>&1 &
  echo $! > .run/freerdp.pid
  sleep 8
fi
# The operator clicks into the remote desktop window once (gives it keyboard focus).
venv/bin/python -m executor.operator focus
echo "bench up: client window on DISPLAY=$DISPLAY"
