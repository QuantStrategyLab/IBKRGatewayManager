#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "$0")" && pwd)"
repo_dir="$(cd "${script_dir}/.." && pwd)"
container_name="${IB_GATEWAY_CONTAINER_NAME:-ib-gateway}"
compose_service_name="${IB_GATEWAY_COMPOSE_SERVICE_NAME:-ib-gateway}"
gateway_mode="${1:-${IB_GATEWAY_MODE:-paper}}"
initial_wait_seconds="${IB_GATEWAY_RECOVERY_INITIAL_WAIT_SECONDS:-240}"
restart_wait_seconds="${IB_GATEWAY_RECOVERY_RESTART_WAIT_SECONDS:-300}"
recreate_wait_seconds="${IB_GATEWAY_RECOVERY_RECREATE_WAIT_SECONDS:-600}"
progress_wait_seconds="${IB_GATEWAY_RECOVERY_PROGRESS_WAIT_SECONDS:-420}"
progress_extensions="${IB_GATEWAY_RECOVERY_PROGRESS_EXTENSIONS:-2}"
initial_snapshot_window_seconds="${IB_GATEWAY_RECOVERY_INITIAL_SNAPSHOT_WINDOW_SECONDS:-420}"
lock_file="${IB_GATEWAY_RECOVERY_LOCK_FILE:-/var/lock/ib_gateway_recovery.lock}"
lock_wait_seconds="${IB_GATEWAY_RECOVERY_LOCK_WAIT_SECONDS:-900}"

cd "${repo_dir}"
mkdir -p "$(dirname "${lock_file}")" 2>/dev/null || true
exec 9>"${lock_file}"
if [ "${lock_wait_seconds}" = 0 ]; then flock -n 9 || exit 0; else flock -w "${lock_wait_seconds}" 9; fi

inspect_epoch() {
  local identity
  identity="$(docker inspect --format '{{.Id}} {{.State.StartedAt}}' "${container_name}" 2>/dev/null)" || return 1
  read -r epoch_id epoch_started_at <<<"${identity}"
  [ -n "${epoch_id}" ] && [[ "${epoch_started_at}" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}T.*Z$ ]]
}

assessment_lower_bound() {
  local stage="$1"
  python3 - "${stage}" "${epoch_started_at}" "${initial_snapshot_window_seconds}" <<'PY'
import sys
from datetime import datetime, timedelta, timezone
stage, started_at, window = sys.argv[1:]
start = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
if stage == "initial":
    lower = max(start, datetime.now(timezone.utc) - timedelta(seconds=int(window)))
else:
    lower = start
print(lower.isoformat(timespec="microseconds").replace("+00:00", "Z"))
PY
}

snapshot_decision() {
  local stage="$1" expected_id="$2" expected_started_at="$3" lower decision
  if ! inspect_epoch || [ "${epoch_id}" != "${expected_id}" ] || [ "${epoch_started_at}" != "${expected_started_at}" ]; then
    echo epoch_changed; return 0
  fi
  lower="$(assessment_lower_bound "${stage}")" || { echo invalid; return 0; }
  decision="$({
    docker logs --timestamps --since "${lower}" "${expected_id}" 2>&1 | sed 's/^/D\t/' || printf 'X\n'
    docker exec "${expected_id}" sh -c '
      for p in /home/ibgateway/Jts/launcher.log /home/ibgateway/2fa.log; do
        [ ! -e "$p" ] || [ -f "$p" ] || exit 42
        [ ! -f "$p" ] || tail -n 400 "$p"
      done
    ' | sed 's/^/F\t/' || printf 'X\n'
  } | python3 -c '
import re, sys
from datetime import datetime, timezone
lower = datetime.fromisoformat(sys.argv[1].replace("Z", "+00:00"))
terminal = re.compile(r"IBC closing because login has not completed|(?:authentication|login).*(?:timeout|timed out|failed)", re.I)
progress = re.compile(r"IBC: (Starting Gateway|Login attempt|Second Factor Authentication|Login has completed|Configuration tasks completed)|Authentication window found|Auto-fill submitted|Passed token authentication|Authentication completed|Security code:", re.I)
seen_progress = False
for raw in sys.stdin:
    if raw == "X\n": print("invalid"); raise SystemExit
    try: _, line = raw.split("\t", 1)
    except ValueError: print("invalid"); raise SystemExit
    m = re.match(r"(\d{4}-\d\d-\d\d[T ]\d\d:\d\d:\d\d)(?:[.,:](\d{1,9}))?Z?", line)
    if not m: continue
    stamp = datetime.fromisoformat((m.group(1).replace(" ", "T") + "." + (m.group(2) or "0") + "+00:00"))
    if stamp < lower: continue
    if terminal.search(line): print("terminal"); raise SystemExit
    if progress.search(line): seen_progress = True
print("progress" if seen_progress else "none")
' "${lower}"
)" || decision=invalid
  if ! inspect_epoch || [ "${epoch_id}" != "${expected_id}" ] || [ "${epoch_started_at}" != "${expected_started_at}" ]; then echo epoch_changed; else echo "${decision}"; fi
}

wait_ready() { IB_GATEWAY_CONTAINER_NAME="$2" IB_GATEWAY_READY_TIMEOUT_SECONDS="$1" bash "${script_dir}/wait_for_ib_gateway_ready.sh" "${gateway_mode}"; }
assess_stage() {
  local timeout="$1" stage="$2" reassessments=0 extension decision
  while [ "$reassessments" -lt 2 ]; do
    inspect_epoch || return 1
    local assessed_id="$epoch_id" assessed_started="$epoch_started_at"
    CONTAINER_NAME="$assessed_id" bash "${script_dir}/ensure_2fa_bot_running.sh"
    wait_ready "$timeout" "$assessed_id" && return 0
    extension=0
    while [ "$extension" -lt "$progress_extensions" ]; do
      decision="$(snapshot_decision "$stage" "$assessed_id" "$assessed_started")"
      case "$decision" in terminal|invalid|none) return 1;; epoch_changed) reassessments=$((reassessments+1)); continue 2;; progress) ;; esac
      extension=$((extension+1)); wait_ready "$progress_wait_seconds" "$assessed_id" && return 0
    done
    return 1
  done
  return 1
}

docker compose up -d --no-build "${compose_service_name}"
assess_stage "$initial_wait_seconds" initial && exit 0
docker compose restart "${compose_service_name}"
assess_stage "$restart_wait_seconds" restart && exit 0
docker compose up -d --force-recreate --no-build "${compose_service_name}"
assess_stage "$recreate_wait_seconds" recreate && exit 0
exit 1
