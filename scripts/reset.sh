#!/bin/sh
# Reset the test case: empty host storage, set host faults, clear the client journal, go to search screen.
# usage: reset.sh '{"save_latency": 2.5, "index_delay": 0}'
cd "$(dirname "$0")/.."
FAULTS=${1:-'{"save_latency": 2.5, "index_delay": 0}'}
docker exec rdp-demo-host sh -c "rm -f /srv/data/records.jsonl; echo '$FAULTS' > /srv/data/faults.json; chown clerk:clerk /srv/data/faults.json"
rm -f runs/journal/DEMO-HH-014_2026-11.jsonl
venv/bin/python -m executor.control resume >/dev/null
# restart the app in the session so it opens on its search screen
docker exec rdp-demo-host pkill -f caseapp.py >/dev/null 2>&1 || true
sleep 1
sleep 2
venv/bin/python -m executor.operator focus >/dev/null
echo "reset: faults=$FAULTS"
