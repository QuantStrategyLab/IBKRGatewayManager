from __future__ import annotations
import unittest,sys
from dataclasses import replace
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scripts.gateway_epoch_value import EpochCursor,EpochIdentity,EpochValueError,parse_epoch_ns
class T(unittest.TestCase):
 def test_equivalence_order_and_separation(self):
  a=parse_epoch_ns('2026-07-15T16:00:00.1Z'); b=parse_epoch_ns('2026-07-15T16:00:00.100000000+00:00'); self.assertEqual(a,b); self.assertLess(a,parse_epoch_ns('2026-07-15T16:00:00.100000001Z'))
  identity=EpochIdentity('c',a); self.assertEqual(identity,replace(identity)); self.assertNotEqual(identity,EpochIdentity('c',a+1)); self.assertNotEqual(EpochCursor(a),EpochCursor(a+1))
 def test_invalid_is_sanitized(self):
  for value in ('','2026-02-30T00:00:00Z','2026-01-01T00:00:00+01:00','2026-01-01T00:00:00.1234567890Z',None,1):
   with self.subTest(value=value):
    with self.assertRaisesRegex(EpochValueError,'invalid epoch value'): parse_epoch_ns(value)
 def test_constructors_revalidate(self):
  with self.assertRaises(EpochValueError): EpochIdentity('',0)
  with self.assertRaises(EpochValueError): EpochCursor(-1)
  for bad in ('a/b','a\\b','a\n', ' ' * 129):
   with self.subTest(bad=bad):
    with self.assertRaises(EpochValueError): EpochIdentity(bad,0)
  with self.assertRaises(EpochValueError): EpochCursor(253402300800000000000)
if __name__=='__main__':unittest.main()
