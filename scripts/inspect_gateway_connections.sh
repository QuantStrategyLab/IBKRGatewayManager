#!/usr/bin/env bash
set -euo pipefail

container_name="${1:-}"
api_port="${2:-}"

if [[ ! "${container_name}" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]*$ ]] || [[ ! "${api_port}" =~ ^[0-9]{1,5}$ ]] || (( api_port < 1 || api_port > 65535 )); then
  echo "GATEWAY_CONNECTION_INSPECTION=blocked reason=configuration_invalid"
  exit 1
fi

container_state=""
if ! container_state="$(sudo -n docker inspect --format '{{.State.Running}} {{.State.Pid}}' "${container_name}" 2>/dev/null)"; then
  echo "GATEWAY_CONNECTION_INSPECTION=blocked reason=container_inspection_failed"
  exit 1
fi

running="${container_state%% *}"
container_pid="${container_state#* }"
if [[ "${running}" != "true" && "${running}" != "false" ]] || [[ ! "${container_pid}" =~ ^[0-9]+$ ]]; then
  echo "GATEWAY_CONNECTION_INSPECTION=blocked reason=container_state_invalid"
  exit 1
fi
if [[ "${running}" == "true" ]] && (( container_pid <= 0 )); then
  echo "GATEWAY_CONNECTION_INSPECTION=blocked reason=container_pid_invalid"
  exit 1
fi

listener_output=""
if [[ "${running}" == "true" ]] && ! listener_output="$(sudo -n nsenter -t "${container_pid}" -n ss -H -ltn sport = ":${api_port}" 2>/dev/null)"; then
  echo "GATEWAY_CONNECTION_INSPECTION=blocked reason=socket_inspection_failed"
  exit 1
fi

established_output=""
if [[ "${running}" == "true" ]] && ! established_output="$(sudo -n nsenter -t "${container_pid}" -n ss -H -tn state established sport = ":${api_port}" 2>/dev/null)"; then
  echo "GATEWAY_CONNECTION_INSPECTION=blocked reason=socket_inspection_failed"
  exit 1
fi

listener_count=0
established_count=0
if [[ "${running}" == "true" ]]; then
  if [[ -n "${listener_output}" ]]; then
    listener_count="$(printf '%s\n' "${listener_output}" | wc -l | tr -d '[:space:]')"
  fi
  if [[ -n "${established_output}" ]]; then
    established_count="$(printf '%s\n' "${established_output}" | wc -l | tr -d '[:space:]')"
  fi
fi

case "${listener_count}:${established_count}" in
  *[!0-9:]* | :* | *:) echo "GATEWAY_CONNECTION_INSPECTION=blocked reason=socket_result_invalid"; exit 1 ;;
esac

observed_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "GATEWAY_CONNECTION_INSPECTION=observed"
echo "GATEWAY_CONTAINER_RUNNING=${running}"
if (( listener_count > 0 )); then
  echo "GATEWAY_API_LISTENER=true"
else
  echo "GATEWAY_API_LISTENER=false"
fi
echo "GATEWAY_ESTABLISHED_CONNECTION_COUNT=${established_count}"
echo "GATEWAY_CONNECTION_OBSERVED_AT_UTC=${observed_at}"
echo "GATEWAY_CONNECTION_INSPECTION_LIMIT=OBSERVATION_ONLY_NO_AUTH_OR_CONCURRENCY_ASSERTION"
