#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd "$(dirname "$0")/.." && pwd)"
recover_script="$repo_dir/scripts/recover_ib_gateway_ready.sh"
swap_script="$repo_dir/scripts/ensure_host_swap.sh"

test -f "$recover_script"
test -f "$swap_script"
test -x "$recover_script"
test -x "$swap_script"

grep -Fq 'IB_GATEWAY_RECOVERY_INITIAL_WAIT_SECONDS:-60' "$recover_script"
grep -Fq 'docker compose restart "${container_name}"' "$recover_script"
grep -Fq 'docker compose up -d --force-recreate --no-build "${container_name}"' "$recover_script"
grep -Fq 'IB_GATEWAY_READY_TIMEOUT_SECONDS="${timeout_seconds}"' "$recover_script"

grep -Fq 'swap_size_mib="${IB_GATEWAY_SWAP_SIZE_MIB:-2048}"' "$swap_script"
grep -Fq 'fallocate -l "${swap_size_mib}M" "${swap_file}"' "$swap_script"
grep -Fq 'swapon "${swap_file}"' "$swap_script"
grep -Fq 'grep -Fq "${swap_file} none swap sw 0 0" /etc/fstab' "$swap_script"
grep -Fq 'printf '\''%s none swap sw 0 0\n'\'' "${swap_file}" >>/etc/fstab' "$swap_script"
