#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd "$(dirname "$0")/.." && pwd)"
wrapper="$repo_dir/scripts/classify_gateway_recovery_snapshot.sh"

test -x "$wrapper"

decision="$(printf '%s\n' \
  $'D\tnew-container\t2026-07-15T16:38:22.000000000Z IBC: Login attempt' \
  | "$wrapper" \
      --epoch-container-id new-container \
      --epoch-started-at 2026-07-15T16:38:21.973425214Z \
      --old-container-id old-container \
      --replacement-identity)"
test "$decision" = progress

tmp_dir="$(mktemp -d)"
trap 'rm -rf "$tmp_dir"' EXIT
failing_python="$tmp_dir/failing-python"
cat >"$failing_python" <<'SH'
#!/usr/bin/env bash
exit 42
SH
chmod +x "$failing_python"

if printf '%s\n' $'D\tnew-container\t2026-07-15T16:38:22Z IBC: Login attempt' \
  | IB_GATEWAY_RECOVERY_CLASSIFIER_PYTHON="$failing_python" "$wrapper" \
      --epoch-container-id new-container \
      --epoch-started-at 2026-07-15T16:38:21.973425214Z \
      --old-container-id old-container \
      --replacement-identity; then
  echo 'Python invocation failure must propagate to recovery as fail-closed.' >&2
  exit 1
fi
