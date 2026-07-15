"""Validated canonical epoch values; intentionally independent from recovery logic."""
from __future__ import annotations
import calendar,re
from dataclasses import dataclass
from datetime import datetime
class EpochValueError(ValueError):
 def __init__(self): super().__init__('invalid epoch value')
STAMP=re.compile(r'^(\d{4})-(\d\d)-(\d\d)T(\d\d):(\d\d):(\d\d)(?:\.(\d{1,9}))?(Z|\+00:00)$')
MAX_EPOCH_NS=253402300799999999999
CONTAINER_ID=re.compile(r'^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$')
def parse_epoch_ns(value: object)->int:
 try:
  if not isinstance(value,str): raise EpochValueError()
  m=STAMP.fullmatch(value)
  if not m: raise EpochValueError()
  year,month,day,hour,minute,second=map(int,m.groups()[:6])
  if year<1970: raise EpochValueError()
  datetime(year,month,day,hour,minute,second)
  return _valid_ns(calendar.timegm((year,month,day,hour,minute,second))*1_000_000_000+int(((m.group(7)or'')+'0'*9)[:9]))
 except (ValueError,OverflowError,TypeError,EpochValueError): raise EpochValueError() from None
def _valid_ns(value: object)->int:
 if type(value) is not int or value<0 or value>MAX_EPOCH_NS: raise EpochValueError()
 return value
def _valid_id(value: object)->str:
 if not isinstance(value,str) or not CONTAINER_ID.fullmatch(value): raise EpochValueError()
 return value
@dataclass(frozen=True,order=True)
class EpochIdentity:
 container_id:str
 started_at_epoch_ns:int
 def __post_init__(self): object.__setattr__(self,'container_id',_valid_id(self.container_id)); object.__setattr__(self,'started_at_epoch_ns',_valid_ns(self.started_at_epoch_ns))
 def serialize(self)->tuple[str,int]: return (self.container_id,self.started_at_epoch_ns)
@dataclass(frozen=True,order=True)
class EpochCursor:
 lower_bound_epoch_ns:int
 def __post_init__(self): object.__setattr__(self,'lower_bound_epoch_ns',_valid_ns(self.lower_bound_epoch_ns))
 def serialize(self)->int:return self.lower_bound_epoch_ns
