#!/usr/bin/env python3
"""Redact account and credential-like values from gateway diagnostics."""

from __future__ import annotations

import re
import sys


ACCOUNT_PATTERN = re.compile(r"(?i)\bu(\d{4,})\b")
EMAIL_PATTERN = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
IPV4_PATTERN = re.compile(r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])")
SENSITIVE_ASSIGNMENT_PATTERN = re.compile(
    r"(?i)\b([A-Z0-9_]*(?:PASSWORD|SECRET|TOKEN|COOKIE|AUTHORIZATION)[A-Z0-9_]*)"
    r"(\s*[:=]\s*)(\S+)"
)
SECURITY_CODE_PATTERN = re.compile(r"(?i)(\bsecurity\s+code\s*[:=]\s*)\S+")


def redact_line(line: str) -> str:
    line = ACCOUNT_PATTERN.sub(lambda match: f"U***{match.group(1)[-4:]}", line)
    line = EMAIL_PATTERN.sub("<EMAIL>", line)
    line = IPV4_PATTERN.sub("<IP>", line)
    line = SENSITIVE_ASSIGNMENT_PATTERN.sub(r"\1\2<REDACTED>", line)
    return SECURITY_CODE_PATTERN.sub(r"\1<REDACTED>", line)


def main() -> int:
    for line in sys.stdin:
        sys.stdout.write(redact_line(line))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
