#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd "$(dirname "$0")/.." && pwd)"
workflow_file="$repo_dir/.github/workflows/main.yml"

grep -Fq 'GCP_PROJECT_ID: interactivebrokersquant' "$workflow_file"
grep -Fq 'providers/github-ibkr-gateway-main' "$workflow_file"
grep -Fq 'ibkr-gateway-deploy@interactivebrokersquant.iam.gserviceaccount.com' "$workflow_file"
grep -Fq 'id-token: write' "$workflow_file"
grep -Fq 'timeout-minutes: 35' "$workflow_file"
grep -Fq 'sync_github_secrets_to_secret_manager:' "$workflow_file"
grep -Fq 'deploy_mode:' "$workflow_file"
grep -Fq 'workload_identity_provider: ${{ env.GCP_WORKLOAD_IDENTITY_PROVIDER }}' "$workflow_file"
grep -Fq 'service_account: ${{ env.GCP_WORKLOAD_IDENTITY_SERVICE_ACCOUNT }}' "$workflow_file"
grep -Fq "DEPLOY_EVENT_NAME: \${{ github.event_name }}" "$workflow_file"
grep -Fq "WORKFLOW_DISPATCH_MODE: \${{ github.event.inputs.deploy_mode }}" "$workflow_file"
grep -Fq 'vars.IB_GATEWAY_INSTANCE_NAME' "$workflow_file"
grep -Fq 'vars.IB_GATEWAY_ZONE' "$workflow_file"
grep -Fq 'vars.IB_GATEWAY_MODE' "$workflow_file"
grep -Fq 'vars.IB_GATEWAY_GCE_USER' "$workflow_file"
grep -Fq 'vars.IB_GATEWAY_DEPLOY_PATH' "$workflow_file"
grep -Fq 'vars.IB_GATEWAY_CLOUD_RUN_EGRESS_CIDR' "$workflow_file"
grep -Fq 'vars.IB_GATEWAY_ALLOW_CONNECTIONS_FROM_LOCALHOST_ONLY' "$workflow_file"
grep -Fq 'vars.IB_GATEWAY_TWS_ACCEPT_INCOMING' "$workflow_file"
grep -Fq 'vars.IB_GATEWAY_READ_ONLY_API' "$workflow_file"
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
grep -Fq "'.github/workflows/main.yml'" "$workflow_file"
grep -Fq 'DEPLOY_MODE="full"' "$workflow_file"
grep -Fq 'if [ "${DEPLOY_EVENT_NAME}" = "schedule" ]; then' "$workflow_file"
grep -Fq 'elif [ "${DEPLOY_EVENT_NAME}" = "workflow_dispatch" ]; then' "$workflow_file"
grep -Fq 'DEPLOY_MODE="${WORKFLOW_DISPATCH_MODE:-keepalive}"' "$workflow_file"
grep -Fq 'Scheduled keepalive mode: skip docker build' "$workflow_file"
grep -Fq 'reset_instance_and_wait_for_ssh()' "$workflow_file"
grep -Fq 'run_remote_ssh()' "$workflow_file"
grep -Fq 'copy_remote_file()' "$workflow_file"
grep -Fq 'gcloud compute instances reset "${GCE_INSTANCE_NAME}"' "$workflow_file"
grep -Fq 'run_remote_ssh "Repository sync" "${REMOTE_SYNC_COMMAND}"' "$workflow_file"
grep -Fq 'copy_remote_file "${ENV_FILE}" "${DEPLOY_PATH}/.env"' "$workflow_file"
grep -Fq 'sudo bash ./scripts/ensure_host_swap.sh' "$workflow_file"
grep -Fq 'sudo systemctl stop ibkr-gateway-healthcheck.timer ibkr-gateway-healthcheck.service 2>/dev/null || true' "$workflow_file"
grep -Fq 'sudo bash ./scripts/install_gateway_health_watcher.sh' "$workflow_file"
grep -Fq "sudo bash ./scripts/recover_ib_gateway_ready.sh '\${IB_GATEWAY_MODE}'" "$workflow_file"
grep -Fq 'sudo systemctl status ibkr-gateway-healthcheck.timer --no-pager' "$workflow_file"
grep -Fq 'sudo systemctl status ibkr-gateway-daily-restart.timer --no-pager' "$workflow_file"
grep -Fq 'Full deploy mode: rebuilding container' "$workflow_file"

mapfile -t recover_lines < <(grep -nF "sudo bash ./scripts/recover_ib_gateway_ready.sh '\${IB_GATEWAY_MODE}'" "$workflow_file" | cut -d: -f1)
mapfile -t health_watcher_lines < <(grep -nF 'sudo bash ./scripts/install_gateway_health_watcher.sh' "$workflow_file" | cut -d: -f1)
test "${#recover_lines[@]}" -eq 2
test "${#health_watcher_lines[@]}" -eq 2
for i in 0 1; do
  if [ "${recover_lines[$i]}" -ge "${health_watcher_lines[$i]}" ]; then
    echo "Gateway health watcher must be installed after explicit recovery in deploy block $i" >&2
    exit 1
  fi
done

grep -Fq '"TRADING_MODE": os.environ["IB_GATEWAY_MODE"]' "$workflow_file"
grep -Fq '"ACCEPT_API_FROM_IP": os.environ["CLOUD_RUN_EGRESS_CIDR"]' "$workflow_file"
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
