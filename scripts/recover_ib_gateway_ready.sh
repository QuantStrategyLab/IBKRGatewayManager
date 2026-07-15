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
progress_regex="${IB_GATEWAY_RECOVERY_PROGRESS_REGEX:-IBC: (Starting Gateway|Login attempt|Second Factor Authentication|Login has completed|Configuration tasks completed|Found Gateway main window|Getting config dialog|Getting main window)|Authentication window found|Auto-fill submitted|Passed token authentication|Authentication completed|Security code:}"
terminal_regex="${IB_GATEWAY_RECOVERY_TERMINAL_REGEX:-Connection reset by peer|Server disconnected|IBC: .*(Authentication|Login).*(timed out|timeout|failed)|IBC: .*(timed out|timeout).*(Authentication|Login)}"
lock_file="${IB_GATEWAY_RECOVERY_LOCK_FILE:-/var/lock/ib_gateway_recovery.lock}"
lock_wait_seconds="${IB_GATEWAY_RECOVERY_LOCK_WAIT_SECONDS:-900}"

cd "${repo_dir}"

mkdir -p "$(dirname "${lock_file}")" 2>/dev/null || true
exec 9>"${lock_file}"
if [ "${lock_wait_seconds}" = "0" ]; then
  if ! flock -n 9; then
    echo "Another IB gateway recovery is already running; skipping this check."
    exit 0
  fi
elif ! flock -w "${lock_wait_seconds}" 9; then
  echo "Timed out waiting for IB gateway recovery lock: ${lock_file}" >&2
  exit 1
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

gateway_recently_terminal_from_docker_logs() {
  docker logs --since "${progress_window_seconds}s" "${container_name}" 2>&1 \
    | grep -Eiq "${terminal_regex}"
}

gateway_recently_terminal_from_file_logs() {
  docker exec "${container_name}" sh -s -- "${progress_window_seconds}" "${terminal_regex}" <<'SH'
set -eu

progress_window_seconds="$1"
terminal_regex="$2"
now="$(date +%s)"
cutoff_timestamp="$(date -u -d "@$((now - progress_window_seconds))" "+%Y-%m-%d %H:%M:%S")"

for log_path in /home/ibgateway/Jts/launcher.log /home/ibgateway/2fa.log; do
  if [ ! -f "${log_path}" ]; then
    continue
  fi

  log_mtime="$(stat -c %Y "${log_path}" 2>/dev/null || echo 0)"
  if [ $((now - log_mtime)) -le "${progress_window_seconds}" ]; then
    tail -n 400 "${log_path}" 2>/dev/null \
      | awk -v cutoff_timestamp="${cutoff_timestamp}" -v terminal_regex="${terminal_regex}" '
          substr($0, 1, 19) >= cutoff_timestamp && $0 ~ terminal_regex { found = 1 }
          END { exit found ? 0 : 1 }
        ' && exit 0
  fi
done

exit 1
SH
}

gateway_recently_terminal() {
  gateway_recently_terminal_from_docker_logs || gateway_recently_terminal_from_file_logs
}

wait_for_ready_with_progress() {
  local timeout_seconds="$1"
  local stage="$2"
  local extension=0

  if wait_for_ready "${timeout_seconds}"; then
    return 0
  fi

  while [ "${extension}" -lt "${progress_extensions}" ]; do
    if gateway_recently_terminal; then
      echo "Recent terminal IB gateway authentication failure detected after ${stage} wait; skipping progress extension." >&2
      return 1
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
docker compose up -d --no-build "${compose_service_name}"
ensure_2fa_bot_running

if wait_for_ready_with_progress "${initial_wait_seconds}" "initial"; then
  exit 0
fi

echo "IB gateway API was not ready; restarting ${container_name} and retrying." >&2
docker compose ps >&2 || true
docker compose restart "${compose_service_name}"
ensure_2fa_bot_running

if wait_for_ready_with_progress "${restart_wait_seconds}" "restart"; then
  exit 0
fi

echo "IB gateway API is still not ready; recreating ${container_name} and retrying." >&2
docker compose up -d --force-recreate --no-build "${compose_service_name}"
ensure_2fa_bot_running

if wait_for_ready_with_progress "${recreate_wait_seconds}" "recreate"; then
  exit 0
fi

echo "IB gateway API did not recover after restart/recreate." >&2
docker compose ps >&2 || true
docker logs --tail 160 "${container_name}" >&2 || true
exit 1
