BEGIN {
  file_timestamp_pattern = "^[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9] [0-9][0-9]:[0-9][0-9]:[0-9][0-9]$"
  docker_timestamp_pattern = "^[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9](\\.[0-9]+)?Z$"
  latest_timestamp = ""
  latest_state = ""
}

function normalize_timestamp(raw, fraction_start, fraction) {
  sub(/Z$/, "", raw)
  gsub("T", " ", raw)
  fraction_start = index(raw, ".")
  if (fraction_start == 0) {
    return raw ".000000000"
  }

  fraction = substr(raw, fraction_start + 1)
  while (length(fraction) < 9) {
    fraction = fraction "0"
  }
  return substr(raw, 1, fraction_start) substr(fraction, 1, 9)
}

{
  raw_timestamp = $1
  if (raw_timestamp ~ docker_timestamp_pattern) {
    timestamp = normalize_timestamp(raw_timestamp)
  } else {
    raw_timestamp = substr($0, 1, 19)
    if (raw_timestamp !~ file_timestamp_pattern) {
      next
    }
    timestamp = raw_timestamp ".000000000"
  }

  normalized_cutoff = cutoff_timestamp
  if (normalized_cutoff != "" && length(normalized_cutoff) == 19) {
    normalized_cutoff = normalized_cutoff ".000000000"
  }
  if (normalized_cutoff != "" && timestamp < normalized_cutoff) {
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
