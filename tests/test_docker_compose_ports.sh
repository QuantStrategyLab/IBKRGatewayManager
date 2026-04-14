#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd "$(dirname "$0")/.." && pwd)"
compose_file="$repo_dir/docker-compose.yml"

grep -Fq '      - "4001:4003"' "$compose_file"
grep -Fq '      - "4002:4004"' "$compose_file"
grep -Fq '      - TWS_ACCEPT_INCOMING=${TWS_ACCEPT_INCOMING:-accept}' "$compose_file"
grep -Fq '      - READ_ONLY_API=${READ_ONLY_API:-no}' "$compose_file"
grep -Fq '      - JAVA_HEAP_SIZE=${JAVA_HEAP_SIZE:-512}' "$compose_file"
grep -Fq '      - ACCEPT_API_FROM_IP=${ACCEPT_API_FROM_IP:?Set ACCEPT_API_FROM_IP to your Cloud Run egress subnet or connector CIDR}' "$compose_file"
