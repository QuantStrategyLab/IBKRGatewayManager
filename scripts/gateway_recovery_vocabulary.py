"""Pure, Python 3.10-compatible current-epoch recovery vocabulary."""
from __future__ import annotations
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Iterable

class Decision(str, Enum): READY="ready"; TERMINAL="terminal"; PROGRESS="progress"; NONE="none"; EPOCH_CHANGED="epoch_changed"
@dataclass(frozen=True)
class Epoch: container_id: str; started_at: str; lower_bound: str
@dataclass(frozen=True)
class Event: container_id: str; source: str; line: str
PROGRESS = re.compile(r"(?:IBC: (?:Starting Gateway|Login attempt|Second Factor Authentication|Login has completed|Configuration tasks completed|Found Gateway main window|Getting config dialog|Getting main window)|Authentication window found|Auto-fill submitted|Passed token authentication|Authentication completed|Security code:)$", re.I)
TERMINAL = re.compile(r"IBC closing because login has not completed|(?:authentication|login).*(?:timed out|timeout|failed)", re.I)
STAMP = re.compile(r"^(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)(?:\.(\d{1,9}))?Z\s+(.*)$")
def stamp(value: str) -> tuple[datetime,int] | None:
    match=STAMP.match(value)
    if not match: return None
    return (datetime.fromisoformat(match.group(1)).replace(tzinfo=timezone.utc), int(((match.group(2) or '')+'0'*9)[:9]))
def epoch_key(value: str) -> tuple[datetime,int]:
    parsed=stamp(value+' x')
    if parsed is None: raise ValueError('invalid RFC3339 timestamp')
    return parsed
class Machine:
    def __init__(self, epoch: Epoch): self.epoch=epoch; self.terminal=False
    def begin(self, epoch: Epoch) -> None: self.epoch=epoch; self.terminal=False
    def classify(self, events: Iterable[Event], *, stable_ready: bool=False, current_epoch: Epoch|None=None) -> Decision:
        if current_epoch is not None and (
            current_epoch.container_id != self.epoch.container_id
            or current_epoch.started_at != self.epoch.started_at
        ): return Decision.EPOCH_CHANGED
        if stable_ready: return Decision.READY
        if self.terminal: return Decision.TERMINAL
        lower=epoch_key(self.epoch.lower_bound)
        for item in events:
            if item.container_id != self.epoch.container_id: continue
            parsed=stamp(item.line)
            if parsed is None or parsed < lower: continue
            message=item.line.split(' ', 1)[1] if ' ' in item.line else ''
            if TERMINAL.search(message): self.terminal=True; return Decision.TERMINAL
            if PROGRESS.fullmatch(message): return Decision.PROGRESS
        return Decision.NONE
