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
# IBC can spend several minutes in first-run login/config flows and then
# restart itself before the API socket listens. Do not interrupt that progress.
progress_wait_seconds="${IB_GATEWAY_RECOVERY_PROGRESS_WAIT_SECONDS:-420}"
progress_extensions="${IB_GATEWAY_RECOVERY_PROGRESS_EXTENSIONS:-2}"
progress_window_seconds="${IB_GATEWAY_RECOVERY_PROGRESS_WINDOW_SECONDS:-420}"
progress_regex="${IB_GATEWAY_RECOVERY_PROGRESS_REGEX:-IBC: (Starting Gateway|Login attempt|Second Factor Authentication|Login has completed|Configuration tasks completed|Found Gateway main window|Getting config dialog|Getting main window)|Authentication window found|Auto-fill submitted|Dismissing post-login dialog|Passed token authentication|Authentication completed|Security code:}"
transient_dialog_restart_attempts="${IB_GATEWAY_TRANSIENT_DIALOG_RESTART_ATTEMPTS:-1}"
transient_dialog_restart_wait_seconds="${IB_GATEWAY_TRANSIENT_DIALOG_RESTART_WAIT_SECONDS:-180}"
lock_file="${IB_GATEWAY_RECOVERY_LOCK_FILE:-/var/lock/ib_gateway_recovery.lock}"
lock_wait_seconds="${IB_GATEWAY_RECOVERY_LOCK_WAIT_SECONDS:-900}"
maintenance_deadline_epoch="${IB_GATEWAY_MAINTENANCE_DEADLINE_EPOCH:-}"
transient_dialog_restart_count=0

fail_recovery() {
  local stage="$1"
  local exit_code="${2:-1}"
  echo "GATEWAY_RECOVERY_FAILURE_STAGE=${stage}" >&2
  exit "${exit_code}"
}

current_recovery_epoch() {
  if [ -n "${IB_GATEWAY_RECOVERY_NOW_EPOCH:-}" ]; then
    echo "${IB_GATEWAY_RECOVERY_NOW_EPOCH}"
  else
    date +%s
  fi
}

stop_if_maintenance_deadline_reached() {
  local action_label="$1"
  if [ -n "${maintenance_deadline_epoch}" ] && [ "$(current_recovery_epoch)" -ge "${maintenance_deadline_epoch}" ]; then
    echo "Maintenance window deadline (${maintenance_deadline_epoch}) reached before ${action_label}; skipping disruptive operation." >&2
    exit 10
  fi
  return 0
}

if [ -n "${maintenance_deadline_epoch}" ] && ! [[ "${maintenance_deadline_epoch}" =~ ^[0-9]+$ ]]; then
  fail_recovery "RECOVERY_CONFIGURATION_INVALID" 2
fi

for value_name in transient_dialog_restart_attempts transient_dialog_restart_wait_seconds; do
  value="${!value_name}"
  if ! [[ "${value}" =~ ^[0-9]+$ ]] || { [ "${value_name}" = "transient_dialog_restart_wait_seconds" ] && [ "${value}" -eq 0 ]; }; then
    fail_recovery "RECOVERY_CONFIGURATION_INVALID" 2
  fi
done

cd "${repo_dir}"

mkdir -p "$(dirname "${lock_file}")" 2>/dev/null || true
exec 9>"${lock_file}"
if [ "${lock_wait_seconds}" = "0" ]; then
  if ! flock -n 9; then
    echo "Another IB gateway recovery is already running; skipping this check."
    exit 0
  fi
elif ! flock -w "${lock_wait_seconds}" 9; then
  fail_recovery "RECOVERY_LOCK_TIMEOUT"
fi

echo "Acquired IB gateway recovery lock: ${lock_file}"

wait_for_ready() {
  local timeout_seconds="$1"
  IB_GATEWAY_CONTAINER_NAME="${container_name}" \
  IB_GATEWAY_READY_TIMEOUT_SECONDS="${timeout_seconds}" \
    bash "${script_dir}/wait_for_ib_gateway_ready.sh" "${gateway_mode}"
}

gateway_recently_progressing_from_docker_logs() {
  docker logs --since "${progress_window_seconds}s" "${container_name}" 2>&1 \
    | grep -Eiq "${progress_regex}"
}

gateway_recently_progressing_from_file_logs() {
  docker exec "${container_name}" sh -s -- "${progress_window_seconds}" "${progress_regex}" <<'SH'
set -eu

progress_window_seconds="$1"
progress_regex="$2"
now="$(date +%s)"
cutoff_timestamp="$(date -u -d "@$((now - progress_window_seconds))" "+%Y-%m-%d %H:%M:%S")"

for log_path in /home/ibgateway/Jts/launcher.log /home/ibgateway/2fa.log; do
  if [ ! -f "${log_path}" ]; then
    continue
  fi

  log_mtime="$(stat -c %Y "${log_path}" 2>/dev/null || echo 0)"
  if [ $((now - log_mtime)) -le "${progress_window_seconds}" ]; then
    tail -n 400 "${log_path}" 2>/dev/null \
      | awk -v cutoff_timestamp="${cutoff_timestamp}" -v progress_regex="${progress_regex}" '
          substr($0, 1, 19) >= cutoff_timestamp && $0 ~ progress_regex { found = 1 }
          END { exit found ? 0 : 1 }
        ' && exit 0
  fi
done

exit 1
SH
}

gateway_recently_progressing() {
  gateway_recently_progressing_from_docker_logs || gateway_recently_progressing_from_file_logs
}

gateway_ui_blocker_present() {
  IB_GATEWAY_CONTAINER_NAME="${container_name}" \
    bash "${script_dir}/detect_gateway_ui_blocker.sh"
}

stop_for_gateway_ui_blocker() {
  fail_recovery "GATEWAY_UI_BLOCKER" 3
}

recover_from_gateway_ui_blocker() {
  if [ "${transient_dialog_restart_count}" -ge "${transient_dialog_restart_attempts}" ]; then
    stop_for_gateway_ui_blocker
  fi

  stop_if_maintenance_deadline_reached "dialog recovery restart"
  transient_dialog_restart_count=$((transient_dialog_restart_count + 1))
  echo "Compact Gateway dialog observed while the API is unavailable; restarting without acknowledging the dialog (${transient_dialog_restart_count}/${transient_dialog_restart_attempts})." >&2
  docker compose restart "${compose_service_name}"
  ensure_2fa_bot_running

  if wait_for_ready "${transient_dialog_restart_wait_seconds}"; then
    exit 0
  fi

  if gateway_ui_blocker_present; then
    stop_for_gateway_ui_blocker
  fi

  fail_recovery "DIALOG_RECOVERY_NOT_READY"
}

wait_for_ready_with_progress() {
  local timeout_seconds="$1"
  local stage="$2"
  local extension=0

  if wait_for_ready "${timeout_seconds}"; then
    return 0
  fi

  while [ "${extension}" -lt "${progress_extensions}" ]; do
    if [ -n "${maintenance_deadline_epoch}" ] && [ "$(current_recovery_epoch)" -ge "${maintenance_deadline_epoch}" ]; then
      return 1
    fi

    if gateway_ui_blocker_present; then
      return 3
    fi

    if ! gateway_recently_progressing; then
      return 1
    fi

    extension=$((extension + 1))
    echo "Recent IB gateway login/config progress detected after ${stage} wait; extending readiness wait (${extension}/${progress_extensions}) by ${progress_wait_seconds}s before external recovery." >&2
    if wait_for_ready "${progress_wait_seconds}"; then
      return 0
    fi
  done

  return 1
}

ensure_2fa_bot_running() {
  CONTAINER_NAME="${container_name}" bash "${script_dir}/ensure_2fa_bot_running.sh"
}

echo "Ensuring ${container_name} is running before readiness check."
if ! docker compose up -d --no-build "${compose_service_name}"; then
  fail_recovery "CONTAINER_START_FAILED"
fi
if ! ensure_2fa_bot_running; then
  fail_recovery "TWOFA_WATCHER_FAILED"
fi

if gateway_ui_blocker_present; then
  recover_from_gateway_ui_blocker
fi

if wait_for_ready_with_progress "${initial_wait_seconds}" "initial"; then
  exit 0
else
  initial_wait_status=$?
fi

if [ "${initial_wait_status}" -eq 3 ]; then
  recover_from_gateway_ui_blocker
fi

stop_if_maintenance_deadline_reached "container restart"
echo "IB gateway API was not ready; restarting ${container_name} and retrying." >&2
if ! docker compose restart "${compose_service_name}"; then
  fail_recovery "CONTAINER_RESTART_FAILED"
fi
if ! ensure_2fa_bot_running; then
  fail_recovery "TWOFA_WATCHER_FAILED"
fi

if wait_for_ready_with_progress "${restart_wait_seconds}" "restart"; then
  exit 0
else
  restart_wait_status=$?
fi

if [ "${restart_wait_status}" -eq 3 ]; then
  recover_from_gateway_ui_blocker
fi

stop_if_maintenance_deadline_reached "container force-recreate"
echo "IB gateway API is still not ready; recreating ${container_name} and retrying." >&2
if ! docker compose up -d --force-recreate --no-build "${compose_service_name}"; then
  fail_recovery "CONTAINER_RECREATE_FAILED"
fi
if ! ensure_2fa_bot_running; then
  fail_recovery "TWOFA_WATCHER_FAILED"
fi

if wait_for_ready_with_progress "${recreate_wait_seconds}" "recreate"; then
  exit 0
else
  recreate_wait_status=$?
fi

if [ "${recreate_wait_status}" -eq 3 ]; then
  recover_from_gateway_ui_blocker
fi

fail_recovery "GATEWAY_NOT_READY_AFTER_RECREATE"
