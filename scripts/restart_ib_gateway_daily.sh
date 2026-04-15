#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "$0")" && pwd)"
repo_dir="$(cd "${script_dir}/.." && pwd)"
container_name="${IB_GATEWAY_CONTAINER_NAME:-ib-gateway}"
gateway_mode="${1:-${IB_GATEWAY_MODE:-paper}}"
ready_wait_seconds="${IB_GATEWAY_DAILY_RESTART_READY_WAIT_SECONDS:-240}"

cd "${repo_dir}"

echo "Restarting ${container_name} for scheduled IB Gateway refresh (mode=${gateway_mode})."
docker compose up -d --no-build
docker compose restart "${container_name}"

IB_GATEWAY_CONTAINER_NAME="${container_name}" \
IB_GATEWAY_RECOVERY_INITIAL_WAIT_SECONDS="${ready_wait_seconds}" \
  bash "${script_dir}/recover_ib_gateway_ready.sh" "${gateway_mode}"

echo "Scheduled IB Gateway refresh complete."
