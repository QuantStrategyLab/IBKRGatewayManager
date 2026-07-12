#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd "$(dirname "$0")/.." && pwd)"
workflow_file="$repo_dir/.github/workflows/main.yml"
maintenance_workflow_file="$repo_dir/.github/workflows/remote-maintenance.yml"
diagnose_workflow_file="$repo_dir/.github/workflows/diagnose.yml"

grep -Fq 'target:' "$workflow_file"
grep -Fq 'IB_GATEWAY_TARGETS_JSON' "$workflow_file"
grep -Fq 'matrix: ${{ fromJSON(needs.select-targets.outputs.matrix) }}' "$workflow_file"
grep -Fq 'GCP_PROJECT_ID: ${{ matrix.target.gcp_project_id }}' "$workflow_file"
grep -Fq '"gcp_project_id": env("LEGACY_GCP_PROJECT_ID", "interactivebrokersquant")' "$workflow_file"
grep -Fq 'providers/github-ibkr-gateway-main' "$workflow_file"
grep -Fq 'ibkr-gateway-deploy@interactivebrokersquant.iam.gserviceaccount.com' "$workflow_file"
grep -Fq 'id-token: write' "$workflow_file"
grep -Fq 'timeout-minutes: 60' "$workflow_file"
grep -Fq 'sync_github_secrets_to_secret_manager:' "$workflow_file"
grep -Fq 'deploy_mode:' "$workflow_file"
grep -Fq 'workload_identity_provider: ${{ env.GCP_WORKLOAD_IDENTITY_PROVIDER }}' "$workflow_file"
grep -Fq 'service_account: ${{ env.GCP_WORKLOAD_IDENTITY_SERVICE_ACCOUNT }}' "$workflow_file"
grep -Fq "DEPLOY_EVENT_NAME: \${{ github.event_name }}" "$workflow_file"
grep -Fq "WORKFLOW_DISPATCH_MODE: \${{ github.event.inputs.deploy_mode }}" "$workflow_file"
grep -Fq 'vars.IB_GATEWAY_INSTANCE_NAME' "$workflow_file"
grep -Fq 'vars.IB_GATEWAY_ZONE' "$workflow_file"
grep -Fq 'vars.IB_GATEWAY_MODE' "$workflow_file"
grep -Fq 'vars.IB_GATEWAY_CONTAINER_NAME' "$workflow_file"
grep -Fq 'vars.IB_GATEWAY_COMPOSE_PROJECT_NAME' "$workflow_file"
grep -Fq 'vars.IB_GATEWAY_COMPOSE_SERVICE_NAME' "$workflow_file"
grep -Fq 'vars.IB_GATEWAY_UNIT_SUFFIX' "$workflow_file"
grep -Fq 'vars.IB_GATEWAY_LIVE_HOST_PORT' "$workflow_file"
grep -Fq 'vars.IB_GATEWAY_PAPER_HOST_PORT' "$workflow_file"
grep -Fq 'vars.IB_GATEWAY_VNC_HOST_ADDRESS' "$workflow_file"
grep -Fq 'vars.IB_GATEWAY_VNC_HOST_PORT' "$workflow_file"
grep -Fq 'vars.IB_GATEWAY_GCE_USER' "$workflow_file"
grep -Fq 'vars.IB_GATEWAY_DEPLOY_PATH' "$workflow_file"
grep -Fq 'vars.IB_GATEWAY_CLOUD_RUN_EGRESS_CIDR' "$workflow_file"
grep -Fq 'vars.IB_GATEWAY_ALLOW_CONNECTIONS_FROM_LOCALHOST_ONLY' "$workflow_file"
grep -Fq 'vars.IB_GATEWAY_TWS_ACCEPT_INCOMING' "$workflow_file"
grep -Fq 'vars.IB_GATEWAY_READ_ONLY_API' "$workflow_file"
grep -Fq 'vars.IB_GATEWAY_TWOFA_DEVICE' "$workflow_file"
grep -Fq 'vars.IB_GATEWAY_2FA_AUTOFILL' "$workflow_file"
grep -Fq 'vars.IB_GATEWAY_2FA_MAX_SUBMISSIONS' "$workflow_file"
grep -Fq 'vars.IB_GATEWAY_2FA_MAX_SUBMISSIONS_PER_WINDOW' "$workflow_file"
grep -Fq 'vars.IB_GATEWAY_2FA_SUBMISSION_RESET_SECONDS' "$workflow_file"
grep -Fq 'vars.IB_GATEWAY_SSH_PRIVATE_KEY_SECRET_NAME' "$workflow_file"
grep -Fq 'vars.IB_GATEWAY_TWS_USERID_SECRET_NAME' "$workflow_file"
grep -Fq 'vars.IB_GATEWAY_TWS_PASSWORD_SECRET_NAME' "$workflow_file"
grep -Fq 'vars.IB_GATEWAY_TOTP_SECRET_SECRET_NAME' "$workflow_file"
grep -Fq 'vars.IB_GATEWAY_VNC_SERVER_PASSWORD_SECRET_NAME' "$workflow_file"
grep -Fq 'gcloud secrets versions access latest' "$workflow_file"
grep -Fq -- '--scp-flag="-o ServerAliveInterval=30"' "$workflow_file"
grep -Fq 'resolve_secret()' "$workflow_file"
grep -Fq 'require_secret_source()' "$workflow_file"
grep -Fq 'Sync GitHub secrets to Secret Manager' "$workflow_file"
grep -Fq 'gcloud secrets versions add "${secret_name}"' "$workflow_file"
grep -Fq "paths:" "$workflow_file"
grep -Fq "'scripts/**'" "$workflow_file"
grep -Fq "'container_overrides/**'" "$workflow_file"
! grep -Fq "'.github/workflows/main.yml'" "$workflow_file"
grep -Fq 'DEPLOY_MODE="full"' "$workflow_file"
grep -Fq 'if [ "${DEPLOY_EVENT_NAME}" = "schedule" ]; then' "$workflow_file"
grep -Fq 'elif [ "${DEPLOY_EVENT_NAME}" = "workflow_dispatch" ]; then' "$workflow_file"
grep -Fq 'DEPLOY_MODE="${WORKFLOW_DISPATCH_MODE:-keepalive}"' "$workflow_file"
grep -Fq 'Scheduled keepalive mode: skip docker build' "$workflow_file"
grep -Fq 'reset_instance_and_wait_for_ssh()' "$workflow_file"
grep -Fq 'run_remote_ssh()' "$workflow_file"
grep -Fq 'copy_remote_file()' "$workflow_file"
grep -Fq 'git archive --format=tar.gz' "$workflow_file"
grep -Fq 'tar -xzf' "$workflow_file"
grep -Fq 'gcloud compute instances reset "${GCE_INSTANCE_NAME}"' "$workflow_file"
grep -Fq 'run_remote_ssh "Repository sync" "${REMOTE_SYNC_COMMAND}"' "$workflow_file"
grep -Fq 'copy_remote_file "${ENV_FILE}" "${DEPLOY_PATH}/.env"' "$workflow_file"
grep -Fq 'sudo bash ./scripts/ensure_host_swap.sh' "$workflow_file"
grep -Fq 'resolve_ibkr_gateway_unit_names "\${container_name}" "\${IB_GATEWAY_UNIT_SUFFIX:-}"' "$workflow_file"
grep -Fq 'sudo systemctl stop "\${IBKR_GATEWAY_HEALTHCHECK_TIMER}" "\${IBKR_GATEWAY_HEALTHCHECK_SERVICE}" 2>/dev/null || true' "$workflow_file"
grep -Fq 'bash ./scripts/install_gateway_health_watcher.sh' "$workflow_file"
grep -Fq 'restore_gateway_watchers()' "$workflow_file"
grep -Fq "trap 'status=\\\$?; if [ \"\\\${watchers_restored}\" != \"true\" ]; then restore_gateway_watchers || true; fi; exit \"\\\${status}\"' EXIT" "$workflow_file"
grep -Fq "sudo env IB_GATEWAY_CONTAINER_NAME=\"\\\${container_name}\" IB_GATEWAY_COMPOSE_SERVICE_NAME=\"\\\${compose_service_name}\" bash ./scripts/recover_ib_gateway_ready.sh '\${IB_GATEWAY_MODE}'" "$workflow_file"
grep -Fq 'sudo systemctl status "\${IBKR_GATEWAY_HEALTHCHECK_TIMER}" --no-pager' "$workflow_file"
grep -Fq 'sudo systemctl status "\${IBKR_GATEWAY_DAILY_RESTART_TIMER}" --no-pager' "$workflow_file"
grep -Fq 'Full deploy mode: rebuilding container' "$workflow_file"

recover_lines=()
while IFS= read -r line_number; do
  recover_lines+=("$line_number")
done < <(grep -nF "bash ./scripts/recover_ib_gateway_ready.sh '\${IB_GATEWAY_MODE}'" "$workflow_file" | cut -d: -f1)

health_watcher_lines=()
while IFS= read -r line_number; do
  health_watcher_lines+=("$line_number")
done < <(grep -nF 'bash ./scripts/install_gateway_health_watcher.sh' "$workflow_file" | cut -d: -f1)
restore_call_lines=()
while IFS= read -r line_number; do
  restore_call_lines+=("$line_number")
done < <(grep -nFx '          restore_gateway_watchers' "$workflow_file" | cut -d: -f1)
test "${#recover_lines[@]}" -eq 2
test "${#health_watcher_lines[@]}" -eq 2
test "${#restore_call_lines[@]}" -eq 2
for i in 0 1; do
  if [ "${recover_lines[$i]}" -ge "${restore_call_lines[$i]}" ]; then
    echo "Gateway watchers must be restored after explicit recovery in deploy block $i" >&2
    exit 1
  fi
done

grep -Fq '"TRADING_MODE": os.environ["IB_GATEWAY_MODE"]' "$workflow_file"
grep -Fq '"ACCEPT_API_FROM_IP": os.environ["CLOUD_RUN_EGRESS_CIDR"]' "$workflow_file"
grep -Fq '"IB_GATEWAY_CONTAINER_NAME": os.environ.get("IB_GATEWAY_CONTAINER_NAME", "")' "$workflow_file"
grep -Fq '"COMPOSE_PROJECT_NAME": os.environ.get("IB_GATEWAY_COMPOSE_PROJECT_NAME", "")' "$workflow_file"
grep -Fq '"IB_GATEWAY_LIVE_HOST_PORT": os.environ.get("IB_GATEWAY_LIVE_HOST_PORT", "")' "$workflow_file"
grep -Fq '"TWOFA_DEVICE": os.environ.get("TWOFA_DEVICE", "")' "$workflow_file"
grep -Fq '"IBKR_2FA_AUTOFILL": os.environ.get("IBKR_2FA_AUTOFILL", "")' "$workflow_file"
grep -Fq '"IBKR_2FA_MAX_SUBMISSIONS": os.environ.get("IBKR_2FA_MAX_SUBMISSIONS") or "3"' "$workflow_file"
grep -Fq '"IBKR_2FA_MAX_SUBMISSIONS_PER_WINDOW": os.environ.get("IBKR_2FA_MAX_SUBMISSIONS_PER_WINDOW") or "1"' "$workflow_file"
grep -Fq '"IBKR_2FA_SUBMISSION_RESET_SECONDS": os.environ.get("IBKR_2FA_SUBMISSION_RESET_SECONDS") or "0"' "$workflow_file"
grep -Fq 'REMOTE_DEPLOY_COMMAND=$(cat <<EOF' "$workflow_file"
if grep -Fq 'DEPLOY_SCRIPT=' "$workflow_file"; then
  echo "Unexpected DEPLOY_SCRIPT temp upload flow still present" >&2
  exit 1
fi

for legacy_pattern in \
  'credentials_json: ${{ secrets.GCP_SA_KEY }}' \
  'secrets.GCP_SA_KEY' \
  'vars.GCE_USER' \
  'secrets.GCE_USER' \
  'secrets.GCE_INSTANCE_NAME' \
  'secrets.GCE_ZONE' \
  'secrets.TRADING_MODE' \
  'vars.DEPLOY_PATH' \
  'secrets.DEPLOY_PATH' \
  'vars.CLOUD_RUN_EGRESS_CIDR' \
  'secrets.ACCEPT_API_FROM_IP' \
  'vars.ALLOW_CONNECTIONS_FROM_LOCALHOST_ONLY' \
  'secrets.ALLOW_CONNECTIONS_FROM_LOCALHOST_ONLY' \
  'vars.TWS_ACCEPT_INCOMING' \
  'vars.READ_ONLY_API'
do
  if grep -Fq "$legacy_pattern" "$workflow_file"; then
    echo "Unexpected legacy config reference remains: $legacy_pattern" >&2
    exit 1
  fi
done

grep -Fq 'stop-gateway' "$maintenance_workflow_file"
grep -Fq 'restart-gateway' "$maintenance_workflow_file"
grep -Fq 'status' "$maintenance_workflow_file"
grep -Fq 'DEPLOY_PATH: target.deploy_path' "$maintenance_workflow_file"
grep -Fq 'IB_GATEWAY_MODE: target.mode' "$maintenance_workflow_file"
grep -Fq 'IB_GATEWAY_CONTAINER_NAME: target.container_name' "$maintenance_workflow_file"
grep -Fq 'IB_GATEWAY_COMPOSE_SERVICE_NAME: target.compose_service_name' "$maintenance_workflow_file"
grep -Fq 'sudo systemctl disable --now' "$maintenance_workflow_file"
grep -Fq 'sudo docker update --restart=no "${container_name}"' "$maintenance_workflow_file"
grep -Fq 'sudo docker compose down' "$maintenance_workflow_file"
grep -Fq 'sudo docker compose up -d --no-build "${compose_service_name}"' "$maintenance_workflow_file"
grep -Fq 'bash ./scripts/install_gateway_health_watcher.sh __IB_GATEWAY_MODE__' "$maintenance_workflow_file"

! grep -Fxq '        shell: python3' "$diagnose_workflow_file"
grep -Fq 'redact_diagnostics()' "$diagnose_workflow_file"
grep -Fq 'sensitive_assignment_pattern.sub(r"\1<REDACTED>\2", line)' "$diagnose_workflow_file"
grep -Fq 'set -o pipefail' "$diagnose_workflow_file"
grep -Fq '| redact_diagnostics' "$diagnose_workflow_file"
grep -Fq 'section "runtime executable metadata"' "$diagnose_workflow_file"
grep -Fq 'image_os={{.Os}} image_arch={{.Architecture}}' "$diagnose_workflow_file"
grep -Fq 'run_first_bytes=' "$diagnose_workflow_file"
grep -Fq 'CONTAINER_NAME=__CONTAINER_NAME__' "$diagnose_workflow_file"
grep -Fq 'sudo docker inspect "$CONTAINER_NAME"' "$diagnose_workflow_file"
grep -Fq 'sudo docker cp "$CONTAINER_NAME":/home/ibgateway/scripts/run.sh' "$diagnose_workflow_file"
! grep -Fq 'actions/checkout' "$diagnose_workflow_file"
! grep -R -Fxq '        shell: python3' "$repo_dir/.github/workflows"

python3 - "$diagnose_workflow_file" <<'PY'
from pathlib import Path
import subprocess
import sys

workflow = Path(sys.argv[1]).read_text(encoding="utf-8")
start = "            python3 -c \"$(cat <<'PY'\n"
end = "\n          PY\n          )\"\n"
code = workflow.split(start, 1)[1].split(end, 1)[0]
code = "\n".join(line.removeprefix("          ") for line in code.splitlines())
sample = (
    "account=U12345678 host=10.20.30.40 user@example.com\n"
    "network=2001:db8::1 scoped=fe80::1%eth0 punctuation=10.20.30.40.\n"
    "paper_account=DU7654321 advisor_account=F9876543\n"
    "TOTP_SECRET=JBSWY3DPEHPK3PXP\n"
    "Authorization: Bearer header.payload.signature\n"
    'json={"access_token":"json-secret","other":1}\n'
    '"cookie": "session-secret; second=value"\n'
    "Security code: 123456\n"
)
result = subprocess.run(
    [sys.executable, "-c", code],
    input=sample,
    capture_output=True,
    check=True,
    text=True,
)
assert "account=U***5678 host=<IP> <EMAIL>" in result.stdout
assert "network=<IP> scoped=<IP> punctuation=<IP>." in result.stdout
assert "paper_account=DU***4321 advisor_account=F***6543" in result.stdout
assert "TOTP_SECRET=<REDACTED>" in result.stdout
assert "Authorization: <REDACTED>" in result.stdout
assert 'json={"access_token":<REDACTED>' in result.stdout
assert '"cookie": <REDACTED>' in result.stdout
assert "Security code: <REDACTED>" in result.stdout
assert "\n\n" not in result.stdout
for sensitive in (
    "U12345678",
    "DU7654321",
    "F9876543",
    "10.20.30.40",
    "2001:db8::1",
    "fe80::1%eth0",
    "user@example.com",
    "JBSWY3DPEHPK3PXP",
    "header.payload.signature",
    "json-secret",
    "session-secret",
    "123456",
):
    assert sensitive not in result.stdout
PY

for resolver_workflow in "$repo_dir/.github/workflows/diagnose.yml" \
  "$repo_dir/.github/workflows/capture-screen.yml" \
  "$repo_dir/.github/workflows/remote-maintenance.yml"
do
  grep -Fq 'const response = await github.rest.actions.getRepoVariable({' "$resolver_workflow"
  grep -Fq 'name: "IB_GATEWAY_TARGETS_JSON"' "$resolver_workflow"
  grep -Fq 'actions: read' "$resolver_workflow"
  ! grep -Fq 'toJSON(vars.IB_GATEWAY_TARGETS_JSON)' "$resolver_workflow"
  grep -Fq 'return digits.length >= 4 ? `U***${digits.slice(-4)}` : "<target>";' "$resolver_workflow"
  grep -Fq 'if (value) core.setSecret(String(value));' "$resolver_workflow"
  grep -Fq 'core.setOutput("matrix", JSON.stringify({include: matrixTargets}));' "$resolver_workflow"
  grep -Fq 'const target = targets[Number(${{ toJSON(matrix.target_index) }})];' "$resolver_workflow"
  grep -Fq 'target_digest: crypto.createHash("sha256").update(JSON.stringify(target)).digest("hex")' "$resolver_workflow"
  grep -Fq 'if (targetDigest !== ${{ toJSON(matrix.target_digest) }}) {' "$resolver_workflow"
  grep -Fq 'core.setFailed("Resolved gateway target changed between jobs")' "$resolver_workflow"
  grep -Fq 'core.setOutput(name.toLowerCase(), value || "");' "$resolver_workflow"
  grep -Fq 'workload_identity_provider: ${{ steps.metadata.outputs.gcp_workload_identity_provider }}' "$resolver_workflow"
  ! grep -Fq 'matrix.target.' "$resolver_workflow"
  grep -Fq 'core.setFailed("Unknown gateway target; choose one of the configured targets")' "$resolver_workflow"
  ! grep -Fq 'Unknown gateway target: ${selectedName}' "$resolver_workflow"
  ! grep -Fq 'TARGETS_JSON: ${{ vars.IB_GATEWAY_TARGETS_JSON }}' "$resolver_workflow"
  ! grep -Fq 'print("Targets: " + ", ".join(t["name"] for t in selected))' "$resolver_workflow"
done

grep -Fq 'name: Diagnose gateway target' "$repo_dir/.github/workflows/diagnose.yml"
grep -Fq 'name: Capture gateway screen' "$repo_dir/.github/workflows/capture-screen.yml"
grep -Fq 'name: Maintain gateway target' "$repo_dir/.github/workflows/remote-maintenance.yml"
