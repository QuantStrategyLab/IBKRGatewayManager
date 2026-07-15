from __future__ import annotations
import sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.gateway_recovery_decision import Decision, Epoch, Event, decide
E=Epoch('c','2026-07-15T16:00:00.123456789Z','2026-07-15T16:00:00.123456789Z')
def e(text, cid='c'): return Event(cid,text)
class Contract(unittest.TestCase):
 def test_precedence_permutations(self):
  terminal=e('2026-07-15T16:00:02Z IBC closing because login has not completed'); ready=e('2026-07-15T16:00:01Z READY'); progress=e('2026-07-15T16:00:01Z IBC: Login attempt')
  for batch in ([ready,terminal],[terminal,ready],[progress,terminal],[terminal,progress]): self.assertEqual(decide(E,batch).decision,Decision.TERMINAL)
 def test_ready_progress_none(self):
  self.assertEqual(decide(E,[e('2026-07-15T16:00:01Z READY')]).decision,Decision.READY)
  self.assertEqual(decide(E,[e('2026-07-15T16:00:01Z IBC: Found Gateway main window')]).decision,Decision.PROGRESS)
  for x in ('2026-07-15T16:00:01Z IBC: Dismissing post-login dialog','2026-07-15T16:00:01Z IBC: Login attempts','untimestamped IBC: Login attempt') : self.assertEqual(decide(E,[e(x)]).decision,Decision.NONE)
 def test_sticky_cursor_and_drift(self):
  first=decide(E,[e('2026-07-15T16:00:01Z IBC closing because login has not completed')]); self.assertTrue(first.sticky_terminal)
  moved=Epoch('c',E.started_at,'2026-07-15T16:00:01.000000000Z'); self.assertEqual(decide(moved,[e('2026-07-15T16:00:02Z IBC: Login attempt')],prior_sticky=True).decision,Decision.TERMINAL)
  drift=Epoch('c','2026-07-15T16:01:00.000000000Z','2026-07-15T16:01:00.000000000Z'); self.assertEqual(decide(E,[],current_epoch=drift,prior_sticky=True).decision,Decision.EPOCH_CHANGED)
 def test_filters(self):
  self.assertEqual(decide(E,[e('2026-07-15T16:00:00.123456788Z IBC: Login attempt'),e('2026-07-15T16:00:01Z IBC: Login attempt','old')]).decision,Decision.NONE)
if __name__=='__main__': unittest.main()
