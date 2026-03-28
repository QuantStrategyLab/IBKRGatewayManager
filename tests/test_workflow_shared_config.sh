#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd "$(dirname "$0")/.." && pwd)"
workflow_file="$repo_dir/.github/workflows/main.yml"

grep -Fq "vars.IB_GATEWAY_INSTANCE_NAME" "$workflow_file"
grep -Fq "vars.IB_GATEWAY_ZONE" "$workflow_file"
grep -Fq "vars.IB_GATEWAY_MODE" "$workflow_file"
grep -Fq "vars.CLOUD_RUN_EGRESS_CIDR" "$workflow_file"
grep -Fq '"TRADING_MODE": os.environ["IB_GATEWAY_MODE"]' "$workflow_file"
grep -Fq '"ACCEPT_API_FROM_IP": os.environ["CLOUD_RUN_EGRESS_CIDR"]' "$workflow_file"
