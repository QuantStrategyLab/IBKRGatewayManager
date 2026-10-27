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
        elif isinstance(self.effect, int):
            self.send(self.effect, 1, 'PRIVATE_ACCOUNT_U1234567')

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


class Event:
    def __init__(self):
        self.handlers = []

    def __iadd__(self, handler):
        self.handlers.append(handler)
        return self

    def __isub__(self, handler):
        self.handlers.remove(handler)
        return self

    def emit(self, *args):
        for handler in self.handlers:
            handler(*args)


def stock(symbol, exchange, currency):
    return SimpleNamespace(symbol=symbol, exchange=exchange, currency=currency, secType='STK', conId=0,
                           includeExpired=False, secIdType='', secId='', issuerId='')


class DetailsNative(Native):
    def __init__(self, effect=None, server_version=176):
        super().__init__()
        self.effect = effect
        self.loop = asyncio.new_event_loop()
        self.errorEvent = Event()
        self._onError = lambda *_args: None
        self.errorEvent += self._onError
        self.disconnectedEvent = Event()
        self.future = None
        self.client.getReqId = lambda: 17
        self.client.serverVersion = lambda: server_version
        self.client.reqContractDetails = self.request
        self.wrapper = SimpleNamespace(startReq=self.start, contractDetailsEnd=self.end)

    def run(self, awaitable):
        return self.loop.run_until_complete(awaitable)

    def start(self, req_id, contract):
        self.future = self.loop.create_future()
        return self.future

    def end(self, req_id):
        self.future.set_result(self.details)

    def request(self, req_id, contract):
        if isinstance(self.effect, int):
            self.client.send(self.effect, 1, 'PRIVATE_ACCOUNT_U1234567')
        if self.effect == 'wrong_request':
            contract.symbol = 'OTHER'
        fields = [9, 8, req_id, contract, contract.includeExpired, contract.secIdType, contract.secId]
        if self.client.serverVersion() >= 176:
            fields.append(contract.issuerId)
        self.client.send(*fields)
        if self.effect == 'duplicate':
            self.client.send(*fields)
        returned = stock('OTHER' if self.effect == 'wrong_identity' else 'SOXL', 'SMART', 'USD')
        returned.conId = 123
        self.details = [SimpleNamespace(contract=returned)]
        if self.effect == 'empty':
            self.details = []
        if self.effect == 'ambiguous':
            self.details *= 2
        if self.effect == 'timeout':
            return

        def complete():
            if self.effect == 'callback_exception':
                raise RuntimeError('PRIVATE_ACCOUNT_U1234567')
            elif self.effect == 'rejected':
                self.errorEvent.emit(req_id, 200, 'PRIVATE_ACCOUNT_U1234567', contract)
                self.future.set_result([])
            elif self.effect == 'disconnect':
                self.disconnectedEvent.emit()
                self.future.set_exception(ConnectionError('PRIVATE_ACCOUNT_U1234567'))
            elif self.effect == 'missing_end':
                self.future.set_result(self.details)
            else:
                print('PRIVATE_ACCOUNT_U1234567')
                self.wrapper.contractDetailsEnd(req_id)
        self.loop.call_soon(complete)

    def close(self):
        if self.future is not None and not self.future.done():
            self.future.cancel()
        self.loop.close()


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
        for message in (3, 4, 9, 16, 61, 62):
            native, out = self.invoke(message)
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

    def test_details_source_failure_is_known_before_any_request(self):
        stdout = io.StringIO()
        with patch.object(probe.inspect, 'getsource', side_effect=OSError('PRIVATE_ACCOUNT_U1234567')), \
             patch.object(probe.subprocess, 'run') as run, redirect_stdout(stdout):
            probe.main(['synthetic-container', '4001', '--contract-details'])
        run.assert_not_called()
        self.assertIn('GATEWAY_CONTRACT_DETAILS_REQUEST_ATTEMPTS=0', stdout.getvalue().splitlines())
        self.assertNotIn('PRIVATE_ACCOUNT', stdout.getvalue())

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

    def invoke_details(self, effect=None, server_version=176):
        native = DetailsNative(effect, server_version)
        stdout = io.StringIO()
        original_wait = asyncio.wait_for
        timeouts = []

        async def bounded_wait(awaitable, timeout):
            timeouts.append(timeout)
            return await original_wait(awaitable, .01)

        try:
            with patch.dict(sys.modules, {'ib_insync': SimpleNamespace(IB=lambda: native, Stock=stock)}), \
                 patch('importlib.metadata.version', return_value='0.9.86'), patch('sys.platform', 'linux'), \
                 patch('asyncio.wait_for', bounded_wait), redirect_stdout(stdout):
                out = probe.probe_once(4001, contract_details=True)
            self.assertEqual(stdout.getvalue(), '')
            self.assertNotIn('PRIVATE_ACCOUNT', str(out))
            self.assertEqual(native.disconnections, 1)
            self.assertTrue(all(timeout == 10 for timeout in timeouts))
            return native, out
        finally:
            native.close()

    def test_explicit_details_mode_one_start_and_one_fixed_definition(self):
        for version in (175, 176):
            native, out = self.invoke_details(server_version=version)
            self.assertEqual([call[0][0] for call in native.client.calls], [71, 9])
            self.assertEqual(out['contract_details_status'], 'ready')
            self.assertEqual(out['contract_details_request_attempts'], 1)
            self.assertEqual(out['contract_details_record_count'], 1)
            self.assertTrue(out['contract_details_end_observed'])
            self.assertTrue(out['contract_identity_match'])
            self.assertEqual(out['contract_error_codes'], [])

    def test_details_timeout_and_disconnect_preserve_unknown_record_count(self):
        for effect in ('timeout', 'disconnect'):
            native, out = self.invoke_details(effect)
            self.assertEqual(out['contract_details_status'], 'timeout' if effect == 'timeout' else 'disconnected')
            self.assertIsNone(out['contract_details_record_count'])
            self.assertEqual(out['contract_details_request_attempts'], 1)
            self.assertEqual(len(native.client.calls), 2)

    def test_rejected_request_does_not_turn_into_successful_empty_result(self):
        _, out = self.invoke_details('rejected')
        self.assertEqual(out['contract_details_status'], 'rejected')
        self.assertEqual(out['contract_error_codes'], ['200'])
        self.assertIsNone(out['contract_details_record_count'])
        self.assertFalse(out['contract_details_end_observed'])

    def test_explicit_end_empty_ambiguous_and_identity_mismatch(self):
        for effect, state, count in [('empty', 'empty', 0), ('ambiguous', 'ambiguous', 2), ('wrong_identity', 'identity_mismatch', 1)]:
            _, out = self.invoke_details(effect)
            self.assertEqual(out['contract_details_status'], state)
            self.assertEqual(out['contract_details_record_count'], count)
            self.assertTrue(out['contract_details_end_observed'])
            self.assertEqual(out['status'], 'unavailable')

    def test_missing_end_never_reports_completed_or_ready(self):
        _, out = self.invoke_details('missing_end')
        self.assertEqual(out['contract_details_status'], 'probe_failed')
        self.assertIsNone(out['contract_details_record_count'])

    def test_callback_exception_is_captured_and_cannot_report_success(self):
        _, out = self.invoke_details('callback_exception')
        self.assertEqual(out['contract_details_status'], 'timeout')
        self.assertIsNone(out['contract_details_record_count'])

    def test_transport_rejects_unconfirmed_completion_and_preserves_unknown(self):
        import json
        _, result = self.invoke_details()
        result['contract_details_end_observed'] = False
        stdout = io.StringIO()
        with patch.object(probe.subprocess, 'run', return_value=SimpleNamespace(returncode=0, stdout=json.dumps(result).encode())), redirect_stdout(stdout):
            probe.main(['synthetic-container', '4001', '--contract-details'])
        self.assertIn('GATEWAY_READONLY_API_REASON=native_response_invalid', stdout.getvalue().splitlines())
        self.assertIn('GATEWAY_CONTRACT_DETAILS_REQUEST_ATTEMPTS=unknown', stdout.getvalue().splitlines())

    def test_write_cancel_account_requests_and_wrong_contract_block_before_send(self):
        for effect in (3, 4, 6, 16, 61, 62, 'wrong_request'):
            native, out = self.invoke_details(effect)
            self.assertEqual([call[0][0] for call in native.client.calls], [71])
            self.assertEqual(out['contract_details_request_attempts'], 0)
            self.assertEqual(out['status'], 'unavailable')

    def test_second_definition_is_rejected_and_never_sent(self):
        native, out = self.invoke_details('duplicate')
        self.assertEqual([call[0][0] for call in native.client.calls], [71, 9])
        self.assertEqual(out['contract_details_request_attempts'], 1)
        self.assertEqual(out['contract_details_status'], 'probe_failed')

    def test_details_transport_validates_complete_group_and_real_stdin(self):
        import json
        import os
        import subprocess
        from tempfile import TemporaryDirectory
        _, result = self.invoke_details()
        with TemporaryDirectory() as directory:
            sudo = Path(directory)/'sudo'
            sudo.write_text("#!/bin/sh\nprintf '%s\\n' '" + json.dumps(result) + "'\n")
            sudo.chmod(0o700)
            completed = subprocess.run([sys.executable, '-', 'synthetic-container', '4001', '--contract-details'],
                input=probe.render_remote(), text=True, capture_output=True,
                env={**os.environ, 'PATH': directory+os.pathsep+os.environ['PATH']}, timeout=5)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn('GATEWAY_CONTRACT_DETAILS_STATUS=ready', completed.stdout.splitlines())
        self.assertIsNotNone(classifier.validate_gateway_ssh_response(completed.stdout.splitlines(), readonly_api=True))
        self.assertIsNone(classifier.validate_gateway_ssh_response(completed.stdout.splitlines()[:-1], readonly_api=True))

    def test_details_outer_timeout_attempts_and_completion_are_unknown(self):
        import subprocess
        stdout = io.StringIO()
        with patch.object(probe.subprocess, 'run', side_effect=subprocess.TimeoutExpired('synthetic', 25)), redirect_stdout(stdout):
            probe.main(['synthetic-container', '4001', '--contract-details'])
        lines = stdout.getvalue().splitlines()
        self.assertIn('GATEWAY_CONTRACT_DETAILS_REQUEST_ATTEMPTS=unknown', lines)
        self.assertIn('GATEWAY_CONTRACT_DETAILS_RECORD_COUNT=unknown', lines)
        self.assertIn('GATEWAY_CONTRACT_DETAILS_END_OBSERVED=unknown', lines)
        self.assertIsNotNone(classifier.validate_gateway_ssh_response(lines, readonly_api=True))

    def test_installed_pinned_sdk_request_and_callbacks_without_socket(self):
        bootstrap = asyncio.new_event_loop()
        asyncio.set_event_loop(bootstrap)
        try:
            import ib_insync
            from importlib.metadata import version
        except ImportError:
            self.skipTest('run additionally with the existing pinned SDK environment')
        finally:
            bootstrap.close()
            asyncio.set_event_loop(None)
        if version('ib_insync') != '0.9.86':
            self.skipTest('requires the installed pinned SDK')
        actual_ib = ib_insync.IB
        original_wait = asyncio.wait_for
        for effect in ('ready', 'rejected', 'timeout', 'restored'):
            with self.subTest(effect=effect):
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                native = actual_ib()
                calls = []

                async def connect(host, port, client_id, timeout):
                    native.client.clientId = client_id
                    native.client._apiReady = True
                    native.client._reqIdSeq = 17
                    native.client._serverVersion = 176
                    native.wrapper.managedAccounts('PRIVATE_ACCOUNT_U1234567')
                    native.client.startApi()

                def send(*fields):
                    calls.append(fields)
                    if fields[0] != 9 or effect == 'timeout':
                        return
                    req_id = fields[2]
                    if effect == 'rejected':
                        loop.call_soon(native.wrapper.error, req_id, 200, 'PRIVATE_ACCOUNT_U1234567', '')
                    else:
                        contract = ib_insync.Stock('SOXL', 'SMART', 'USD', conId=123)
                        if effect == 'restored':
                            loop.call_soon(native.wrapper.error, -1, 1102, 'PRIVATE_ACCOUNT_U1234567', '')
                        loop.call_soon(native.wrapper.contractDetails, req_id, ib_insync.ContractDetails(contract=contract))
                        loop.call_soon(native.wrapper.contractDetailsEnd, req_id)

                async def bounded_wait(awaitable, timeout):
                    self.assertEqual(timeout, 10)
                    return await original_wait(awaitable, .01)

                native.client.connectAsync = connect
                native.client.send = send
                summary_calls = []
                native.reqAccountSummaryAsync = lambda: summary_calls.append(True) or loop.create_future()
                stdout = io.StringIO()
                try:
                    with patch.object(ib_insync, 'IB', return_value=native), patch('sys.platform', 'linux'), \
                         patch('asyncio.wait_for', bounded_wait), redirect_stdout(stdout):
                        out = probe.probe_once(4001, contract_details=True)
                    self.assertEqual(stdout.getvalue(), '')
                    self.assertEqual([fields[0] for fields in calls], [71, 9])
                    self.assertEqual(summary_calls, [])
                    self.assertEqual(len(calls[1]), 8)
                    self.assertEqual(out['contract_details_status'], 'ready' if effect == 'restored' else effect)
                    if effect == 'restored':
                        self.assertEqual(out['contract_error_codes'], ['1102'])
                    self.assertNotIn('PRIVATE_ACCOUNT', str(out))
                finally:
                    for task in asyncio.all_tasks(loop):
                        task.cancel()
                    loop.close()
                    asyncio.set_event_loop(None)


if __name__ == '__main__':
    unittest.main()
