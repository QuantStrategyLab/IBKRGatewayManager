#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd "$(dirname "$0")/.." && pwd)"
workflow_file="$repo_dir/.github/workflows/read-only-vm-metadata-diagnostic.yml"

test -f "$workflow_file"
grep -Fq 'name: Read-Only Gateway VM Metadata Diagnostic' "$workflow_file"
grep -Fq 'workflow_dispatch:' "$workflow_file"
grep -Fq 'match_current_gateway:' "$workflow_file"
grep -Fq 'remaining_gateways:' "$workflow_file"
grep -Fq 'remaining_gateway_index:' "$workflow_file"
grep -Fq 'inspect_ssh_policy:' "$workflow_file"
grep -A3 -Fq 'match_current_gateway:' "$workflow_file"
grep -Fq 'default: false' "$workflow_file"
grep -A3 -Fq 'remaining_gateways:' "$workflow_file"
! grep -Fq 'schedule:' "$workflow_file"
! grep -Fq 'push:' "$workflow_file"
grep -Fq 'One gateway target from IB_GATEWAY_TARGETS_JSON' "$workflow_file"
grep -Fq 'target_index' "$workflow_file"
grep -Fq 'target_digest' "$workflow_file"
grep -Fq 'Resolved gateway target changed between jobs' "$workflow_file"
grep -Fq 'gcloud compute instances describe' "$workflow_file"
grep -Fq 'uses: actions/checkout@v6' "$workflow_file"
grep -Fq 'persist-credentials: false' "$workflow_file"
grep -Fq 'GATEWAY_VM_DIAGNOSTIC_STATUS=VM_RUNNING' "$workflow_file"
test "$(grep -Fc 'scripts/classify_gcloud_metadata_failure.py' "$workflow_file")" -eq 5
grep -Fq 'GATEWAY_VM_DIAGNOSTIC_FAILURE_CLASS=' "$repo_dir/scripts/classify_gcloud_metadata_failure.py"
grep -Fq 'GATEWAY_VM_DIAGNOSTIC_LIMIT=NO_GATEWAY_OR_CONTAINER_HEALTH_ASSERTION' "$workflow_file"
for forbidden in \
  'gcloud compute ssh' \
  'gcloud compute scp' \
  'gcloud compute instances reset' \
  'docker ' \
  'systemctl ' \
  '2fa' \
  'order' \
  'curl '
do
  if grep -Fqi "$forbidden" "$workflow_file"; then
    echo "Read-only VM metadata workflow contains forbidden operation: $forbidden" >&2
    exit 1
  fi
done

grep -Fq 'GCP_PROJECT_ID: ${{ steps.metadata.outputs.gcp_project_id }}' "$workflow_file"
grep -Fq "MATCH_TARGETS_JSON: \${{ inputs.match_current_gateway && secrets.IB_GATEWAY_TARGETS_JSON || '' }}" "$workflow_file"
grep -Fq "LEGACY_TARGETS_JSON: \${{ !inputs.match_current_gateway && vars.IB_GATEWAY_TARGETS_JSON || '' }}" "$workflow_file"
grep -Fq "IB_GATEWAY_EXPECTED_HOST: \${{ inputs.match_current_gateway && !inputs.remaining_gateways && secrets.IB_GATEWAY_EXPECTED_HOST || '' }}" "$workflow_file"
grep -Fq 'fail-fast: ${{ !inputs.remaining_gateways }}' "$workflow_file"
grep -Fq 'max-parallel: ${{ inputs.remaining_gateways && 3 || 1 }}' "$workflow_file"
grep -Fq 'Remaining gateway inspection requires protected metadata or passive-connection mode' "$workflow_file"
grep -Fq 'Resolved gateway target is not an eligible remaining target' "$workflow_file"
grep -Fq -- '--verify-target-identity' "$workflow_file"
grep -Fq 'GATEWAY_VM_DIAGNOSTIC_TARGET_INDEX=' "$workflow_file"
grep -Fq 'inputs.remaining_gateways' "$workflow_file"
grep -Fq 'scripts/match_gateway_metadata.py' "$workflow_file"
grep -Fq 'targets.map((_, target_index) => ({target_index}))' "$workflow_file"
grep -Fq 'Selected remaining gateway index requires protected passive connection inspection' "$workflow_file"
grep -Fq 'Selected gateway index is not an eligible remaining target' "$workflow_file"
grep -Fq 'Resolved gateway target does not match selected remaining index' "$workflow_file"
grep -Fq 'REMAINING_GATEWAY_INDEX: ${{ inputs.remaining_gateway_index }}' "$workflow_file"
test "$(grep -Fc 'REMAINING_GATEWAY_INDEX: ${{ inputs.remaining_gateway_index }}' "$workflow_file")" -eq 2
test "$(grep -Fc 'gcloud compute instances describe' "$workflow_file")" -eq 2
grep -Fq 'gcloud compute project-info describe' "$workflow_file"
grep -Fq 'scripts/parse_gateway_ssh_policy.py' "$workflow_file"
grep -Fq 'SSH_POLICY=blocked reason=metadata_mismatch' "$workflow_file"
grep -Fq 'SSH_POLICY=blocked reason=instance_host_unverified' "$workflow_file"
grep -Fq 'SSH_POLICY=blocked reason=project_metadata_unavailable' "$workflow_file"
grep -Fq 'SSH policy inspection cannot be combined with connection inspection' "$workflow_file"
