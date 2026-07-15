BEGIN {
  timestamp_pattern = "^[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9][T ][0-9][0-9]:[0-9][0-9]:[0-9][0-9]$"
  latest_timestamp = ""
  latest_state = ""
}

{
  timestamp = substr($0, 1, 19)
  if (timestamp !~ timestamp_pattern) {
    next
  }

  gsub("T", " ", timestamp)
  if (cutoff_timestamp != "" && timestamp < cutoff_timestamp) {
    next
  }

  state = ""
  if ($0 ~ progress_regex) {
    state = "progress"
  }
  if ($0 ~ terminal_regex) {
    state = "terminal"
  }

  if (state != "" && (timestamp > latest_timestamp ||
      (timestamp == latest_timestamp && state == "terminal"))) {
    latest_timestamp = timestamp
    latest_state = state
  }
}

END {
  if (latest_state != "") {
    print latest_timestamp "\t" latest_state
  }
}
