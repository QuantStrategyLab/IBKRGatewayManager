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
grep -Fq 'IB_GATEWAY_TARGETS_JSON is required' "$workflow_file"
! grep -Fq 'LEGACY_' "$workflow_file"
! grep -Fq 'interactivebrokersquant' "$workflow_file"
! grep -Fq 'github-ibkr-gateway-main' "$workflow_file"
! grep -Fq 'ibkr-gateway-deploy@' "$workflow_file"

python3 - "$workflow_file" <<'PY'
from pathlib import Path
import os
import subprocess
import sys
import tempfile

workflow = Path(sys.argv[1]).read_text(encoding="utf-8")
start = "          python3 - <<'PY'\n"
code = workflow.split(start, 1)[1].split("          PY\n", 1)[0]
code = "\n".join(line.removeprefix("          ") for line in code.splitlines())

def select(targets_json: str) -> subprocess.CompletedProcess[str]:
    with tempfile.NamedTemporaryFile() as output:
        env = os.environ | {
            "TARGETS_JSON": targets_json,
            "SELECTED_TARGET": "all",
            "SELECTED_DEPLOY_MODE": "keepalive",
            "GITHUB_OUTPUT": output.name,
        }
        return subprocess.run([sys.executable, "-c", code], env=env, text=True, capture_output=True)

missing = select("")
assert missing.returncode != 0
assert "IB_GATEWAY_TARGETS_JSON is required" in missing.stderr

configured = select('{"gateway-a": {}}')
assert configured.returncode == 0, configured.stderr
PY
grep -Fq 'id-token: write' "$workflow_file"
grep -Fq 'timeout-minutes: 75' "$workflow_file"
grep -Fq 'sync_github_secrets_to_secret_manager:' "$workflow_file"
grep -Fq 'deploy_mode:' "$workflow_file"
grep -Fq 'workload_identity_provider: ${{ env.GCP_WORKLOAD_IDENTITY_PROVIDER }}' "$workflow_file"
grep -Fq 'service_account: ${{ env.GCP_WORKLOAD_IDENTITY_SERVICE_ACCOUNT }}' "$workflow_file"
grep -Fq "DEPLOY_EVENT_NAME: \${{ github.event_name }}" "$workflow_file"
grep -Fq "WORKFLOW_DISPATCH_MODE: \${{ github.event.inputs.deploy_mode }}" "$workflow_file"
grep -Fq "WORKFLOW_DISPATCH_ALLOW_VM_RESET: \${{ github.event.inputs.allow_vm_reset }}" "$workflow_file"
grep -Fq "WORKFLOW_DISPATCH_REBUILD_WITHOUT_CACHE: \${{ github.event.inputs.rebuild_without_cache }}" "$workflow_file"
grep -Fq 'gcloud secrets versions access latest' "$workflow_file"
grep -Fq -- '--scp-flag="-o ServerAliveInterval=30"' "$workflow_file"
grep -Fq 'resolve_secret()' "$workflow_file"
grep -Fq 'require_secret_source()' "$workflow_file"
grep -Fq 'Sync GitHub secrets to Secret Manager' "$workflow_file"
grep -Fq 'gcloud secrets versions add "${secret_name}"' "$workflow_file"
! grep -Fq '  push:' "$workflow_file"
grep -Fq 'DEPLOY_MODE="keepalive"' "$workflow_file"
grep -Fq 'if [ "${DEPLOY_EVENT_NAME}" = "workflow_dispatch" ]; then' "$workflow_file"
grep -Fq 'DEPLOY_MODE="${WORKFLOW_DISPATCH_MODE:-keepalive}"' "$workflow_file"
grep -Fq 'Scheduled keepalive mode: skip docker build' "$workflow_file"
grep -Fq 'reset_instance_and_wait_for_ssh()' "$workflow_file"
grep -Fq 'Manual workflow VM reset is disabled; failing closed.' "$workflow_file"
grep -Fq 'sudo docker compose build --no-cache "\${compose_service_name}"' "$workflow_file"
grep -Fq 'if [ "${WORKFLOW_DISPATCH_REBUILD_WITHOUT_CACHE:-false}" = '\''true'\'' ]; then' "$workflow_file"
grep -Fq 'run_remote_ssh()' "$workflow_file"
grep -Fq 'copy_remote_file()' "$workflow_file"
grep -Fq 'git archive --format=tar.gz' "$workflow_file"
grep -Fq 'tar -xzf' "$workflow_file"
grep -Fq 'gcloud compute instances reset "${GCE_INSTANCE_NAME}"' "$workflow_file"
grep -Fq 'run_remote_ssh "Repository sync" "${REMOTE_SYNC_COMMAND}"' "$workflow_file"
grep -Fq 'copy_remote_file "${ENV_FILE}" "${DEPLOY_PATH}/.env"' "$workflow_file"
grep -Fq 'A full gateway deployment requires one explicit target' "$workflow_file"
grep -Fq 'Runtime keepalive uses the already released source and environment' "$workflow_file"
grep -Fq 'sudo bash ./scripts/ensure_host_swap.sh' "$workflow_file"
grep -Fq 'host_2fa_bot_sha256="\$(sha256sum ./2fa_bot.py' "$workflow_file"
grep -Fq 'container_2fa_bot_sha256="\$(sudo timeout 15 docker exec' "$workflow_file"
grep -Fq 'Refreshing stale 2FA bot bind mount for \${container_name}' "$workflow_file"
grep -Fq 'sudo docker compose up -d --force-recreate --no-build "\${compose_service_name}"' "$workflow_file"
grep -Fq 'resolve_ibkr_gateway_unit_names "\${container_name}" "\${IB_GATEWAY_UNIT_SUFFIX:-}"' "$workflow_file"
grep -Fq 'sudo systemctl stop "\${IBKR_GATEWAY_HEALTHCHECK_TIMER}" "\${IBKR_GATEWAY_HEALTHCHECK_SERVICE}" 2>/dev/null || true' "$workflow_file"
grep -Fq 'bash ./scripts/install_gateway_health_watcher.sh' "$workflow_file"
grep -Fq 'restore_gateway_watchers()' "$workflow_file"
grep -Fq 'arm_gateway_watchers_failsafe()' "$workflow_file"
grep -Fq 'cancel_gateway_watchers_failsafe()' "$workflow_file"
grep -Fq 'watcher_failsafe_seconds="\${IB_GATEWAY_WATCHER_FAILSAFE_SECONDS:-3900}"' "$workflow_file"
grep -Fq 'sudo systemd-run --unit="\${watcher_failsafe_name}" --on-active="\${watcher_failsafe_seconds}s" --collect' "$workflow_file"
grep -Fq 'systemctl enable --now '\''\${IBKR_GATEWAY_HEALTHCHECK_TIMER}'\'' '\''\${IBKR_GATEWAY_DAILY_RESTART_TIMER}'\''' "$workflow_file"
grep -Fq 'sudo systemctl stop "\${watcher_failsafe_name}.timer" "\${watcher_failsafe_name}.service"' "$workflow_file"
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
test "$(grep -cFx '          arm_gateway_watchers_failsafe' "$workflow_file")" -eq 2
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
grep -Fq 'sudo docker compose up -d --force-recreate --no-build "${compose_service_name}"' "$maintenance_workflow_file"
grep -Fq 'bash ./scripts/install_gateway_health_watcher.sh __IB_GATEWAY_MODE__' "$maintenance_workflow_file"

! grep -Fxq '        shell: python3' "$diagnose_workflow_file"
grep -Fq 'redact_diagnostics()' "$diagnose_workflow_file"
grep -Fq 'sensitive_assignment_pattern.sub(r"\1<REDACTED>\2", line)' "$diagnose_workflow_file"
grep -Fq 'set -o pipefail' "$diagnose_workflow_file"
grep -Fq '| redact_diagnostics' "$diagnose_workflow_file"
grep -Fq 'section "runtime executable metadata"' "$diagnose_workflow_file"
grep -Fq 'image_os={{.Os}} image_arch={{.Architecture}}' "$diagnose_workflow_file"
grep -Fq 'run_first_bytes=' "$diagnose_workflow_file"
grep -Fq 'source_run_size=%s' "$diagnose_workflow_file"
grep -Fq 'source_run_sha256=' "$diagnose_workflow_file"
grep -Fq 'CONTAINER_NAME=__CONTAINER_NAME__' "$diagnose_workflow_file"
grep -Fq 'UNIT_SUFFIX=__IB_GATEWAY_UNIT_SUFFIX__' "$diagnose_workflow_file"
grep -Fq 'section "structured runtime receipt"' "$diagnose_workflow_file"
grep -Fq 'resolve_ibkr_gateway_unit_names "$CONTAINER_NAME" "$UNIT_SUFFIX"' "$diagnose_workflow_file"
grep -Fq 'GATEWAY_RUNTIME_RECEIPT=READY' "$diagnose_workflow_file"
grep -Fq 'GATEWAY_RUNTIME_RECEIPT=DEGRADED' "$diagnose_workflow_file"
grep -Fq 'GATEWAY_RUNTIME_RECEIPT=UNKNOWN' "$diagnose_workflow_file"
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
  grep -Fq 'const raw = ${{ toJSON(vars.IB_GATEWAY_TARGETS_JSON) }};' "$resolver_workflow"
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

python3 - "$workflow_file" <<'PY'
from pathlib import Path
import subprocess
import sys
import tempfile

workflow = Path(sys.argv[1]).read_text(encoding="utf-8")
assert 'emit_sanitized_remote_failure_stage()' in workflow
assert "GATEWAY_DEPLOY_FAILURE_STAGE=REMOTE_COMMAND_OR_TRANSPORT_FAILED" in workflow
assert "GATEWAY_RECOVERY_FAILURE_STAGE=GATEWAY_NOT_READY_AFTER_RECREATE" in workflow
assert 'GATEWAY_REMOTE_FAILURE_STAGE=LOAD_RUNTIME_ENV' in workflow
assert 'GATEWAY_REMOTE_FAILURE_STAGE=ARM_WATCHER_FAILSAFE' in workflow
assert 'GATEWAY_REMOTE_FAILURE_STAGE=STOP_WATCHERS' in workflow
assert 'GATEWAY_REMOTE_FAILURE_STAGE=ENSURE_HOST_SWAP' in workflow
assert 'GATEWAY_REMOTE_FAILURE_STAGE=CHECK_RUNTIME_IMAGE' in workflow
assert 'GATEWAY_REMOTE_FAILURE_STAGE=CHECK_2FA_BIND_MOUNT' in workflow
assert 'GATEWAY_REMOTE_FAILURE_STAGE=REFRESH_2FA_BIND_MOUNT' in workflow
assert 'GATEWAY_REMOTE_FAILURE_STAGE=RECOVER_GATEWAY' in workflow
assert 'GATEWAY_REMOTE_FAILURE_STAGE=RESTORE_WATCHERS' in workflow
assert 'GATEWAY_REMOTE_FAILURE_STAGE=REPORT_RUNTIME_STATUS' in workflow
assert 'gcloud compute ssh "${REMOTE_TARGET}" "${SSH_FLAGS[@]}" --command "${REMOTE_DEPLOY_COMMAND}" >"${command_log}" 2>&1' in workflow
assert 'run_sanitized_remote_deploy' in workflow

function_start = "          emit_sanitized_remote_failure_stage() {\n"
function_end = "\n          }\n\n          run_sanitized_remote_deploy()"
classifier = workflow.split(function_start, 1)[1].split(function_end, 1)[0]
classifier = "emit_sanitized_remote_failure_stage() {\n" + "\n".join(
    line.removeprefix("          ") for line in classifier.splitlines()
) + "\n}"

def classify(log_text: str) -> subprocess.CompletedProcess[str]:
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8") as command_log:
        command_log.write(log_text)
        command_log.flush()
        script = "log_step() { printf '%s\\n' \"$1\"; }\n" + classifier + '\nemit_sanitized_remote_failure_stage "$1"\n'
        return subprocess.run(
            ["bash", "-c", script, "classifier", command_log.name],
            capture_output=True,
            check=True,
            text=True,
        )

sensitive = "TOTP_SECRET=do-not-print account=U12345678"
recovery = classify(f"{sensitive}\nGATEWAY_RECOVERY_FAILURE_STAGE=GATEWAY_UI_BLOCKER\n")
assert recovery.stdout.strip() == "GATEWAY_RECOVERY_FAILURE_STAGE=GATEWAY_UI_BLOCKER"
assert sensitive not in recovery.stdout

remote = classify(f"{sensitive}\nGATEWAY_REMOTE_FAILURE_STAGE=ENSURE_HOST_SWAP\n")
assert remote.stdout.strip() == "GATEWAY_REMOTE_FAILURE_STAGE=ENSURE_HOST_SWAP"
assert sensitive not in remote.stdout

unknown = classify(f"{sensitive}\nGATEWAY_REMOTE_FAILURE_STAGE=UNTRUSTED_STAGE\n")
assert unknown.stdout.strip().endswith("GATEWAY_DEPLOY_FAILURE_STAGE=REMOTE_COMMAND_OR_TRANSPORT_FAILED")
assert sensitive not in unknown.stdout

transport = classify(f"{sensitive}\nssh: connect to host failed\n")
assert transport.stdout.strip().endswith("GATEWAY_DEPLOY_FAILURE_STAGE=REMOTE_COMMAND_OR_TRANSPORT_FAILED")
assert sensitive not in transport.stdout

keepalive_start = '          if [ "${DEPLOY_MODE}" = "keepalive" ]; then\n'
remote_start = "            REMOTE_DEPLOY_COMMAND=$(cat <<EOF\n"
remote_end = "          cd '${DEPLOY_PATH}'\n"
keepalive = workflow.split(keepalive_start, 1)[1]
remote_prelude = keepalive.split(remote_start, 1)[1].split(remote_end, 1)[0]
remote_prelude = "\n".join(
    line.removeprefix("          ").replace(r"\${", "${").replace(r"\$?", "$?")
    for line in remote_prelude.splitlines()
)

keepalive_remote = keepalive.split(remote_start, 1)[1].split("          EOF\n", 1)[0]
trap_lines = [
    line.removeprefix("          ").replace(r"\${", "${").replace(r"\$?", "$?")
    for line in keepalive_remote.splitlines()
    if line.removeprefix("          ").startswith("trap 'status=")
]
assert len(trap_lines) == 2

with tempfile.NamedTemporaryFile(mode="r+", encoding="utf-8") as restore_log:
    arm_failure = subprocess.run(
        [
            "bash",
            "-c",
            remote_prelude
            + '\nrestore_log_path="$1"\nrestore_gateway_watchers() { printf restore >>"$restore_log_path"; }\n'
            + 'remote_failure_stage="ARM_WATCHER_FAILSAFE"\nexit 19\n',
            "arm-failure",
            restore_log.name,
        ],
        capture_output=True,
        text=True,
    )
    restore_log.seek(0)
    assert arm_failure.returncode == 19
    assert restore_log.read() == ""
    assert arm_failure.stderr.strip() == "GATEWAY_REMOTE_FAILURE_STAGE=ARM_WATCHER_FAILSAFE"

with tempfile.NamedTemporaryFile(mode="r+", encoding="utf-8") as restore_log:
    post_arm_failure = subprocess.run(
        [
            "bash",
            "-c",
            "set -euo pipefail\n"
            + 'remote_failure_stage="ENSURE_HOST_SWAP"\n'
            + 'watchers_restored=false\n'
            + 'restore_log_path="$1"\n'
            + 'emit_remote_failure_stage() { printf "GATEWAY_REMOTE_FAILURE_STAGE=%s\\n" "$remote_failure_stage" >&2; }\n'
            + 'restore_gateway_watchers() { printf restore >>"$restore_log_path"; }\n'
            + trap_lines[1]
            + "\nexit 23\n",
            "post-arm-failure",
            restore_log.name,
        ],
        capture_output=True,
        text=True,
    )
    restore_log.seek(0)
    assert post_arm_failure.returncode == 23
    assert restore_log.read() == "restore"
    assert post_arm_failure.stderr.strip() == "GATEWAY_REMOTE_FAILURE_STAGE=ENSURE_HOST_SWAP"

failed_pipe = subprocess.run(
    ["bash", "-c", remote_prelude + '\nremote_failure_stage="CHECK_RUNTIME_IMAGE"\nprintf x | false\n'],
    capture_output=True,
    text=True,
)
assert failed_pipe.returncode != 0
assert failed_pipe.stderr.strip() == "GATEWAY_REMOTE_FAILURE_STAGE=CHECK_RUNTIME_IMAGE"

successful_remote = subprocess.run(
    ["bash", "-c", remote_prelude + "\ntrue\n"],
    capture_output=True,
    text=True,
)
assert successful_remote.returncode == 0
assert "GATEWAY_REMOTE_FAILURE_STAGE" not in successful_remote.stderr
PY
