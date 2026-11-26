#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd "$(dirname "$0")/.." && pwd)"
workflow_file="$repo_dir/.github/workflows/main.yml"
maintenance_workflow_file="$repo_dir/.github/workflows/remote-maintenance.yml"
diagnose_workflow_file="$repo_dir/.github/workflows/diagnose.yml"

grep -Fq 'target:' "$workflow_file"
grep -Fq 'IB_GATEWAY_TARGETS_JSON' "$workflow_file"
grep -Fq 'matrix: ${{ fromJSON(needs.select-targets.outputs.matrix) }}' "$workflow_file"
! grep -Fq 'matrix.target.' "$workflow_file"
grep -Fq 'Resolve gateway target config' "$workflow_file"
grep -Fq 'gcloud secrets versions access latest --project "${GCP_SECRET_PROJECT_ID}"' "$workflow_file"
! grep -Fq 'gcloud secrets versions access latest --project "${GCP_PROJECT_ID}"' "$workflow_file"
grep -Fq 'IB_GATEWAY_TARGETS_JSON is required' "$workflow_file"
! grep -Fq 'LEGACY_' "$workflow_file"
! grep -Fq 'interactivebrokersquant' "$workflow_file"
! grep -Fq 'github-ibkr-gateway-main' "$workflow_file"
! grep -Fq 'ibkr-gateway-deploy@' "$workflow_file"

python3 - "$workflow_file" <<'PY'
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

workflow = Path(sys.argv[1]).read_text(encoding="utf-8")
start = "          python3 - <<'PY'\n"
code = workflow.split(start, 1)[1].split("          PY\n", 1)[0]
code = "\n".join(line.removeprefix("          ") for line in code.splitlines())

def select(
    targets_json: str,
    mode: str = "keepalive",
    event: str = "schedule",
    selected_target: str = "all",
    schedule_cron: str = "",
    schedule_now_utc: str = "",
) -> tuple[subprocess.CompletedProcess[str], dict[str, str], str]:
    with tempfile.TemporaryDirectory() as temp_dir:
        output = Path(temp_dir) / "output"
        summary = Path(temp_dir) / "summary"
        env = os.environ | {
            "TARGETS_JSON": targets_json,
            "SELECTED_TARGET": selected_target,
            "SELECTED_DEPLOY_MODE": mode,
            "GITHUB_EVENT_NAME": event,
            "EVENT_SCHEDULE_CRON": schedule_cron,
            "SCHEDULE_NOW_UTC": schedule_now_utc,
            "GITHUB_OUTPUT": str(output),
            "GITHUB_STEP_SUMMARY": str(summary),
        }
        result = subprocess.run([sys.executable, "-c", code], env=env, text=True, capture_output=True)
        outputs = (
            dict(line.split("=", 1) for line in output.read_text().splitlines())
            if output.exists()
            else {}
        )
        summary_text = summary.read_text() if summary.exists() else ""
        return result, outputs, summary_text

missing, _, _ = select("")
assert missing.returncode != 0
assert "IB_GATEWAY_TARGETS_JSON is required" in missing.stderr

multiline, _, _ = select('{\n  "gateway-a": {}\n}')
assert multiline.returncode != 0
assert "IB_GATEWAY_TARGETS_JSON must be stored as single-line JSON" in multiline.stderr

configured, outputs, summary = select('{"gateway-a": {}}')
assert configured.returncode == 0, configured.stderr
assert [item["target_index"] for item in json.loads(outputs["matrix"])["include"]] == [0]
assert outputs["has_targets"] == "true"
assert "Selected: gateway-a" in summary

list_secret = '[{"name":"gateway-a","gcp_project_id":"mock-project"}]'
list_configured, list_outputs, _ = select(list_secret, event="workflow_dispatch")
assert list_configured.returncode == 0, list_configured.stderr
assert "mock-project" not in list_outputs["matrix"]
assert "gateway-a" not in list_outputs["matrix"]

targets = '{"active": {}, "parked": {"maintenance_enabled": false}}'
scheduled, outputs, summary = select(targets)
assert scheduled.returncode == 0, scheduled.stderr
assert [item["target_index"] for item in json.loads(outputs["matrix"])["include"]] == [0]
assert outputs["has_targets"] == "true"
assert "Skipped parked: maintenance_enabled=false; runtime state not verified." in summary

all_parked, outputs, summary = select('{"parked": {"maintenance_enabled": false}}')
assert all_parked.returncode == 0, all_parked.stderr
assert json.loads(outputs["matrix"])["include"] == []
assert outputs["has_targets"] == "false"
assert "Selected: none" in summary

manual, outputs, summary = select(targets, event="workflow_dispatch", selected_target="parked")
assert manual.returncode == 0, manual.stderr
assert [item["target_index"] for item in json.loads(outputs["matrix"])["include"]] == [1]
assert "Skipped parked" not in summary

manual_all, outputs, _ = select(targets, event="workflow_dispatch")
assert manual_all.returncode == 0, manual_all.stderr
assert [item["target_index"] for item in json.loads(outputs["matrix"])["include"]] == [0, 1]

invalid, _, _ = select('{"gateway-a": {"maintenance_enabled": "false"}}')
assert invalid.returncode != 0
assert "must be a boolean" in invalid.stderr

restore_all, _, _ = select('{"gateway-a": {}}', "restore-env", event="workflow_dispatch")
assert restore_all.returncode != 0
assert "one explicit target" in restore_all.stderr

# Winter EST: 00:15 UTC = 19:15 EST (outside 20:00-20:55 ET pause -> skipped); 01:15 UTC = 20:15 EST (selected)
win_targets = '{"us-gw": {}, "fut-gw": {"maintenance_window": "weekend_only"}}'
est_early, outputs, summary = select(win_targets, schedule_cron="15 0 * * 2-6", schedule_now_utc="2026-12-08T00:15:00Z")
assert est_early.returncode == 0, est_early.stderr
assert json.loads(outputs["matrix"])["include"] == []
assert outputs["has_targets"] == "false"
assert "Skipped us-gw: outside us_23x5_daily_pause window; runtime state untouched." in summary

est_pause, outputs, _ = select(win_targets, schedule_cron="15 1 * * 2-6", schedule_now_utc="2026-12-08T01:15:00Z")
assert est_pause.returncode == 0, est_pause.stderr
assert [t["target_index"] for t in json.loads(outputs["matrix"])["include"]] == [0]

# Summer EDT: 00:15 UTC = 20:15 EDT (selected); 01:15 UTC = 21:15 EDT (outside pause -> skipped)
edt_pause, outputs, _ = select(win_targets, schedule_cron="15 0 * * 2-6", schedule_now_utc="2026-07-08T00:15:00Z")
assert edt_pause.returncode == 0, edt_pause.stderr
assert [t["target_index"] for t in json.loads(outputs["matrix"])["include"]] == [0]

edt_late, outputs, _ = select(win_targets, schedule_cron="15 1 * * 2-6", schedule_now_utc="2026-07-08T01:15:00Z")
assert edt_late.returncode == 0, edt_late.stderr
assert json.loads(outputs["matrix"])["include"] == []

# Saturday 14:15 UTC = 09:15 EST -> weekend_only selected, us_23x5_daily_pause skipped
sat_maint, outputs, _ = select(win_targets, schedule_cron="15 14 * * 6", schedule_now_utc="2026-12-12T14:15:00Z")
assert sat_maint.returncode == 0, sat_maint.stderr
assert [t["target_index"] for t in json.loads(outputs["matrix"])["include"]] == [1]

# Verify deploy Resolve gateway target config writes GITHUB_ENV and rejects digest mismatch
resolve_step = workflow.split("      - name: Resolve gateway target config\n", 1)[1].split("          PY\n", 1)[0]
resolve_code = "\n".join(line.removeprefix("          ") for line in resolve_step.split(start, 1)[1].splitlines())
entry = json.loads(list_outputs["matrix"])["include"][0]
with tempfile.TemporaryDirectory() as temp_dir:
    env_out = Path(temp_dir) / "env_out"
    res_ok = subprocess.run(
        [sys.executable, "-c", resolve_code],
        env=os.environ | {
            "TARGETS_JSON": list_secret,
            "TARGET_INDEX": str(entry["target_index"]),
            "TARGET_DIGEST": entry["target_digest"],
            "GITHUB_ENV": str(env_out),
        },
        text=True,
        capture_output=True,
    )
    assert res_ok.returncode == 0, res_ok.stderr
    env_map = dict(line.split("=", 1) for line in env_out.read_text().splitlines())
    assert env_map["TARGET_NAME"] == "gateway-a"
    assert env_map["GCP_PROJECT_ID"] == "mock-project"
    assert env_map["GCP_SECRET_PROJECT_ID"] == "mock-project"
    assert "::add-mask::mock-project" in res_ok.stdout

    res_bad = subprocess.run(
        [sys.executable, "-c", resolve_code],
        env=os.environ | {
            "TARGETS_JSON": list_secret,
            "TARGET_INDEX": str(entry["target_index"]),
            "TARGET_DIGEST": "0" * 64,
            "GITHUB_ENV": str(env_out),
        },
        text=True,
        capture_output=True,
    )
    assert res_bad.returncode != 0
    assert "Resolved gateway target changed between jobs" in res_bad.stderr
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
grep -Fq 'copy_remote_file "${ENV_FILE}" "${REMOTE_ENV}"' "$workflow_file"
grep -Fq "install -m 600 '\${REMOTE_ENV}' '\${DEPLOY_PATH}/.env'" "$workflow_file"
grep -Fq 'A full or restore-env gateway operation requires one explicit target' "$workflow_file"
grep -Fq '          - restore-env' "$workflow_file"
grep -Fq 'Restore missing gateway runtime environment' "$workflow_file"
grep -Fq 'RUNTIME_ENV_ALREADY_EXISTS' "$workflow_file"
grep -Fq 'CONTAINER_IDENTITY_OR_SECURITY_MISMATCH' "$workflow_file"
grep -Fq 'docker compose --project-name "\${project}" --env-file "\${candidate}" config --format json' "$workflow_file"
grep -Fq 'os.link(staged, destination)' "$workflow_file"
grep -Fq 'os.fchmod(fd, 0o600)' "$workflow_file"
grep -Fq 'restore-env requires target-specific Secret Manager names' "$workflow_file"
grep -Fq 'require_secret_source TOTP_SECRET_SECRET_NAME TOTP_SECRET' "$workflow_file"
grep -Fq "inputs.deploy_mode != 'restore-env'" "$workflow_file"
python3 "$repo_dir/tests/test_restore_env_workflow_mock.py"
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
grep -Fq 'if [ -n "${VNC_SERVER_PASSWORD_SECRET_NAME:-}" ]; then' "$workflow_file"
! grep -Fq 'require_secret_source VNC_SERVER_PASSWORD_SECRET_NAME' "$workflow_file"
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
    "account=U00000001 host=10.20.30.40 user@example.com\n"
    "network=2001:db8::1 scoped=fe80::1%eth0 punctuation=10.20.30.40.\n"
    "paper_account=DU0000001 advisor_account=F0000001\n"
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
assert "account=U***0001 host=<IP> <EMAIL>" in result.stdout
assert "network=<IP> scoped=<IP> punctuation=<IP>." in result.stdout
assert "paper_account=DU***0001 advisor_account=F***0001" in result.stdout
assert "TOTP_SECRET=<REDACTED>" in result.stdout
assert "Authorization: <REDACTED>" in result.stdout
assert 'json={"access_token":<REDACTED>' in result.stdout
assert '"cookie": <REDACTED>' in result.stdout
assert "Security code: <REDACTED>" in result.stdout
assert "\n\n" not in result.stdout
for sensitive in (
    "U00000001",
    "DU0000001",
    "F0000001",
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
  grep -Fq 'const raw = ${{ toJSON(secrets.IB_GATEWAY_TARGETS_JSON) }};' "$resolver_workflow"
  grep -Fq 'return digits.length >= 4 ? `U***${digits.slice(-4)}` : "<target>";' "$resolver_workflow"
  grep -Fq 'if (value) core.setSecret(String(value));' "$resolver_workflow"
  grep -Fq 'core.setOutput("matrix", JSON.stringify({include: matrixTargets}));' "$resolver_workflow"
  grep -Fq 'const target = targets[Number(${{ toJSON(matrix.target_index) }})];' "$resolver_workflow"
  grep -Fq 'target_digest: crypto.createHash("sha256").update(JSON.stringify(target)).digest("hex")' "$resolver_workflow"
  grep -Fq 'if (targetDigest !== ${{ toJSON(matrix.target_digest) }}) {' "$resolver_workflow"
  grep -Fq 'core.setFailed("IB_GATEWAY_TARGETS_JSON must be stored as single-line JSON");' "$resolver_workflow"
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

sensitive = "TOTP_SECRET=do-not-print account=U00000001"
recovery = classify(f"{sensitive}\nGATEWAY_RECOVERY_FAILURE_STAGE=GATEWAY_UI_BLOCKER\n")
assert recovery.stdout.strip() == "GATEWAY_RECOVERY_FAILURE_STAGE=GATEWAY_UI_BLOCKER"
assert sensitive not in recovery.stdout

remote = classify(f"{sensitive}\nGATEWAY_REMOTE_FAILURE_STAGE=ENSURE_HOST_SWAP\n")
assert remote.stdout.strip() == "GATEWAY_REMOTE_FAILURE_STAGE=ENSURE_HOST_SWAP"
assert sensitive not in remote.stdout

unknown = classify(f"{sensitive}\nGATEWAY_REMOTE_FAILURE_STAGE=UNTRUSTED_STAGE\n")
assert unknown.stdout.strip().endswith("GATEWAY_DEPLOY_FAILURE_STAGE=REMOTE_COMMAND_FAILED")
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

python3 - "$workflow_file" <<'PY'
import os
import subprocess
from pathlib import Path
import sys

workflow = Path(sys.argv[1]).read_text(encoding="utf-8")
deploy_step = workflow.split("      - name: Deploy and Log Setup\n", 1)[1].split("          log_step()", 1)[0]
guard_lines = [line.removeprefix("          ") for line in deploy_step.splitlines() if line.startswith("          ") or line == ""]
guard_script = "\n".join(guard_lines) + "\necho CONTINUED_PAST_GUARD\n"

def run_guard(**extra_env: str) -> subprocess.CompletedProcess[str]:
    env = os.environ | {
        "TARGET_NAME": "us-gw",
        "MAINTENANCE_WINDOW": "us_23x5_daily_pause",
        "DEPLOY_EVENT_NAME": "schedule",
        "EVENT_SCHEDULE_CRON": "15 1 * * 2-6",
        "SCHEDULE_NOW_UTC": "2026-12-08T01:20:00Z",
    } | extra_env
    return subprocess.run(["bash", "-c", guard_script], env=env, capture_output=True, text=True)

expired = run_guard(SCHEDULE_NOW_UTC="2026-12-08T01:56:00Z")
assert expired.returncode == 0, expired.stderr
assert "window expired before remote maintenance" in expired.stdout
assert "CONTINUED_PAST_GUARD" not in expired.stdout

active = run_guard(SCHEDULE_NOW_UTC="2026-12-08T01:20:00Z")
assert active.returncode == 0, active.stderr
assert "CONTINUED_PAST_GUARD" in active.stdout

assert "IB_GATEWAY_MAINTENANCE_DEADLINE_EPOCH" in workflow
assert "recovery_rc -eq 10" in workflow or 'recovery_rc}" -eq 10' in workflow

deadline_probe = deploy_step.split("          log_step()", 1)[0]
deadline_script = "\n".join(
    line.removeprefix("          ") for line in deadline_probe.splitlines() if line.startswith("          ") or line == ""
) + '\necho "DEADLINE=${MAINTENANCE_DEADLINE_EPOCH}"\n'
deadline_res = subprocess.run(
    ["bash", "-c", deadline_script],
    env=os.environ | {
        "TARGET_NAME": "us-gw",
        "MAINTENANCE_WINDOW": "us_23x5_daily_pause",
        "DEPLOY_EVENT_NAME": "schedule",
        "EVENT_SCHEDULE_CRON": "15 1 * * 2-6",
        "SCHEDULE_NOW_UTC": "2026-12-08T01:45:00Z",
    },
    capture_output=True,
    text=True,
)
assert deadline_res.returncode == 0, deadline_res.stderr
assert "DEADLINE=1796694900" in deadline_res.stdout  # 2026-12-07 20:55 EST == 2026-12-08T01:55:00Z

invalid = run_guard(MAINTENANCE_WINDOW="bogus")
assert invalid.returncode != 0
assert "Unsupported maintenance_window" in invalid.stderr
PY
