#!/bin/sh
# INDEPENDENT test check, not used by the executor: count records stored on the host
# for one household and period, straight from the application's storage in the container.
HH=${1:-DEMO-HH-014}; PERIOD=${2:-2026-11}
docker exec rdp-demo-host sh -c "cat /srv/data/records.jsonl 2>/dev/null" | \
  python3 -c "import sys,json; r=[json.loads(l) for l in sys.stdin if l.strip()]; m=[x for x in r if x['household_id']=='$HH' and x['period']=='$PERIOD']; print(json.dumps({'household':'$HH','period':'$PERIOD','records_on_host':len(m),'numbers':[x['number'] for x in m],'values':[{k:x[k] for k in ('members','effective_date','monthly_wages','monthly_benefits')} for x in m]}))"
