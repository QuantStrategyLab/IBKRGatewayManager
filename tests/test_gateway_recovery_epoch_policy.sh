#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd "$(dirname "$0")/.." && pwd)"
recover_script="$repo_dir/scripts/recover_ib_gateway_ready.sh"
classifier="$repo_dir/scripts/classify_ib_gateway_epoch_activity.awk"
twofa_bot="$repo_dir/2fa_bot.py"

test -f "$classifier"
grep -Fq 'IB_GATEWAY_RECOVERY_TERMINAL_REGEX' "$recover_script"
grep -Fq 'gateway_epoch_activity()' "$recover_script"
grep -Fq 'new_recovery_epoch()' "$recover_script"
grep -Fq 'activity="$(gateway_epoch_activity "${attempt_start}")"' "$recover_script"
grep -Fq 'Recent terminal IB gateway authentication failure detected in the current recovery epoch' "$recover_script"
grep -Fq 'Dismissing gateway dialog candidate' "$twofa_bot"
if grep -Fq 'Dismissing post-login dialog' "$recover_script" "$twofa_bot"; then
  echo 'Ambiguous dialog dismissal must not be recovery progress' >&2
  exit 1
fi

default_progress_regex="$(sed -n 's/^progress_regex="${IB_GATEWAY_RECOVERY_PROGRESS_REGEX:-\(.*\)}"$/\1/p' "$recover_script")"
default_terminal_regex="$(sed -n "s/^default_terminal_regex='\\(.*\\)'$/\\1/p" "$recover_script")"
test -n "$default_progress_regex"
test -n "$default_terminal_regex"
case "$default_terminal_regex" in
  *'}') echo 'Terminal regex must not contain the shell parameter-expansion delimiter' >&2; exit 1 ;;
esac
printf '%s\n' 'IBC: Login attempt timed out' | grep -Eq "$default_terminal_regex"
printf '%s\n' 'IBC: timed out waiting for Login' | grep -Eq "$default_terminal_regex"

classify() {
  local attempt_start="$1"
  awk \
    -v attempt_start="$attempt_start" \
    -v progress_regex="$default_progress_regex" \
    -v terminal_regex="$default_terminal_regex" \
    -f "$classifier"
}

pre_epoch_terminal="$(printf '%s\n' \
  '2026-07-15T16:00:00.100000000Z Server disconnected' \
  '2026-07-15T16:00:00.300000000Z IBC: Login attempt' \
  | classify '2026-07-15T16:00:00.200000000Z')"
test "$pre_epoch_terminal" = 'progress'

sticky_terminal="$(printf '%s\n' \
  '2026-07-15T16:00:00.200000000Z Connection reset by peer' \
  '2026-07-15T16:00:00.300000000Z Security code:' \
  '2026-07-15T16:00:00.400000000Z Authentication completed' \
  | classify '2026-07-15T16:00:00.100000000Z')"
test "$sticky_terminal" = 'terminal'

new_epoch_reset="$(printf '%s\n' \
  '2026-07-15T16:00:00.200000000Z Server disconnected' \
  '2026-07-15T16:00:00.400000000Z IBC: Login attempt' \
  | classify '2026-07-15T16:00:00.300000000Z')"
test "$new_epoch_reset" = 'progress'

untimestamped_terminal="$(printf '%s\n' \
  'Server disconnected' \
  '2026-07-15T16:00:00.400000000Z IBC: Login attempt' \
  | classify '2026-07-15T16:00:00.300000000Z')"
test "$untimestamped_terminal" = 'progress'

ready_line="$(grep -n 'if wait_for_ready "${timeout_seconds}"; then' "$recover_script" | head -n 1 | cut -d: -f1)"
activity_line="$(grep -n 'activity="$(gateway_epoch_activity "${attempt_start}")"' "$recover_script" | head -n 1 | cut -d: -f1)"
test -n "$ready_line"
test -n "$activity_line"
test "$ready_line" -lt "$activity_line"

epoch_count="$(grep -c 'attempt_start="$(new_recovery_epoch)"' "$recover_script")"
test "$epoch_count" -eq 3
awk '
  /attempt_start="\$\(new_recovery_epoch\)"/ {
    seen += 1
    if (getline <= 0 || $0 !~ /^docker compose (up|restart)/) {
      exit 1
    }
  }
  END { exit seen == 3 ? 0 : 1 }
' "$recover_script"
