#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd "$(dirname "$0")/.." && pwd)"
recover_script="$repo_dir/scripts/recover_ib_gateway_ready.sh"
epoch_helpers="$repo_dir/scripts/ib_gateway_container_epoch.sh"
classifier="$repo_dir/scripts/classify_ib_gateway_epoch_activity.awk"
twofa_bot="$repo_dir/2fa_bot.py"

test -f "$epoch_helpers"
test -f "$classifier"
# shellcheck source=/dev/null
source "$epoch_helpers"

valid_started_at='2026-07-15T16:38:21.973425214Z'
ib_gateway_validate_replacement_epoch old-id new-id "$valid_started_at"
if ib_gateway_validate_replacement_epoch old-id '' "$valid_started_at"; then
  echo 'Missing replacement ID must fail closed' >&2
  exit 1
fi
if ib_gateway_validate_replacement_epoch '' new-id "$valid_started_at"; then
  echo 'Missing old ID must fail closed' >&2
  exit 1
fi
if ib_gateway_validate_replacement_epoch old-id old-id "$valid_started_at"; then
  echo 'Same replacement ID must fail closed' >&2
  exit 1
fi
if ib_gateway_validate_replacement_epoch old-id new-id '0001-01-01T00:00:00Z'; then
  echo 'Invalid StartedAt must fail closed' >&2
  exit 1
fi

inspected_epoch="$({
  docker() {
    test "$1" = inspect
    printf '%s\n' 'new-id 2026-07-15T16:38:21.973425214Z'
  }
  ib_gateway_inspect_container_epoch ib-gateway
})"
test "$inspected_epoch" = 'new-id 2026-07-15T16:38:21.973425214Z'
if (
  docker() { return 1; }
  ib_gateway_inspect_container_epoch ib-gateway
); then
  echo 'Missing inspect result must fail closed' >&2
  exit 1
fi
if (
  docker() { printf '%s\n' 'new-id invalid-started-at'; }
  ib_gateway_inspect_container_epoch ib-gateway
); then
  echo 'Invalid inspected StartedAt must fail closed' >&2
  exit 1
fi

default_progress_regex="$(sed -n 's/^progress_regex="${IB_GATEWAY_RECOVERY_PROGRESS_REGEX:-\(.*\)}"$/\1/p' "$recover_script")"
default_terminal_regex="$(sed -n "s/^default_terminal_regex='\\(.*\\)'$/\\1/p" "$recover_script")"
test -n "$default_progress_regex"
test -n "$default_terminal_regex"

classify() {
  local epoch_started_at="$1"
  awk \
    -v epoch_started_at="$epoch_started_at" \
    -v progress_regex="$default_progress_regex" \
    -v terminal_regex="$default_terminal_regex" \
    -f "$classifier"
}

old_shutdown_ignored="$(printf '%s\n' \
  '2026-07-15T16:38:21.900000000Z Server disconnected' \
  '2026-07-15T16:38:21.980000000Z IBC: Login attempt' \
  | classify "$valid_started_at")"
test "$old_shutdown_ignored" = 'progress'

replacement_terminal_sticky="$(printf '%s\n' \
  '2026-07-15T16:38:21.980000000Z Connection reset by peer' \
  '2026-07-15T16:38:22.100000000Z Security code:' \
  '2026-07-15T16:38:22.200000000Z Authentication completed' \
  | classify "$valid_started_at")"
test "$replacement_terminal_sticky" = 'terminal'

untimestamped_terminal="$(printf '%s\n' \
  'Server disconnected' \
  '2026-07-15T16:38:22.100000000Z IBC: Login attempt' \
  | classify "$valid_started_at")"
test "$untimestamped_terminal" = 'progress'

grep -Fq 'replace_gateway_container()' "$recover_script"
grep -Fq 'old_container_id="$(docker inspect --format '\''{{.Id}}'\'' "${container_name}"' "$recover_script"
grep -Fq 'docker compose stop "${compose_service_name}"' "$recover_script"
grep -Fq 'docker compose rm -f "${compose_service_name}"' "$recover_script"
grep -Fq 'docker inspect "${old_container_id}"' "$recover_script"
grep -Fq 'ib_gateway_inspect_container_epoch "${container_name}"' "$recover_script"
grep -Fq 'ib_gateway_validate_replacement_epoch "${old_container_id}" "${replacement_container_id}" "${replacement_started_at}"' "$recover_script"
grep -Fq 'docker logs --timestamps --since "${epoch_started_at}" "${epoch_container_id}"' "$recover_script"
grep -Fq 'docker exec "${epoch_container_id}"' "$recover_script"
grep -Fq 'IB_GATEWAY_CONTAINER_NAME="${epoch_container_id}"' "$recover_script"
grep -Fq 'if wait_for_ready "${initial_wait_seconds}" "${epoch_container_id}"; then' "$recover_script"
if grep -Fq 'wait_for_ready_with_progress "${initial_wait_seconds}"' "$recover_script"; then
  echo 'Pre-replacement container logs must not be classified as a recovery epoch' >&2
  exit 1
fi
if grep -Eq 'docker (logs|exec).*\$\{container_name\}' "$recover_script"; then
  echo 'Log classification must never fall back to the reusable container name' >&2
  exit 1
fi
if grep -Fq 'tail -n' "$recover_script"; then
  echo 'Sticky terminal classification must scan the complete current epoch' >&2
  exit 1
fi

ready_line="$(grep -n 'if wait_for_ready "${timeout_seconds}" "${epoch_container_id}"; then' "$recover_script" | head -n 1 | cut -d: -f1)"
activity_line="$(grep -n 'activity="$(gateway_epoch_activity "${epoch_container_id}" "${epoch_started_at}")"' "$recover_script" | head -n 1 | cut -d: -f1)"
test -n "$ready_line"
test -n "$activity_line"
test "$ready_line" -lt "$activity_line"

grep -Fq 'Dismissing gateway dialog candidate' "$twofa_bot"
if grep -Fq 'Dismissing post-login dialog' "$recover_script" "$twofa_bot"; then
  echo 'Ambiguous dialog dismissal must not be recovery progress' >&2
  exit 1
fi
