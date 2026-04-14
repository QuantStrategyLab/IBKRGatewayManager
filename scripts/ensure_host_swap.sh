#!/usr/bin/env bash
set -euo pipefail

swap_file="${IB_GATEWAY_SWAP_FILE:-/swapfile}"
swap_size_mib="${IB_GATEWAY_SWAP_SIZE_MIB:-2048}"

if swapon --show=NAME --noheadings | grep -Fxq "${swap_file}"; then
  echo "Swap ${swap_file} is already active."
  exit 0
fi

if [ ! -f "${swap_file}" ]; then
  echo "Creating ${swap_size_mib}MiB swap file at ${swap_file}."
  if ! fallocate -l "${swap_size_mib}M" "${swap_file}" 2>/dev/null; then
    dd if=/dev/zero of="${swap_file}" bs=1M count="${swap_size_mib}" status=progress
  fi
fi

chmod 600 "${swap_file}"

if ! file "${swap_file}" | grep -Fq 'swap file'; then
  mkswap "${swap_file}"
fi

swapon "${swap_file}"

if ! grep -Fq "${swap_file} none swap sw 0 0" /etc/fstab; then
  printf '%s none swap sw 0 0\n' "${swap_file}" >>/etc/fstab
fi

echo "Swap ${swap_file} is active."
