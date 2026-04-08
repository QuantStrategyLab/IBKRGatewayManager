#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd "$(dirname "$0")/.." && pwd)"
script_file="$repo_dir/scripts/wait_for_ib_gateway_ready.sh"

test -f "$script_file"
test -x "$script_file" || true
grep -Fq 'container_name="${IB_GATEWAY_CONTAINER_NAME:-ib-gateway}"' "$script_file"
grep -Fq 'ready_timeout_seconds="${IB_GATEWAY_READY_TIMEOUT_SECONDS:-240}"' "$script_file"
grep -Fq 'gateway_port=4002' "$script_file"
grep -Fq 'gateway_port=4001' "$script_file"
grep -Fq "docker inspect --format '{{.State.Running}}'" "$script_file"
grep -Fq 'timeout 3 docker exec "${container_name}" bash -lc "exec 3<>/dev/tcp/127.0.0.1/${gateway_port}"' "$script_file"
grep -Fq 'docker logs --tail 120 "${container_name}"' "$script_file"
