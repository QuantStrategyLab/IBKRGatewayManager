"""Pure, bounded classifier for one immutable IB Gateway recovery epoch snapshot."""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Iterable, TextIO


MAX_SNAPSHOT_EVENTS = 512
MAX_SNAPSHOT_BYTES = 256 * 1024
MAX_LINE_BYTES = 4096

DOCKER_TIMESTAMP = re.compile(
    r"^(?P<date>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?:\.(?P<fraction>\d{1,9}))?Z(?:\s|$)"
)
FILE_TIMESTAMP = re.compile(
    r"^(?P<date>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})(?:(?P<separator>[.,:])(?P<fraction>\d{1,9}))?(?:\s|$)"
)
TIMESTAMP_PREFIX = re.compile(r"^\d{4}-\d{2}-\d{2}[ T]")
PROGRESS_MARKER = re.compile(
    r"IBC: (Starting Gateway|Login attempt|Second Factor Authentication|Login has completed|"
    r"Configuration tasks completed|Found Gateway main window|Getting config dialog|Getting main window)|"
    r"Authentication window found|Auto-fill submitted|Passed token authentication|"
    r"Authentication completed|Security code:",
    re.IGNORECASE,
)
AUTH_CONTEXT_MARKER = re.compile(r"login|authentication|security code|token authentication", re.IGNORECASE)
EXPLICIT_TERMINAL_MARKER = re.compile(
    r"IBC closing because login has not completed|"
    r"(?:authentication|login).*(?:timed out|timeout|failed)|"
    r"(?:timed out|timeout|failed).*(?:authentication|login)",
    re.IGNORECASE,
)
GENERIC_DISCONNECT_MARKER = re.compile(r"connection reset by peer|server disconnected", re.IGNORECASE)
DISMISSAL_MARKER = re.compile(r"dismissing post-login dialog", re.IGNORECASE)


class SnapshotError(ValueError):
    """The primitive event snapshot cannot be safely classified."""


class Decision(str, Enum):
    READY = "ready"
    TERMINAL = "terminal"
    PROGRESS = "progress"
    NONE = "none"
    INVALID = "invalid"


@dataclass(frozen=True)
class Epoch:
    container_id: str
    started_at: str
    event_not_before: str | None = None
    old_container_id: str | None = None
    replacement_identity: bool = False

    def __post_init__(self) -> None:
        if not self.container_id:
            raise SnapshotError("missing epoch container identity")
        if self.replacement_identity and (
            not self.old_container_id or self.old_container_id == self.container_id
        ):
            raise SnapshotError("invalid replacement identity")
        parse_rfc3339_nanos(self.started_at)
        if self.event_not_before is not None:
            parse_rfc3339_nanos(self.event_not_before)

    @property
    def started_key(self) -> tuple[datetime, int]:
        return parse_rfc3339_nanos(self.started_at)

    @property
    def event_lower_bound(self) -> tuple[datetime, int]:
        return parse_rfc3339_nanos(self.event_not_before or self.started_at)


@dataclass(frozen=True)
class PrimitiveEvent:
    source: str
    container_id: str
    line: str


@dataclass(frozen=True)
class FrozenSnapshot:
    events: tuple[PrimitiveEvent, ...]


@dataclass(frozen=True)
class ParsedTimestamp:
    key: tuple[datetime, int]
    precision: str


def parse_rfc3339_nanos(value: str) -> tuple[datetime, int]:
    match = re.fullmatch(r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?:\.(\d{1,9}))?Z", value)
    if match is None:
        raise SnapshotError("invalid epoch StartedAt")
    seconds = datetime.strptime(match.group(1), "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
    return seconds, _fraction_to_nanos(match.group(2))


def _fraction_to_nanos(fraction: str | None) -> int:
    if fraction is None:
        return 0
    return int((fraction + "0" * 9)[:9])


def parse_event_timestamp(source: str, line: str) -> ParsedTimestamp | None:
    if source == "docker":
        match = DOCKER_TIMESTAMP.match(line)
        if match is None:
            return _reject_malformed_timestamp(line)
        seconds = datetime.strptime(match.group("date"), "%Y-%m-%dT%H:%M:%S").replace(
            tzinfo=timezone.utc
        )
        return ParsedTimestamp((seconds, _fraction_to_nanos(match.group("fraction"))), "exact")
    if source == "file":
        match = FILE_TIMESTAMP.match(line)
        if match is None:
            return _reject_malformed_timestamp(line)
        seconds = datetime.strptime(match.group("date"), "%Y-%m-%d %H:%M:%S").replace(
            tzinfo=timezone.utc
        )
        fraction = match.group("fraction")
        precision = "seconds" if fraction is None else "fractional"
        return ParsedTimestamp((seconds, _fraction_to_nanos(fraction)), precision)
    raise SnapshotError("unknown snapshot source")


def _reject_malformed_timestamp(line: str) -> ParsedTimestamp | None:
    if TIMESTAMP_PREFIX.match(line):
        raise SnapshotError("malformed timestamp")
    return None


def freeze_snapshot(events: Iterable[PrimitiveEvent]) -> FrozenSnapshot:
    frozen: list[PrimitiveEvent] = []
    total_bytes = 0
    for event in events:
        if event.source not in {"docker", "file"}:
            raise SnapshotError("unknown snapshot source")
        encoded_size = len(event.line.encode("utf-8", errors="replace"))
        if encoded_size > MAX_LINE_BYTES:
            raise SnapshotError("snapshot line exceeds limit")
        total_bytes += encoded_size
        if total_bytes > MAX_SNAPSHOT_BYTES:
            raise SnapshotError("snapshot exceeds byte limit")
        frozen.append(event)
        if len(frozen) > MAX_SNAPSHOT_EVENTS:
            raise SnapshotError("snapshot exceeds event limit")
    return FrozenSnapshot(tuple(frozen))


class RecoveryEpochMachine:
    """Sticky terminal state scoped to one explicit recovery attempt."""

    def __init__(self, epoch: Epoch) -> None:
        self.epoch = epoch
        self._terminal = False

    def begin_new_attempt(self, epoch: Epoch) -> None:
        self.epoch = epoch
        self._terminal = False

    def classify(self, snapshot: FrozenSnapshot, *, stable_ready: bool = False) -> Decision:
        if stable_ready:
            return Decision.READY
        if self._terminal:
            return Decision.TERMINAL
        try:
            decision = self._classify_frozen_snapshot(snapshot)
        except SnapshotError:
            return Decision.INVALID
        if decision is Decision.TERMINAL:
            self._terminal = True
        return decision

    def _classify_frozen_snapshot(self, snapshot: FrozenSnapshot) -> Decision:
        progress_seen = False
        dismissal_seen = False
        auth_context_seen = False
        generic_disconnect_seen = False

        for event in snapshot.events:
            if event.container_id == self.epoch.old_container_id:
                continue
            if event.container_id != self.epoch.container_id:
                continue
            timestamp = parse_event_timestamp(event.source, event.line)
            if timestamp is None or not self._is_in_epoch(timestamp):
                continue
            if EXPLICIT_TERMINAL_MARKER.search(event.line):
                return Decision.TERMINAL
            if DISMISSAL_MARKER.search(event.line):
                dismissal_seen = True
            if PROGRESS_MARKER.search(event.line):
                progress_seen = True
            if AUTH_CONTEXT_MARKER.search(event.line):
                auth_context_seen = True
            if GENERIC_DISCONNECT_MARKER.search(event.line):
                generic_disconnect_seen = True

        if generic_disconnect_seen and auth_context_seen:
            return Decision.TERMINAL
        # A dismissed dialog is ambiguous. It is only auxiliary evidence after
        # an independent current-epoch auth/login progress marker is present.
        if dismissal_seen and not progress_seen:
            return Decision.NONE
        if progress_seen:
            return Decision.PROGRESS
        return Decision.NONE

    def _is_in_epoch(self, timestamp: ParsedTimestamp) -> bool:
        epoch_seconds, epoch_nanos = self.epoch.event_lower_bound
        event_seconds, event_nanos = timestamp.key
        if event_seconds > epoch_seconds:
            return True
        if event_seconds < epoch_seconds:
            return False
        if timestamp.precision == "seconds":
            # A replacement ID proves the file stream belongs to this attempt,
            # but a seconds-only line cannot be ordered against StartedAt nanos.
            # Include it conservatively; without that identity fail closed.
            if self.epoch.replacement_identity:
                return True
            raise SnapshotError("ambiguous same-second file event")
        return event_nanos >= epoch_nanos


def parse_protocol_snapshot(stream: TextIO) -> FrozenSnapshot:
    events: list[PrimitiveEvent] = []
    total_bytes = 0
    protocol_line_limit = MAX_LINE_BYTES + 256
    while True:
        raw_line = stream.readline(protocol_line_limit + 1)
        if not raw_line:
            break
        if len(raw_line) > protocol_line_limit or (
            len(raw_line) == protocol_line_limit and not raw_line.endswith("\n")
        ):
            raise SnapshotError("snapshot protocol line exceeds limit")
        line = raw_line.rstrip("\n")
        if line.startswith("X\t"):
            raise SnapshotError("snapshot source failed")
        fields = line.split("\t", 2)
        if len(fields) != 3:
            raise SnapshotError("invalid snapshot protocol")
        source_code, container_id, message = fields
        source = {"D": "docker", "F": "file"}.get(source_code)
        if source is None:
            raise SnapshotError("unknown snapshot source")
        encoded_size = len(message.encode("utf-8", errors="replace"))
        if encoded_size > MAX_LINE_BYTES:
            raise SnapshotError("snapshot line exceeds limit")
        total_bytes += encoded_size
        if total_bytes > MAX_SNAPSHOT_BYTES:
            raise SnapshotError("snapshot exceeds byte limit")
        events.append(PrimitiveEvent(source=source, container_id=container_id, line=message))
        if len(events) > MAX_SNAPSHOT_EVENTS:
            raise SnapshotError("snapshot exceeds event limit")
    return FrozenSnapshot(tuple(events))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--epoch-container-id", required=True)
    parser.add_argument("--epoch-started-at", required=True)
    parser.add_argument("--event-not-before")
    parser.add_argument("--old-container-id")
    parser.add_argument("--replacement-identity", action="store_true")
    args = parser.parse_args()
    try:
        epoch = Epoch(
            container_id=args.epoch_container_id,
            started_at=args.epoch_started_at,
            event_not_before=args.event_not_before,
            old_container_id=args.old_container_id,
            replacement_identity=args.replacement_identity,
        )
        snapshot = parse_protocol_snapshot(sys.stdin)
        print(RecoveryEpochMachine(epoch).classify(snapshot).value)
    except SnapshotError:
        print(Decision.INVALID.value)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
