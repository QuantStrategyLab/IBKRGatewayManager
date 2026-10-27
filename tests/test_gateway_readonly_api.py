from __future__ import annotations

import asyncio
import importlib.util
import io
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from contextlib import redirect_stdout

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('gateway_readonly_api', ROOT/'scripts/inspect_gateway_readonly_api.py')
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)
spec = importlib.util.spec_from_file_location('gateway_ssh_classify', ROOT/'scripts/classify_gateway_ssh_failure.py')
classifier = importlib.util.module_from_spec(spec)
spec.loader.exec_module(classifier)


class Client:
    def __init__(self, effect=None):
        self.calls = []
        self.effect = effect

    def send(self, *fields, **kwargs):
        self.calls.append((fields, kwargs))

    async def connectAsync(self, host, port, client_id, timeout):
        self.binding = host, port, client_id, timeout
        self.send(71, 2, client_id, '')
        print('PRIVATE_ACCOUNT_U1234567')
        if self.effect == 'timeout':
            raise TimeoutError('PRIVATE_ACCOUNT_U1234567')
        if self.effect == 'forbidden':
            self.send(3, 1, 'PRIVATE_ACCOUNT_U1234567')

    def isReady(self):
        return True


class Native:
    def __init__(self, effect=None):
        self.client = Client(effect)
        self.disconnections = 0

    def run(self, awaitable):
        return asyncio.run(awaitable)

    def managedAccounts(self):
        return ['PRIVATE_ACCOUNT_U1234567']

    def disconnect(self):
        self.disconnections += 1


class ProbeTests(unittest.TestCase):
    def invoke(self, effect=None, version='0.9.86'):
        native = Native(effect)
        stdout = io.StringIO()
        with patch.dict(sys.modules, {'ib_insync': SimpleNamespace(IB=lambda: native)}), \
             patch('importlib.metadata.version', return_value=version), patch('sys.platform', 'linux'), redirect_stdout(stdout):
            out = probe.probe_once(4001)
        self.assertEqual(stdout.getvalue(), '')
        self.assertNotIn('PRIVATE_ACCOUNT', str(out))
        return native, out

    def test_one_low_level_start_api_with_no_account_sync_or_writes(self):
        native, out = self.invoke()
        self.assertTrue(out['api_session_ready'])
        self.assertEqual(out['managed_account_count'], 1)
        self.assertFalse(out['account_identity_verified'])
        self.assertEqual(out['connection_attempts'], 1)
        self.assertEqual(len(native.client.calls), 1)
        self.assertEqual(native.client.calls[0][0][:2], (71, 2))
        self.assertEqual(native.client.binding[:2], ('127.0.0.1', 4001))
        self.assertEqual(native.disconnections, 1)

    def test_timeout_is_not_retried_and_disconnects(self):
        native, out = self.invoke('timeout')
        self.assertEqual(out['reason'], 'api_session_timeout')
        self.assertEqual(out['connection_attempts'], 1)
        self.assertEqual(len(native.client.calls), 1)
        self.assertEqual(native.disconnections, 1)

    def test_every_non_start_api_request_is_rejected_before_native_send(self):
        native, out = self.invoke('forbidden')
        self.assertEqual(out['reason'], 'api_probe_failed')
        self.assertEqual(len(native.client.calls), 1)
        self.assertEqual(native.disconnections, 1)

    def test_unpinned_client_never_connects(self):
        native, out = self.invoke(version='0.0.0')
        self.assertEqual(out['reason'], 'client_prerequisite_unavailable')
        self.assertEqual(out['connection_attempts'], 0)
        self.assertEqual(native.client.calls, [])

    def test_transport_only_accepts_fixed_result_schema(self):
        private = b'PRIVATE_ACCOUNT_U1234567'
        stdout = io.StringIO()
        with patch.object(probe.subprocess, 'run', return_value=SimpleNamespace(returncode=0, stdout=private)), redirect_stdout(stdout):
            self.assertEqual(probe.main(['synthetic-container', '4001']), 0)
        lines = stdout.getvalue().splitlines()
        self.assertNotIn('PRIVATE_ACCOUNT', stdout.getvalue())
        self.assertIn('GATEWAY_READONLY_API_STATUS=unavailable', lines)
        self.assertIn('GATEWAY_READONLY_API_CONNECTION_ATTEMPTS=unknown', lines)
        self.assertIsNotNone(classifier.validate_gateway_ssh_response(lines, readonly_api=True))
        self.assertIsNone(classifier.validate_gateway_ssh_response(lines))
        self.assertIsNone(classifier.validate_gateway_ssh_response(lines + ['PRIVATE_ACCOUNT_U1234567'], readonly_api=True))

    def test_rendered_program_runs_from_real_ssh_style_stdin(self):
        import json
        import os
        import subprocess
        from tempfile import TemporaryDirectory
        result = dict(status="observed", reason="api_session_ready", connection_attempts=1,
                      api_session_ready=True, managed_account_count=1,
                      account_identity_verified=False, broker_write_attempts=0)
        with TemporaryDirectory() as directory:
            sudo = Path(directory)/'sudo'
            sudo.write_text("#!/bin/sh\nprintf '%s\\n' '" + json.dumps(result) + "'\n")
            sudo.chmod(0o700)
            completed = subprocess.run([sys.executable, '-', 'synthetic-container', '4001'],
                input=probe.render_remote(), text=True, capture_output=True,
                env={**os.environ, 'PATH': directory+os.pathsep+os.environ['PATH']}, timeout=5)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn('GATEWAY_READONLY_API_STATUS=observed', completed.stdout.splitlines())
        self.assertIn('GATEWAY_READONLY_API_CONNECTION_ATTEMPTS=1', completed.stdout.splitlines())
        self.assertNotIn('inspect', completed.stderr)
        self.assertIsNotNone(classifier.validate_gateway_ssh_response(completed.stdout.splitlines(), readonly_api=True))

    def test_unrendered_stdin_source_failure_occurs_before_native_launch(self):
        import os
        import subprocess
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as directory:
            trace = Path(directory)/'native-launched'
            sudo = Path(directory)/'sudo'
            sudo.write_text("#!/bin/sh\ntouch '" + str(trace) + "'\nexit 1\n")
            sudo.chmod(0o700)
            completed = subprocess.run([sys.executable, '-', 'synthetic-container', '4001'],
                input=(ROOT/'scripts/inspect_gateway_readonly_api.py').read_text(),
                text=True, capture_output=True,
                env={**os.environ, 'PATH': directory+os.pathsep+os.environ['PATH']}, timeout=5)
            self.assertFalse(trace.exists())
        self.assertIn('GATEWAY_READONLY_API_REASON=probe_source_unavailable', completed.stdout.splitlines())
        self.assertIn('GATEWAY_READONLY_API_CONNECTION_ATTEMPTS=0', completed.stdout.splitlines())

    def test_outer_timeout_preserves_unknown_attempt_count(self):
        import subprocess
        stdout = io.StringIO()
        with patch.object(probe.subprocess, 'run', side_effect=subprocess.TimeoutExpired('synthetic', 25)), redirect_stdout(stdout):
            probe.main(['synthetic-container', '4001'])
        self.assertIn('GATEWAY_READONLY_API_CONNECTION_ATTEMPTS=unknown', stdout.getvalue().splitlines())
        self.assertIn('GATEWAY_READONLY_API_REASON=native_transport_timeout', stdout.getvalue().splitlines())

    def test_source_failure_is_known_before_any_native_launch(self):
        stdout = io.StringIO()
        with patch.object(probe.inspect, 'getsource', side_effect=OSError('private fixture')), \
             patch.object(probe.subprocess, 'run') as run, redirect_stdout(stdout):
            probe.main(['synthetic-container', '4001'])
        run.assert_not_called()
        self.assertIn('GATEWAY_READONLY_API_CONNECTION_ATTEMPTS=0', stdout.getvalue().splitlines())
        self.assertIn('GATEWAY_READONLY_API_REASON=probe_source_unavailable', stdout.getvalue().splitlines())
        self.assertNotIn('private fixture', stdout.getvalue())

    def test_invalid_binding_does_not_execute(self):
        with patch.object(probe.subprocess, 'run') as run, redirect_stdout(io.StringIO()):
            probe.main(['bad;name', '4001'])
        run.assert_not_called()


if __name__ == '__main__':
    unittest.main()
