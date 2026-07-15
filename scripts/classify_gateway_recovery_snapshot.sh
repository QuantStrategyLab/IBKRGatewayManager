#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "$0")" && pwd)"
classifier_python="${IB_GATEWAY_RECOVERY_CLASSIFIER_PYTHON:-python3}"

exec "${classifier_python}" "${script_dir}/gateway_recovery_classifier.py" "$@"
