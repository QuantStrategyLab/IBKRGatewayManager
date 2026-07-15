"""Pure full-batch decision precedence for one immutable Gateway epoch."""
from __future__ import annotations
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Iterable
class Decision(str, Enum): TERMINAL='terminal'; READY='ready'; PROGRESS='progress'; NONE='none'; EPOCH_CHANGED='epoch_changed'
@dataclass(frozen=True)
class Epoch: container_id:str; started_at:str; lower_bound:str
@dataclass(frozen=True)
class Event: container_id:str; started_at:str; line:str
@dataclass(frozen=True)
class Result: decision:Decision; sticky_terminal:bool
STAMP=re.compile(r'^(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)(?:\.(\d{1,9}))?Z\s+(.*)$')
TERMINAL=re.compile(r'IBC closing because login has not completed|(?:authentication|login).*(?:timed out|timeout|failed)',re.I)
PROGRESS=re.compile(r'(?:IBC: (?:Starting Gateway|Login attempt|Second Factor Authentication|Login has completed|Configuration tasks completed|Found Gateway main window|Getting config dialog|Getting main window)|Authentication window found|Auto-fill submitted|Passed token authentication|Authentication completed|Security code:)$',re.I)
def key(value:str):
 m=STAMP.match(value+' x')
 if not m: raise ValueError('invalid RFC3339')
 return (datetime.fromisoformat(m.group(1)).replace(tzinfo=timezone.utc),int(((m.group(2)or'')+'0'*9)[:9]))
def decide(epoch:Epoch, events:Iterable[Event], *, stable_ready:bool=False, prior_sticky:bool=False, current_epoch:Epoch|None=None)->Result:
 if current_epoch and (current_epoch.container_id!=epoch.container_id or current_epoch.started_at!=epoch.started_at): return Result(Decision.EPOCH_CHANGED,False)
 if prior_sticky:return Result(Decision.TERMINAL,True)
 events=tuple(events)
 if any(item.container_id!=epoch.container_id or item.started_at!=epoch.started_at for item in events): return Result(Decision.NONE,False)
 lower=key(epoch.lower_bound); ready=stable_ready; progress=False; terminal=False
 for item in events:
  if item.container_id!=epoch.container_id or item.started_at!=epoch.started_at:continue
  match=STAMP.match(item.line)
  if not match:continue
  stamp=(datetime.fromisoformat(match.group(1)).replace(tzinfo=timezone.utc),int(((match.group(2)or'')+'0'*9)[:9]))
  if stamp<lower:continue
  text=match.group(3)
  terminal=terminal or bool(TERMINAL.search(text)); ready=ready or text=='READY'; progress=progress or bool(PROGRESS.fullmatch(text))
 if terminal:return Result(Decision.TERMINAL,True)
 if ready:return Result(Decision.READY,False)
 return Result(Decision.PROGRESS if progress else Decision.NONE,False)
