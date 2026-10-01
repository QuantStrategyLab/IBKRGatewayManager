#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd "$(dirname "$0")/.." && pwd)"
workflow_file="${repo_dir}/.github/workflows/read-only-vm-metadata-diagnostic.yml"
script_file="${repo_dir}/scripts/inspect_gateway_connections.sh"
tmp_dir="$(mktemp -d)"
trap 'rm -rf "${tmp_dir}"' EXIT

cat >"${tmp_dir}/sudo" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
[[ "${1:-}" == "-n" ]] || exit 90
shift
if [[ "${1:-}" == "docker" ]]; then
  [[ "${MOCK_DOCKER_FAIL:-false}" != "true" ]] || exit 11
  printf '%s %s\n' "${MOCK_RUNNING:-true}" "${MOCK_PID:-12345}"
  exit 0
fi
if [[ "${1:-}" == "nsenter" ]]; then
  [[ -z "${MOCK_TRACE_FILE:-}" ]] || printf '%s\n' "$*" >> "${MOCK_TRACE_FILE}"
  shift
  [[ "${1:-}" == "-t" ]] || exit 91
  [[ "${MOCK_PID:-12345}" == "${2:-}" ]] || exit 92
  shift 3
  [[ "${1:-}" == "ss" ]] || exit 93
  shift
  if [[ "${MOCK_SS_FAIL:-}" == "listener" && "${1:-}" == "-H" && "${2:-}" == "-ltn" ]]; then exit 12; fi
  if [[ "${MOCK_SS_FAIL:-}" == "established" && "${1:-}" == "-H" && "${2:-}" == "-tn" ]]; then exit 13; fi
  if [[ "${1:-}" == "-H" && "${2:-}" == "-ltn" && "${3:-}" == "sport" && "${4:-}" == "=" && "${5:-}" == ":4002" ]]; then
    printf '%s' "${MOCK_LISTENER_OUTPUT:-}"
    exit 0
  fi
  if [[ "${1:-}" == "-H" && "${2:-}" == "-tn" && "${3:-}" == "state" && "${4:-}" == "established" && "${5:-}" == "sport" && "${6:-}" == "=" && "${7:-}" == ":4002" ]]; then
    printf '%s' "${MOCK_ESTABLISHED_OUTPUT:-}"
    exit 0
  fi
fi
exit 94
SH
chmod +x "${tmp_dir}/sudo"

run_check() {
  env PATH="${tmp_dir}:${PATH}" "$@" bash "${script_file}" synthetic-container 4002
}

trace_file="${tmp_dir}/ss-arguments"
output="$(run_check MOCK_RUNNING=true MOCK_PID=54321 MOCK_TRACE_FILE="${trace_file}" \
  MOCK_LISTENER_OUTPUT=$'LISTEN 0 128 0.0.0.0:4002 0.0.0.0:*\n' \
  MOCK_ESTABLISHED_OUTPUT=$'ESTAB 0 0 10.20.30.40:4002 10.90.80.70:32100\nESTAB 0 0 10.20.30.40:4002 10.90.80.71:32101\n')"
grep -Fxq 'GATEWAY_CONNECTION_INSPECTION=observed' <<<"${output}"
grep -Fxq 'GATEWAY_CONTAINER_RUNNING=true' <<<"${output}"
grep -Fxq 'GATEWAY_API_LISTENER=true' <<<"${output}"
grep -Fxq 'GATEWAY_ESTABLISHED_CONNECTION_COUNT=2' <<<"${output}"
grep -Fxq 'GATEWAY_CONNECTION_INSPECTION_LIMIT=OBSERVATION_ONLY_NO_AUTH_OR_CONCURRENCY_ASSERTION' <<<"${output}"
grep -Eq '^GATEWAY_CONNECTION_OBSERVED_AT_UTC=[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$' <<<"${output}"
! grep -Eq '54321|10\.20\.30\.40|10\.90\.80\.' <<<"${output}"
grep -Fq 'ss -H -ltn sport = :4002' "${trace_file}"
grep -Fq 'ss -H -tn state established sport = :4002' "${trace_file}"

output="$(run_check MOCK_RUNNING=true MOCK_PID=321 MOCK_LISTENER_OUTPUT='' MOCK_ESTABLISHED_OUTPUT='')"
grep -Fxq 'GATEWAY_API_LISTENER=false' <<<"${output}"
grep -Fxq 'GATEWAY_ESTABLISHED_CONNECTION_COUNT=0' <<<"${output}"

output="$(run_check MOCK_RUNNING=false MOCK_PID=0)"
grep -Fxq 'GATEWAY_CONTAINER_RUNNING=false' <<<"${output}"
grep -Fxq 'GATEWAY_API_LISTENER=false' <<<"${output}"

if run_check MOCK_DOCKER_FAIL=true >"${tmp_dir}/failure"; then exit 1; fi
grep -Fxq 'GATEWAY_CONNECTION_INSPECTION=blocked reason=container_inspection_failed' "${tmp_dir}/failure"
if run_check MOCK_RUNNING=true MOCK_PID=321 MOCK_SS_FAIL=listener >"${tmp_dir}/failure"; then exit 1; fi
grep -Fxq 'GATEWAY_CONNECTION_INSPECTION=blocked reason=socket_inspection_failed' "${tmp_dir}/failure"
if run_check MOCK_RUNNING=true MOCK_PID=321 MOCK_SS_FAIL=established >"${tmp_dir}/failure"; then exit 1; fi
grep -Fxq 'GATEWAY_CONNECTION_INSPECTION=blocked reason=socket_inspection_failed' "${tmp_dir}/failure"
if env PATH="${tmp_dir}:${PATH}" bash "${script_file}" 'unsafe;name' 4002 >"${tmp_dir}/failure"; then exit 1; fi
grep -Fxq 'GATEWAY_CONNECTION_INSPECTION=blocked reason=configuration_invalid' "${tmp_dir}/failure"

grep -Fq 'inspect_connections:' "${workflow_file}"
grep -A3 -Fq 'inspect_connections:' "${workflow_file}"
grep -Fq 'default: false' "${workflow_file}"
grep -Fq '(inputs.inspect_connections || inputs.inspect_ssh_policy || inputs.remaining_gateways) && secrets.IB_GATEWAY_MATCHED_INDEX' "${workflow_file}"
grep -Fq 'parseProtectedGatewayIndex(process.env.MATCHED_INDEX)' "${workflow_file}"
grep -Fq 'Passive inspection requires protected current-gateway matching' "${workflow_file}"
grep -Fq 'Protected matched target connection configuration is incomplete' "${workflow_file}"
grep -Fq 'steps.metadata_check.outputs.gateway_ip_match_status == '\''match'\''' "${workflow_file}"
grep -Fq 'gcloud compute start-iap-tunnel' "${workflow_file}"
grep -Fq 'ss -H -tn state established sport = ":${api_port}"' "${script_file}"
grep -Fq 'gcloud secrets versions access latest' "${workflow_file}"
grep -Fq 'chmod 600 "${key_file}"' "${workflow_file}"
grep -Fq 'bash scripts/prepare_gateway_ssh_key.sh' "${workflow_file}"
grep -Fq 'scripts/classify_gateway_ssh_failure.py' "${workflow_file}"
grep -Fq 'trap cleanup_secret_fetch EXIT' "${workflow_file}"
grep -Fq 'if: ${{ always() && inputs.inspect_connections }}' "${workflow_file}"
grep -Fq 'rm -f -- "${SSH_KEY_FILE}"' "${workflow_file}"
grep -Fq 'MATCHED_INDEX: ${{ (inputs.inspect_connections || inputs.inspect_ssh_policy || inputs.remaining_gateways) && secrets.IB_GATEWAY_MATCHED_INDEX' "${workflow_file}"
grep -Fq 'NODE_OPTIONS: --require=${{ github.workspace }}/scripts/filter_github_action_auth_logs.cjs' "${workflow_file}"
test "$(grep -Fc 'NODE_OPTIONS: --require=${{ github.workspace }}/scripts/filter_github_action_auth_logs.cjs' "${workflow_file}")" -eq 2
grep -Fq "steps.gcloud_setup_filtered.outcome != 'success'" "${workflow_file}"
grep -Fq 'GCP_AUTH_ACTION_STATUS=failed' "${repo_dir}/scripts/filter_github_action_auth_logs.cjs"
! grep -Fq 'gcloud compute ssh' "${workflow_file}"
grep -Fq 'ssh-keygen -y -P' "${repo_dir}/scripts/prepare_gateway_ssh_key.sh"
! grep -Fq 'docker exec' "${script_file}"
! grep -Fq 'docker logs' "${script_file}"
! grep -Fq '4001' "${script_file}"
! grep -Fq '4002' "${script_file}"

echo "PASS: passive Gateway inspection status, failures, counts, and privacy"
