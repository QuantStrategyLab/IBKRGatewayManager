from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.gateway_recovery_vocabulary import Decision, Epoch, Event, Machine

EPOCH = Epoch("new", "2026-07-15T16:00:00.123456789Z", "2026-07-15T16:00:00.123456789Z")

def event(line: str, container_id: str = "new", source: str = "docker") -> Event:
    return Event(container_id, source, line)

class VocabularyContract(unittest.TestCase):
    def decision(self, *events: Event) -> Decision:
        return Machine(EPOCH).classify(events)

    def test_approved_exact_progress_markers(self) -> None:
        for marker in (
            "IBC: Starting Gateway", "IBC: Login attempt", "IBC: Second Factor Authentication",
            "IBC: Login has completed", "IBC: Configuration tasks completed",
            "IBC: Found Gateway main window", "IBC: Getting config dialog", "IBC: Getting main window",
            "Authentication window found", "Auto-fill submitted", "Passed token authentication",
            "Authentication completed", "Security code:",
        ):
            with self.subTest(marker=marker):
                self.assertEqual(self.decision(event(f"2026-07-15T16:00:01.000000001Z {marker}")), Decision.PROGRESS)

    def test_negative_epoch_identity_and_near_matches(self) -> None:
        cases = [
            event("2026-07-15T16:00:00.123456788Z IBC: Login attempt"),
            event("2026-07-15T16:00:01Z IBC: Login attempts"),
            event("2026-07-15T16:00:01Z IBC: Dismissing post-login dialog"),
            event("2026-07-15T16:00:01Z ordinary line"), event("untimestamped IBC: Login attempt"),
            event("2026-07-15T16:00:01Z IBC: Login attempt", "old"),
        ]
        for candidate in cases:
            with self.subTest(candidate=candidate): self.assertEqual(self.decision(candidate), Decision.NONE)

    def test_terminal_sticky_and_new_epoch(self) -> None:
        machine = Machine(EPOCH)
        self.assertEqual(machine.classify([event("2026-07-15T16:00:01Z IBC closing because login has not completed")]), Decision.TERMINAL)
        self.assertEqual(machine.classify([event("2026-07-15T16:00:02Z IBC: Login attempt")]), Decision.TERMINAL)
        newer = Epoch("newer", "2026-07-15T16:01:00.000000001Z", "2026-07-15T16:01:00.000000001Z")
        machine.begin(newer)
        self.assertEqual(machine.classify([event("2026-07-15T16:01:01Z IBC: Login attempt", "newer")]), Decision.PROGRESS)

    def test_stable_readiness_and_started_at_drift(self) -> None:
        self.assertEqual(Machine(EPOCH).classify([], stable_ready=True), Decision.READY)
        drifted = Epoch("new", "2026-07-15T16:00:02.000000000Z", "2026-07-15T16:00:02.000000000Z")
        self.assertEqual(Machine(EPOCH).classify([event("2026-07-15T16:00:01Z IBC: Login attempt")], current_epoch=drifted), Decision.EPOCH_CHANGED)

    def test_moving_lower_bound_does_not_change_epoch_identity(self) -> None:
        moved_cursor = Epoch("new", EPOCH.started_at, "2026-07-15T16:00:01.000000000Z")
        self.assertEqual(
            Machine(EPOCH).classify([event("2026-07-15T16:00:01.000000001Z IBC: Login attempt")], current_epoch=moved_cursor),
            Decision.PROGRESS,
        )

if __name__ == "__main__": unittest.main()
