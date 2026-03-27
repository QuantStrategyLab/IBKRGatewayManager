#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd "$(dirname "$0")/.." && pwd)"
compose_file="$repo_dir/docker-compose.yml"

grep -Fq '      - "4001:4003"' "$compose_file"
grep -Fq '      - "4002:4004"' "$compose_file"
