#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../.."
run_directory=${1:?usage: run-capacity.sh RUN_DIRECTORY}
duration=${2:-3600}
recovery=${3:-600}
test -f "$run_directory/candidate-pin.json"
log="$run_directory/capacity-$(date -u +%Y%m%dT%H%M%SZ)"
mkdir "$log"
python3 tools/e2e/monitor.py "$run_directory" --seconds "$((duration + recovery + 600))" \
  --output "$log/resources.jsonl" > "$log/monitor.log" 2>&1 &
monitor_pid=$!
trap 'kill "$monitor_pid" 2>/dev/null || true; wait "$monitor_pid" 2>/dev/null || true' EXIT
load_status=0
recovery_status=0
audit_status=0
monitor_status=0
caffeinate -i node tools/e2e/load.mjs "$run_directory" "$duration" 50 > "$log/load.log" 2>&1 || load_status=$?
load_directory=$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["evidence"])' "$run_directory/latest-load.json")
printf '%s\n' "$load_directory" > "$log/load-directory.txt"
if test -f "$load_directory/result.json" && \
  python3 -c 'import json,sys;raise SystemExit(0 if json.load(open(sys.argv[1]))["complete"] else 1)' "$load_directory/result.json"; then
  caffeinate -i python3 tools/e2e/recover.py "$run_directory" "$load_directory" --seconds "$recovery" > "$log/recovery.log" 2>&1 || recovery_status=$?
  if ! kill -0 "$monitor_pid" 2>/dev/null; then monitor_status=1; fi
  kill "$monitor_pid" 2>/dev/null || true
  wait "$monitor_pid" 2>/dev/null || true
  trap - EXIT
  python3 tools/e2e/verify-capacity-data.py "$run_directory" "$load_directory" > "$log/persistence.log" 2>&1 || audit_status=$?
  python3 tools/e2e/summarize-capacity.py "$load_directory" "$log/resources.jsonl" > "$log/summary.log" 2>&1 || monitor_status=$?
  if ! python3 -c 'import json,sys; r=json.load(open(sys.argv[1])); raise SystemExit(not all(r.get(k) for k in ("resource_sampling_complete","browser_rss_after_close_zero","health_ok")))' "$load_directory/capacity-summary.json"; then
    monitor_status=1
  fi
fi
printf '%s\n' "$load_status" > "$log/load-exit-code.txt"
printf '%s\n' "$recovery_status" > "$log/recovery-exit-code.txt"
printf '%s\n' "$monitor_status" > "$log/monitor-exit-code.txt"
printf '%s\n' "$audit_status" > "$log/persistence-exit-code.txt"
if (( load_status != 0 )); then exit "$load_status"; fi
if (( recovery_status != 0 )); then exit "$recovery_status"; fi
if (( audit_status != 0 )); then exit "$audit_status"; fi
exit "$monitor_status"
