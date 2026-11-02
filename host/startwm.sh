#!/bin/sh
# The session runs one program: the synthetic application, full screen, no window manager.
# If it exits (test reset), it is started again on its search screen.
xsetroot -solid '#3a6ea5' 2>/dev/null
while true; do python3 /srv/app/caseapp.py; sleep 0.5; done
