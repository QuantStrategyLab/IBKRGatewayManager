#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd "$(dirname "$0")/.." && pwd)"

actual="$({
  printf '%s\n' 'account=U12345678 host=10.20.30.40 user@example.com'
  printf '%s\n' 'TOTP_SECRET=JBSWY3DPEHPK3PXP'
  printf '%s\n' 'Security code: 123456'
} | python3 "$repo_dir/scripts/redact_gateway_diagnostics.py")"

grep -Fq 'account=U***5678 host=<IP> <EMAIL>' <<<"$actual"
grep -Fq 'TOTP_SECRET=<REDACTED>' <<<"$actual"
grep -Fq 'Security code: <REDACTED>' <<<"$actual"
! grep -Fq 'U12345678' <<<"$actual"
! grep -Fq '10.20.30.40' <<<"$actual"
! grep -Fq 'user@example.com' <<<"$actual"
! grep -Fq 'JBSWY3DPEHPK3PXP' <<<"$actual"
! grep -Fq '123456' <<<"$actual"
