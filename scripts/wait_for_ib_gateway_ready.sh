#!/usr/bin/env bash
set -euo pipefail

container_name="${IB_GATEWAY_CONTAINER_NAME:-ib-gateway}"
gateway_mode="${1:-${IB_GATEWAY_MODE:-paper}}"
ready_timeout_seconds="${IB_GATEWAY_READY_TIMEOUT_SECONDS:-240}"
poll_interval_seconds="${IB_GATEWAY_READY_POLL_INTERVAL_SECONDS:-5}"

case "${gateway_mode}" in
  paper)
    gateway_port=4002
    ;;
  live)
    gateway_port=4001
    ;;
  *)
    echo "Unsupported IB gateway mode: ${gateway_mode}" >&2
    exit 1
    ;;
esac

deadline=$((SECONDS + ready_timeout_seconds))

echo "Waiting for ${container_name} API to become ready on internal port ${gateway_port} (mode=${gateway_mode})"

while true; do
  if docker inspect --format '{{.State.Running}}' "${container_name}" 2>/dev/null | grep -Fxq 'true'; then
    if timeout 3 docker exec "${container_name}" bash -lc "exec 3<>/dev/tcp/127.0.0.1/${gateway_port}" >/dev/null 2>&1; then
      echo "IB gateway API is ready on internal port ${gateway_port} (mode=${gateway_mode})"
      exit 0
    fi
  fi

  if [ "${SECONDS}" -ge "${deadline}" ]; then
    echo "Timed out waiting for ${container_name} API readiness on internal port ${gateway_port}" >&2
    echo "--- docker compose ps ---" >&2
    docker compose ps >&2 || true
    echo "--- recent container logs ---" >&2
    docker logs --tail 120 "${container_name}" >&2 || true
    exit 1
  fi

  sleep "${poll_interval_seconds}"
done
