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
grep -Fq 'IB_GATEWAY_HEALTHCHECK_CLIENT_ID:-$((9000 + (BASHPID % 9000)))' "$script_file"
grep -Fq 'check_api_handshake()' "$script_file"
grep -Fq 'from ib_insync import IB' "$script_file"
grep -Fq 'ib.connect(host, port, clientId=client_id, timeout=timeout_seconds)' "$script_file"
grep -Fq 'IB API ib_insync healthcheck ready' "$script_file"
grep -Fq 'b"API\0" + struct.pack(">I", len(b"v157..176")) + b"v157..176"' "$script_file"
grep -Fq 'has_next_valid_id and has_managed_accounts' "$script_file"
grep -Fq 'IB API handshake readiness' "$script_file"
grep -Fq 'docker logs --tail 120 "${container_name}"' "$script_file"
