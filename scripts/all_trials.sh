#!/bin/sh
# Replay every scenario used on the page. The two films are recorded; the rest are logged only.
cd "$(dirname "$0")/.."
for s in "recovery --record" "recovery" "recovery" "recovery" "ambiguous --record" "ambiguous" "popup" "popup" "focus" "move"; do
  venv/bin/python scripts/scenario.py $s > .run/last_scenario.log 2>&1
  echo "== $s: exit $?"
done
venv/bin/python scripts/results_table.py
