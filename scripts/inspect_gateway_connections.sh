#!/usr/bin/env bash
set -euo pipefail

container_name="${1:-}"
api_port="${2:-}"
source_presence="${3:-}"

if [[ ! "${container_name}" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]*$ ]] || [[ ! "${api_port}" =~ ^[0-9]{1,5}$ ]] || (( api_port < 1 || api_port > 65535 )) || [[ -n "${source_presence}" && "${source_presence}" != "source-presence" ]] || (( $# > 3 )); then
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

presence_output=""
if [[ "${source_presence}" == "source-presence" ]]; then
  # Capture only socket/port-mapping metadata. No process arguments, container
  # environment, HTTP request, broker request, login or configuration mutation.
  host_api=""
  host_web=""
  if ! host_api="$(sudo -n ss -H -ltn sport = ":${api_port}" 2>/dev/null)" || \
     ! host_web="$(sudo -n ss -H -ltn sport = :5000 2>/dev/null)"; then
    echo "GATEWAY_CONNECTION_INSPECTION=blocked reason=socket_inspection_failed"
    exit 1
  fi
  mapping=container_stopped
  mapped_listener=unknown
  container_web=unknown
  if [[ "${running}" == "true" ]]; then
    ports=""
    if ! ports="$(sudo -n docker inspect --format '{{json .NetworkSettings.Ports}}' "${container_name}" 2>/dev/null)"; then
      echo "GATEWAY_CONNECTION_INSPECTION=blocked reason=port_mapping_inspection_failed"
      exit 1
    fi
    mapped_port=""
    if ! mapped_port="$(printf '%s' "${ports}" | python3 -c '
import json, re, sys
try:
    ports = json.load(sys.stdin)
    if ports is None:
        ports = {}
    if not isinstance(ports, dict):
        raise ValueError()
    selected = set()
    for port, bindings in ports.items():
        if not isinstance(port, str) or not re.fullmatch(r"[0-9]{1,5}/(?:tcp|udp)", port):
            raise ValueError()
        number = int(port.split("/")[0])
        if not 0 < number <= 65535 or (bindings is not None and not isinstance(bindings, list)):
            raise ValueError()
        for binding in bindings or []:
            if not isinstance(binding, dict) or not isinstance(binding.get("HostPort"), str):
                raise ValueError()
            if port.endswith("/tcp") and binding["HostPort"] == sys.argv[1]:
                selected.add(number)
    if len(selected) > 1:
        raise ValueError()
    print(next(iter(selected), 0))
except Exception:
    sys.exit(1)
' "${api_port}" 2>/dev/null)"; then
      echo "GATEWAY_CONNECTION_INSPECTION=blocked reason=port_mapping_invalid"
      exit 1
    fi
    web_sockets=""
    if ! web_sockets="$(sudo -n nsenter -t "${container_pid}" -n ss -H -ltn sport = :5000 2>/dev/null)"; then
      echo "GATEWAY_CONNECTION_INSPECTION=blocked reason=socket_inspection_failed"
      exit 1
    fi
    container_web=false
    [[ -z "${web_sockets}" ]] || container_web=true
    mapping=not_published
    if (( mapped_port > 0 )); then
      mapped_sockets=""
      if ! mapped_sockets="$(sudo -n nsenter -t "${container_pid}" -n ss -H -ltn sport = ":${mapped_port}" 2>/dev/null)"; then
        echo "GATEWAY_CONNECTION_INSPECTION=blocked reason=socket_inspection_failed"
        exit 1
      fi
      mapping=observed
      mapped_listener=false
      [[ -z "${mapped_sockets}" ]] || mapped_listener=true
    fi
  fi
  host_api_listener=false
  host_web_listener=false
  [[ -z "${host_api}" ]] || host_api_listener=true
  [[ -z "${host_web}" ]] || host_web_listener=true
  presence_output="$(printf '%s\n' \
    "GATEWAY_PUBLISHED_API_MAPPING=${mapping}" \
    "GATEWAY_PUBLISHED_CONTAINER_API_LISTENER=${mapped_listener}" \
    "GATEWAY_HOST_API_LISTENER=${host_api_listener}" \
    "GATEWAY_HOST_WEB_DEFAULT_PORT_LISTENER=${host_web_listener}" \
    "GATEWAY_CONTAINER_WEB_DEFAULT_PORT_LISTENER=${container_web}")"
fi

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
if [[ -n "${presence_output}" ]]; then printf '%s\n' "${presence_output}"; fi
