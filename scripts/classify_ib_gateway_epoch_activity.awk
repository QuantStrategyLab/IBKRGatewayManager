BEGIN {
  file_timestamp_pattern = "^[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9] [0-9][0-9]:[0-9][0-9]:[0-9][0-9]$"
  rfc3339_timestamp_pattern = "^[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9](\\.[0-9]+)?Z$"
  epoch_start = normalize_timestamp(attempt_start)
  if (epoch_start == "") {
    exit 2
  }
}

function normalize_timestamp(raw, fraction_at, fraction) {
  if (raw ~ rfc3339_timestamp_pattern) {
    sub(/Z$/, "", raw)
    gsub("T", " ", raw)
  } else if (raw !~ file_timestamp_pattern) {
    return ""
  }

  fraction_at = index(raw, ".")
  if (fraction_at == 0) {
    return raw ".000000000"
  }
  fraction = substr(raw, fraction_at + 1)
  while (length(fraction) < 9) {
    fraction = fraction "0"
  }
  return substr(raw, 1, fraction_at) substr(fraction, 1, 9)
}

{
  event_timestamp = normalize_timestamp($1)
  if (event_timestamp == "") {
    event_timestamp = normalize_timestamp(substr($0, 1, 19))
  }
  if (event_timestamp == "" || event_timestamp < epoch_start) {
    next
  }

  if ($0 ~ terminal_regex) {
    terminal_seen = 1
  }
  if ($0 ~ progress_regex) {
    progress_seen = 1
  }
}

END {
  if (terminal_seen) {
    print "terminal"
  } else if (progress_seen) {
    print "progress"
  }
}
