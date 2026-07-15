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
# restart itself before the API socket listens. Extend only within the
# replacement container epoch, and never past a terminal authentication event.
progress_wait_seconds="${IB_GATEWAY_RECOVERY_PROGRESS_WAIT_SECONDS:-420}"
progress_extensions="${IB_GATEWAY_RECOVERY_PROGRESS_EXTENSIONS:-2}"
progress_regex="${IB_GATEWAY_RECOVERY_PROGRESS_REGEX:-IBC: (Starting Gateway|Login attempt|Second Factor Authentication|Login has completed|Configuration tasks completed|Found Gateway main window|Getting config dialog|Getting main window)|Authentication window found|Auto-fill submitted|Passed token authentication|Authentication completed|Security code:}"
default_terminal_regex='Connection reset by peer|Server disconnected|IBC: .*(Authentication|Login).*(timed out|timeout|failed)|IBC: .*(timed out|timeout).*(Authentication|Login)'
terminal_regex="${IB_GATEWAY_RECOVERY_TERMINAL_REGEX:-$default_terminal_regex}"
lock_file="${IB_GATEWAY_RECOVERY_LOCK_FILE:-/var/lock/ib_gateway_recovery.lock}"
lock_wait_seconds="${IB_GATEWAY_RECOVERY_LOCK_WAIT_SECONDS:-900}"
classifier="${script_dir}/classify_ib_gateway_epoch_activity.awk"

# shellcheck source=ib_gateway_container_epoch.sh
source "${script_dir}/ib_gateway_container_epoch.sh"

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
  local epoch_container_id="$2"

  IB_GATEWAY_CONTAINER_NAME="${epoch_container_id}" \
  IB_GATEWAY_READY_TIMEOUT_SECONDS="${timeout_seconds}" \
    bash "${script_dir}/wait_for_ib_gateway_ready.sh" "${gateway_mode}"
}

classify_epoch_activity() {
  local epoch_started_at="$1"

  awk \
    -v epoch_started_at="${epoch_started_at}" \
    -v progress_regex="${progress_regex}" \
    -v terminal_regex="${terminal_regex}" \
    -f "${classifier}"
}

gateway_epoch_activity_from_docker_logs() {
  local epoch_container_id="$1"
  local epoch_started_at="$2"

  docker logs --timestamps --since "${epoch_started_at}" "${epoch_container_id}" 2>&1 \
    | classify_epoch_activity "${epoch_started_at}"
}

gateway_epoch_activity_from_file_logs() {
  local epoch_container_id="$1"
  local epoch_started_at="$2"

  docker exec "${epoch_container_id}" sh -s <<'SH' \
    | classify_epoch_activity "${epoch_started_at}"
set -eu

for log_path in /home/ibgateway/Jts/launcher.log /home/ibgateway/2fa.log; do
  if [ -f "${log_path}" ]; then
    cat "${log_path}" 2>/dev/null || true
  fi
done
SH
}

gateway_epoch_activity() {
  local epoch_container_id="$1"
  local epoch_started_at="$2"
  local docker_activity file_activity

  if ! docker_activity="$(gateway_epoch_activity_from_docker_logs "${epoch_container_id}" "${epoch_started_at}")"; then
    echo "Unable to classify replacement epoch Docker logs for ${epoch_container_id}." >&2
    return 1
  fi
  if ! file_activity="$(gateway_epoch_activity_from_file_logs "${epoch_container_id}" "${epoch_started_at}")"; then
    echo "Unable to classify replacement epoch file logs for ${epoch_container_id}." >&2
    return 1
  fi
  if [ "${docker_activity}" = "terminal" ] || [ "${file_activity}" = "terminal" ]; then
    echo terminal
  elif [ "${docker_activity}" = "progress" ] || [ "${file_activity}" = "progress" ]; then
    echo progress
  else
    echo none
  fi
}

wait_for_ready_with_progress() {
  local timeout_seconds="$1"
  local stage="$2"
  local epoch_container_id="$3"
  local epoch_started_at="$4"
  local extension=0 activity

  if wait_for_ready "${timeout_seconds}" "${epoch_container_id}"; then
    return 0
  fi

  while [ "${extension}" -lt "${progress_extensions}" ]; do
    if ! activity="$(gateway_epoch_activity "${epoch_container_id}" "${epoch_started_at}")"; then
      echo "Replacement epoch activity is unavailable during ${stage}; refusing to extend readiness wait." >&2
      return 1
    fi
    if [ "${activity}" = "terminal" ]; then
      echo "Terminal IB gateway authentication event detected during ${stage} replacement epoch; refusing to extend readiness wait." >&2
      return 1
    fi
    if [ "${activity}" != "progress" ]; then
      return 1
    fi

    extension=$((extension + 1))
    echo "Current replacement epoch shows IB gateway login/config progress after ${stage} wait; extending readiness wait (${extension}/${progress_extensions}) by ${progress_wait_seconds}s before external recovery." >&2
    if wait_for_ready "${progress_wait_seconds}" "${epoch_container_id}"; then
      return 0
    fi
  done

  return 1
}

ensure_2fa_bot_running() {
  local epoch_container_id="$1"
  CONTAINER_NAME="${epoch_container_id}" bash "${script_dir}/ensure_2fa_bot_running.sh"
}

inspect_current_container() {
  local inspect_record

  inspect_record="$(ib_gateway_inspect_container_epoch "${container_name}")" || {
    echo "Unable to establish a valid identity/StartedAt epoch for ${container_name}." >&2
    return 1
  }
  read -r epoch_container_id epoch_started_at <<<"${inspect_record}"
}

replace_gateway_container() {
  local replacement_mode="$1"
  local old_container_id replacement_container_id replacement_started_at inspect_record

  old_container_id="$(docker inspect --format '{{.Id}}' "${container_name}" 2>/dev/null)" || {
    echo "Unable to capture the current container identity for ${container_name}." >&2
    return 1
  }
  [ -n "${old_container_id}" ] || return 1

  docker compose stop "${compose_service_name}"
  docker compose rm -f "${compose_service_name}"
  if docker inspect "${old_container_id}" >/dev/null 2>&1; then
    echo "Old container identity still exists after controlled removal." >&2
    return 1
  fi

  if [ "${replacement_mode}" = "recreate" ]; then
    docker compose up -d --force-recreate --no-build "${compose_service_name}"
  else
    docker compose up -d --no-build "${compose_service_name}"
  fi

  inspect_record="$(ib_gateway_inspect_container_epoch "${container_name}")" || {
    echo "Unable to inspect replacement container identity/StartedAt." >&2
    return 1
  }
  read -r replacement_container_id replacement_started_at <<<"${inspect_record}"
  ib_gateway_validate_replacement_epoch "${old_container_id}" "${replacement_container_id}" "${replacement_started_at}" || {
    echo "Replacement container identity/StartedAt validation failed closed." >&2
    return 1
  }
  epoch_container_id="${replacement_container_id}"
  epoch_started_at="${replacement_started_at}"
}

echo "Ensuring ${container_name} is running before readiness check."
docker compose up -d --no-build "${compose_service_name}"
inspect_current_container
ensure_2fa_bot_running "${epoch_container_id}"

if wait_for_ready_with_progress "${initial_wait_seconds}" "initial" "${epoch_container_id}" "${epoch_started_at}"; then
  exit 0
fi

echo "IB gateway API was not ready; replacing ${container_name} and retrying." >&2
docker compose ps >&2 || true
replace_gateway_container restart
ensure_2fa_bot_running "${epoch_container_id}"

if wait_for_ready_with_progress "${restart_wait_seconds}" "replacement" "${epoch_container_id}" "${epoch_started_at}"; then
  exit 0
fi

echo "IB gateway API is still not ready; recreating ${container_name} and retrying." >&2
replace_gateway_container recreate
ensure_2fa_bot_running "${epoch_container_id}"

if wait_for_ready_with_progress "${recreate_wait_seconds}" "recreate" "${epoch_container_id}" "${epoch_started_at}"; then
  exit 0
fi

echo "IB gateway API did not recover after controlled replacements." >&2
docker compose ps >&2 || true
docker logs --tail 160 "${epoch_container_id}" >&2 || true
exit 1
