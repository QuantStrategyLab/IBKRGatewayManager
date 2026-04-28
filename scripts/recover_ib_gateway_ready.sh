#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "$0")" && pwd)"
repo_dir="$(cd "${script_dir}/.." && pwd)"
container_name="${IB_GATEWAY_CONTAINER_NAME:-ib-gateway}"
gateway_mode="${1:-${IB_GATEWAY_MODE:-paper}}"
initial_wait_seconds="${IB_GATEWAY_RECOVERY_INITIAL_WAIT_SECONDS:-240}"
restart_wait_seconds="${IB_GATEWAY_RECOVERY_RESTART_WAIT_SECONDS:-300}"
recreate_wait_seconds="${IB_GATEWAY_RECOVERY_RECREATE_WAIT_SECONDS:-360}"
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

echo "Ensuring ${container_name} is running before readiness check."
docker compose up -d --no-build

if wait_for_ready "${initial_wait_seconds}"; then
  exit 0
fi

echo "IB gateway API was not ready; restarting ${container_name} and retrying." >&2
docker compose ps >&2 || true
docker compose restart "${container_name}"

if wait_for_ready "${restart_wait_seconds}"; then
  exit 0
fi

echo "IB gateway API is still not ready; recreating ${container_name} and retrying." >&2
docker compose up -d --force-recreate --no-build "${container_name}"

if wait_for_ready "${recreate_wait_seconds}"; then
  exit 0
fi

echo "IB gateway API did not recover after restart/recreate." >&2
docker compose ps >&2 || true
docker logs --tail 160 "${container_name}" >&2 || true
exit 1
