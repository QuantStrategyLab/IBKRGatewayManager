function canonical_timestamp(value, fraction, digits) {
  if (value ~ /^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]+)?Z$/) {
    sub(/Z$/, "", value)
    sub(/T/, " ", value)
  } else if (value !~ /^[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]+)?$/) {
    return ""
  }

  if (value ~ /\./) {
    fraction = value
    sub(/^.*\./, "", fraction)
    sub(/\..*$/, "", value)
  } else {
    fraction = ""
  }
  digits = length(fraction)
  if (digits > 9) {
    fraction = substr(fraction, 1, 9)
  }
  while (length(fraction) < 9) {
    fraction = fraction "0"
  }
  return value "." fraction
}

BEGIN {
  epoch_timestamp = canonical_timestamp(epoch_started_at)
  if (epoch_timestamp == "") {
    exit 2
  }
}

{
  line_timestamp = ""
  if ($0 ~ /^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]+)?Z[[:space:]]/) {
    line_timestamp = $1
  } else if ($0 ~ /^[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]+)?[[:space:]]/) {
    line_timestamp = $1 " " $2
  }

  line_timestamp = canonical_timestamp(line_timestamp)
  if (line_timestamp == "" || line_timestamp < epoch_timestamp) {
    next
  }
  if ($0 ~ terminal_regex) {
    terminal_found = 1
  }
  if ($0 ~ progress_regex) {
    progress_found = 1
  }
}

END {
  if (terminal_found) {
    print "terminal"
  } else if (progress_found) {
    print "progress"
  } else {
    print "none"
  }
}
