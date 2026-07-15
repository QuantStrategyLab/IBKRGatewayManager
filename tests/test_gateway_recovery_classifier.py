from __future__ import annotations

import unittest
import sys
from io import StringIO
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import gateway_recovery_classifier as classifier


EPOCH = classifier.Epoch(
    container_id="new-container",
    started_at="2026-07-15T16:38:21.973425214Z",
    old_container_id="old-container",
    replacement_identity=True,
)


def event(source: str, container_id: str, line: str) -> classifier.PrimitiveEvent:
    return classifier.PrimitiveEvent(source=source, container_id=container_id, line=line)


class GatewayRecoveryClassifierTests(unittest.TestCase):
    def classify(self, events: list[classifier.PrimitiveEvent]) -> classifier.Decision:
        machine = classifier.RecoveryEpochMachine(EPOCH)
        return machine.classify(classifier.freeze_snapshot(events))

    def test_old_container_events_are_ignored(self) -> None:
        decision = self.classify(
            [
                event(
                    "docker",
                    "old-container",
                    "2026-07-15T16:38:22.000000000Z IBC closing because login has not completed",
                ),
                event("docker", "new-container", "2026-07-15T16:38:22.000000000Z IBC: Login attempt"),
            ]
        )
        self.assertEqual(decision, classifier.Decision.PROGRESS)

    def test_same_second_low_precision_replacement_event_is_included(self) -> None:
        decision = self.classify(
            [event("file", "new-container", "2026-07-15 16:38:21 Security code:")]
        )
        self.assertEqual(decision, classifier.Decision.PROGRESS)

    def test_same_second_low_precision_nonreplacement_fails_closed(self) -> None:
        epoch = classifier.Epoch(
            container_id="restarted-container",
            started_at="2026-07-15T16:38:21.973425214Z",
            replacement_identity=False,
        )
        machine = classifier.RecoveryEpochMachine(epoch)
        snapshot = classifier.freeze_snapshot(
            [event("file", "restarted-container", "2026-07-15 16:38:21 Security code:")]
        )
        self.assertEqual(machine.classify(snapshot), classifier.Decision.INVALID)

    def test_all_supported_timestamp_formats(self) -> None:
        decision = self.classify(
            [
                event("docker", "new-container", "2026-07-15T16:38:21.973425215Z IBC: Login attempt"),
                event("file", "new-container", "2026-07-15 16:38:22.001 IBC: Login attempt"),
                event("file", "new-container", "2026-07-15 16:38:22,002 IBC: Login attempt"),
                event("file", "new-container", "2026-07-15 16:38:22:003 IBC: Login attempt"),
            ]
        )
        self.assertEqual(decision, classifier.Decision.PROGRESS)

    def test_untimestamped_is_ignored_but_malformed_fails_closed(self) -> None:
        self.assertEqual(
            self.classify([event("docker", "new-container", "Server disconnected")]),
            classifier.Decision.NONE,
        )
        self.assertEqual(
            self.classify([event("file", "new-container", "2026-07-15 16:38:21: malformed")]),
            classifier.Decision.INVALID,
        )

    def test_terminal_is_sticky_after_later_progress(self) -> None:
        machine = classifier.RecoveryEpochMachine(EPOCH)
        terminal_snapshot = classifier.freeze_snapshot(
            [event("docker", "new-container", "2026-07-15T16:38:22Z IBC closing because login has not completed")]
        )
        progress_snapshot = classifier.freeze_snapshot(
            [event("docker", "new-container", "2026-07-15T16:38:23Z IBC: Login attempt")]
        )
        self.assertEqual(machine.classify(terminal_snapshot), classifier.Decision.TERMINAL)
        self.assertEqual(machine.classify(progress_snapshot), classifier.Decision.TERMINAL)

    def test_progress_then_auth_disconnect_is_terminal(self) -> None:
        decision = self.classify(
            [
                event("docker", "new-container", "2026-07-15T16:38:22Z Security code:"),
                event("docker", "new-container", "2026-07-15T16:38:23Z Server disconnected"),
            ]
        )
        self.assertEqual(decision, classifier.Decision.TERMINAL)

    def test_stable_readiness_succeeds_without_classifying_logs(self) -> None:
        machine = classifier.RecoveryEpochMachine(EPOCH)
        terminal_snapshot = classifier.freeze_snapshot(
            [event("docker", "new-container", "2026-07-15T16:38:22Z IBC closing because login has not completed")]
        )
        self.assertEqual(machine.classify(terminal_snapshot, stable_ready=True), classifier.Decision.READY)

    def test_new_recovery_attempt_resets_terminal_state(self) -> None:
        machine = classifier.RecoveryEpochMachine(EPOCH)
        terminal_snapshot = classifier.freeze_snapshot(
            [event("docker", "new-container", "2026-07-15T16:38:22Z IBC closing because login has not completed")]
        )
        self.assertEqual(machine.classify(terminal_snapshot), classifier.Decision.TERMINAL)

        new_epoch = classifier.Epoch(
            container_id="newer-container",
            started_at="2026-07-15T16:40:00.000000000Z",
            old_container_id="new-container",
            replacement_identity=True,
        )
        machine.begin_new_attempt(new_epoch)
        progress_snapshot = classifier.freeze_snapshot(
            [event("docker", "newer-container", "2026-07-15T16:40:01Z IBC: Login attempt")]
        )
        self.assertEqual(machine.classify(progress_snapshot), classifier.Decision.PROGRESS)

    def test_snapshot_is_bounded_and_immutable_across_source_divergence(self) -> None:
        events = [event("docker", "new-container", "2026-07-15T16:38:22Z IBC: Login attempt")]
        snapshot = classifier.freeze_snapshot(events)
        events.append(
            event("docker", "new-container", "2026-07-15T16:38:23Z IBC closing because login has not completed")
        )
        machine = classifier.RecoveryEpochMachine(EPOCH)
        self.assertEqual(machine.classify(snapshot), classifier.Decision.PROGRESS)
        self.assertEqual(machine.classify(snapshot), classifier.Decision.PROGRESS)

        oversized = [event("docker", "new-container", "x")] * (classifier.MAX_SNAPSHOT_EVENTS + 1)
        with self.assertRaises(classifier.SnapshotError):
            classifier.freeze_snapshot(oversized)
        protocol = StringIO(
            "".join(
                "D\tnew-container\t2026-07-15T16:38:22Z IBC: Login attempt\n"
                for _ in range(classifier.MAX_SNAPSHOT_EVENTS + 1)
            )
        )
        with self.assertRaises(classifier.SnapshotError):
            classifier.parse_protocol_snapshot(protocol)
        with self.assertRaises(classifier.SnapshotError):
            classifier.parse_protocol_snapshot(
                StringIO("D\tnew-container\t" + "x" * (classifier.MAX_LINE_BYTES + 1))
            )

    def test_source_failure_sentinel_is_sanitized_fail_closed(self) -> None:
        with self.assertRaises(classifier.SnapshotError):
            classifier.parse_protocol_snapshot(StringIO("X\\tfile\\n"))


if __name__ == "__main__":
    unittest.main()
