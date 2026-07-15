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
lock_file="${IB_GATEWAY_RECOVERY_LOCK_FILE:-/var/lock/ib_gateway_recovery.lock}"
lock_wait_seconds="${IB_GATEWAY_RECOVERY_LOCK_WAIT_SECONDS:-900}"
classifier_wrapper="${script_dir}/classify_gateway_recovery_snapshot.sh"

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

inspect_epoch_identity() {
  local container_ref="$1"
  local identity

  identity="$(docker inspect --format '{{.Id}} {{.State.StartedAt}}' "${container_ref}" 2>/dev/null)" || return 1
  read -r epoch_container_id epoch_started_at <<<"${identity}"
  [ -n "${epoch_container_id}" ] \
    && [[ "${epoch_started_at}" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]+)?Z$ ]] \
    && [[ "${epoch_started_at}" != 0001-01-01T00:00:00* ]]
}

capture_epoch_decision() {
  local epoch_container_id="$1"
  local epoch_started_at="$2"
  local old_container_id="$3"
  local replacement_identity="$4"
  local -a classifier_args
  local decision

  classifier_args=(
    --epoch-container-id "${epoch_container_id}"
    --epoch-started-at "${epoch_started_at}"
  )
  if [ -n "${old_container_id}" ]; then
    classifier_args+=(--old-container-id "${old_container_id}")
  fi
  if [ "${replacement_identity}" = "true" ]; then
    classifier_args+=(--replacement-identity)
  fi

  if ! decision="$({
    if ! docker logs --timestamps --since "${epoch_started_at}" "${epoch_container_id}" 2>&1 \
      | sed "s/^/D\\t${epoch_container_id}\\t/"; then
      printf 'X\tdocker\n'
    fi
    if ! docker exec "${epoch_container_id}" sh -c '
      for log_path in /home/ibgateway/Jts/launcher.log /home/ibgateway/2fa.log; do
        if [ -e "${log_path}" ] && [ ! -f "${log_path}" ]; then
          exit 42
        fi
        if [ -f "${log_path}" ]; then
          cat "${log_path}"
        fi
      done
    ' | sed "s/^/F\\t${epoch_container_id}\\t/"; then
      printf 'X\tfile\n'
    fi
  } | "${classifier_wrapper}" "${classifier_args[@]}")"; then
    echo "Python recovery classifier invocation failed; refusing progress extension." >&2
    echo invalid
    return 0
  fi

  case "${decision}" in
    terminal|progress|none|invalid)
      echo "${decision}"
      ;;
    *)
      echo "Python recovery classifier returned an invalid decision; refusing progress extension." >&2
      echo invalid
      ;;
  esac
}

wait_for_ready_with_progress() {
  local timeout_seconds="$1"
  local stage="$2"
  local epoch_container_id="$3"
  local epoch_started_at="$4"
  local old_container_id="$5"
  local replacement_identity="$6"
  local extension=0 decision

  if wait_for_ready "${timeout_seconds}" "${epoch_container_id}"; then
    return 0
  fi

  # Freeze the bounded primitive event snapshot once for this attempt. Every
  # extension decision below uses this immutable result and never rereads logs.
  decision="$(capture_epoch_decision \
    "${epoch_container_id}" "${epoch_started_at}" "${old_container_id}" "${replacement_identity}")"
  case "${decision}" in
    terminal)
      echo "Terminal authentication event detected in the current recovery epoch; refusing extension." >&2
      return 1
      ;;
    invalid|none)
      echo "No safe progress evidence in the current immutable recovery snapshot; refusing extension." >&2
      return 1
      ;;
    progress)
      ;;
  esac

  while [ "${extension}" -lt "${progress_extensions}" ]; do
    extension=$((extension + 1))
    echo "Immutable recovery snapshot shows login/config progress after ${stage} wait;" \
      "extending readiness wait (${extension}/${progress_extensions}) by ${progress_wait_seconds}s." >&2
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

echo "Ensuring ${container_name} is running before readiness check."
docker compose up -d --no-build "${compose_service_name}"
if ! inspect_epoch_identity "${container_name}"; then
  echo "Unable to establish a valid initial container identity/StartedAt." >&2
  exit 1
fi
ensure_2fa_bot_running "${epoch_container_id}"

if wait_for_ready_with_progress \
  "${initial_wait_seconds}" "initial" "${epoch_container_id}" "${epoch_started_at}" "" "false"; then
  exit 0
fi

echo "IB gateway API was not ready; restarting ${container_name} and retrying." >&2
docker compose ps >&2 || true
docker compose restart "${compose_service_name}"
if ! inspect_epoch_identity "${container_name}"; then
  echo "Unable to establish a valid restart container identity/StartedAt." >&2
  exit 1
fi
ensure_2fa_bot_running "${epoch_container_id}"

if wait_for_ready_with_progress \
  "${restart_wait_seconds}" "restart" "${epoch_container_id}" "${epoch_started_at}" "" "false"; then
  exit 0
fi

echo "IB gateway API is still not ready; recreating ${container_name} and retrying." >&2
old_container_id="$(docker inspect --format '{{.Id}}' "${container_name}" 2>/dev/null)" || {
  echo "Unable to capture the old container identity before recreate." >&2
  exit 1
}
docker compose up -d --force-recreate --no-build "${compose_service_name}"
if ! inspect_epoch_identity "${container_name}" \
  || [ "${epoch_container_id}" = "${old_container_id}" ]; then
  echo "Unable to establish a distinct replacement container identity/StartedAt." >&2
  exit 1
fi
ensure_2fa_bot_running "${epoch_container_id}"

if wait_for_ready_with_progress \
  "${recreate_wait_seconds}" "recreate" "${epoch_container_id}" "${epoch_started_at}" \
  "${old_container_id}" "true"; then
  exit 0
fi

echo "IB gateway API did not recover after restart/recreate." >&2
docker compose ps >&2 || true
docker logs --tail 160 "${epoch_container_id}" >&2 || true
exit 1
