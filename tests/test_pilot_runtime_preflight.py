"""Synthetic host/image/package metadata; never connect to a Gateway."""
import json
from contextlib import redirect_stdout
import io
import os
from pathlib import Path
import sys
import tempfile
import hashlib
import urllib.error
import urllib.request
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.pilot_runtime_preflight import (CANDIDATE, PACKAGE_PROBE, observe, valid_result,
    BASE_DIGEST, image_access, image_result, valid_image_result)
from scripts.run_native_cash_ssh import main as transport_main, preflight_program


class PilotRuntimePreflightTests(unittest.TestCase):
    def inspect(self, *, labels=None, pins=None, failure=None, payload=None):
        calls = []

        def run(args):
            calls.append(tuple(args))
            if failure:
                raise RuntimeError(failure)
            if args[3] == 'inspect':
                return 'true'
            if args[3:5] == ('image', 'ls'):
                return 'sha256:' + '1' * 64
            if args[3:5] == ('image', 'inspect'):
                return json.dumps(labels or {})
            if args[3] == 'exec':
                return json.dumps(payload or dict(python_minor='3.11', dependency_pins=pins or
                    dict(qpk='MISSING', ues='MISSING', hes='MISSING', sdk='MATCHED')))
            raise AssertionError('unexpected command')

        with patch('scripts.pilot_runtime_preflight.Path.read_text', return_value='MemAvailable: 524288 kB\n'), \
                patch('scripts.pilot_runtime_preflight.shutil.disk_usage', return_value=SimpleNamespace(free=104857600)):
            return observe('synthetic-gateway', run=run), calls

    def test_missing_strategy_dependencies_stay_missing_without_install_or_launch(self):
        out, calls = self.inspect()
        self.assertEqual(out['status'], 'observed')
        self.assertEqual(out['dependency_pins'], dict(qpk='MISSING', ues='MISSING', hes='MISSING', sdk='MATCHED'))
        self.assertEqual(out['candidate_image_label_count'], 0)
        self.assertEqual(out['host_memory_available_mib'], 512)
        self.assertTrue(valid_result(out))
        for key in ('runtime_ready', 'candidate_source_verified', 'broker_called',
                    'strategy_computation_started', 'image_pull_attempted', 'configuration_changed'):
            self.assertIs(out[key], False)
        self.assertTrue(all(call[:3] == ('sudo', '-n', 'docker') for call in calls))
        self.assertFalse(any(word in ('pull', 'run', 'start', 'restart', 'build') for call in calls for word in call))

    def test_matching_labels_and_dependencies_do_not_certify_source_or_runtime(self):
        out, _ = self.inspect(labels={'org.opencontainers.image.revision': CANDIDATE},
                              pins=dict(qpk='MATCHED', ues='MATCHED', hes='MATCHED', sdk='MATCHED'))
        self.assertEqual(out['candidate_image_label_count'], 1)
        self.assertFalse(out['candidate_source_verified'])
        self.assertFalse(out['runtime_ready'])

    def test_conflicting_labels_are_not_a_candidate_match(self):
        out, _ = self.inspect(labels={'org.opencontainers.image.revision': CANDIDATE, 'commit-sha': 'f' * 40})
        self.assertEqual(out['candidate_image_label_count'], 0)

    def test_malformed_package_response_cannot_leak_arbitrary_data(self):
        private = 'private-account-and-token'
        out, _ = self.inspect(payload=dict(python_minor='3.11', dependency_pins={}, account=private))
        self.assertEqual(out['status'], 'unavailable')
        self.assertEqual(out['reason'], 'dependency_metadata_failed')
        self.assertNotIn(private, json.dumps(out))

    def test_failed_metadata_read_is_not_an_empty_inventory(self):
        out, _ = self.inspect(failure='private-host-secret')
        self.assertEqual(out['status'], 'unavailable')
        self.assertIsNone(out['candidate_image_label_count'])
        self.assertNotIn('private-host-secret', json.dumps(out))
        self.assertTrue(valid_result(out))

    def test_validator_rejects_extra_fields_claims_and_bad_types(self):
        out, _ = self.inspect()
        for changed in ({**out, 'account': 'private'}, {**out, 'broker_called': True},
                        {**out, 'runtime_ready': True}, {**out, 'candidate_image_label_count': False},
                        {**out, 'reason': []}, {**out, 'host_architecture': []},
                        {**out, 'python_minor': 'private'}, {**out, 'dependency_pins': dict(qpk='MATCHED')}):
            self.assertFalse(valid_result(changed))

    def test_invalid_container_does_not_invoke_docker(self):
        out = observe('bad;container', run=lambda _: self.fail('command called'))
        self.assertEqual(out['reason'], 'request_invalid')
        self.assertTrue(valid_result(out))

    def test_package_probe_reads_commits_without_importing_packages(self):
        def dist(name, commit=None, *, version='0.9.86'):
            return SimpleNamespace(metadata={'Name': name}, version=version,
                read_text=lambda _: json.dumps({'vcs_info': {'commit_id': commit}}))
        distributions = [dist('quant_platform_kit', 'bd8d06e50f88927eb525c2c585752435ab24492a'),
            dist('us-equity-strategies', 'wrong-pin'), dist('ib-insync')]
        output = io.StringIO()
        with patch('importlib.metadata.distributions', return_value=distributions), redirect_stdout(output):
            exec(PACKAGE_PROBE, {})
        self.assertEqual(json.loads(output.getvalue())['dependency_pins'],
            dict(qpk='MATCHED', ues='MISMATCHED', hes='MISSING', sdk='MATCHED'))
        distributions.append(distributions[0])
        output = io.StringIO()
        with patch('importlib.metadata.distributions', return_value=distributions), redirect_stdout(output):
            exec(PACKAGE_PROBE, {})
        self.assertEqual(json.loads(output.getvalue())['dependency_pins']['qpk'], 'AMBIGUOUS')

    def test_preflight_transport_is_small_and_uses_only_metadata_program(self):
        out, _ = self.inspect()
        source = (ROOT / 'scripts/pilot_runtime_preflight.py').read_text()
        program = preflight_program('synthetic-gateway', source)
        self.assertLess(len(program.encode()), 16384)
        self.assertNotIn('read_native_cash', program)
        with tempfile.TemporaryDirectory() as folder:
            key = Path(folder) / 'key'; key.touch(mode=0o600)
            env = dict(GCP_PROJECT_ID='synthetic-project', GCE_INSTANCE_NAME='synthetic-vm',
                GCE_ZONE='us-central1-a', GCE_USER='synthetic', IB_GATEWAY_CONTAINER_NAME='synthetic-gateway',
                IB_GATEWAY_MODE='live', SSH_KEY_FILE=str(key), RUNTIME_PREFLIGHT='true')
            output = io.StringIO()
            with patch.dict(os.environ, env, clear=True), \
                    patch('scripts.run_native_cash_ssh.subprocess.run', return_value=SimpleNamespace(returncode=0, stdout=json.dumps(out))), \
                    patch('scripts.run_native_cash_ssh.remote_program') as native, redirect_stdout(output):
                self.assertEqual(transport_main(), 0)
            native.assert_not_called()
            self.assertEqual(json.loads(output.getvalue()), out)
            for update in (dict(SAVED_CAPTURE_ID='saved'), dict(SAVED_EVIDENCE_SHA256='a'*64), dict(RETAIN_SAVED_ON_HOST='true')):
                with patch.dict(os.environ, {**env, **update}, clear=True), \
                        patch('scripts.run_native_cash_ssh.subprocess.run') as child, redirect_stdout(io.StringIO()):
                    self.assertEqual(transport_main(), 1)
                child.assert_not_called()


class ImageAccessTests(unittest.TestCase):
    image = 'us-central1-docker.pkg.dev/synthetic-project/repository/runtime@' + BASE_DIGEST

    class Response(io.BytesIO):
        def __init__(self, body, headers=None):
            super().__init__(body)
            self.headers = headers or {}
            self.status = 200

    def token(self):
        return self.Response(b'{"access_token":"synthetic-token"}', {'Metadata-Flavor': 'Google'})

    def test_manifest_bytes_are_verified_without_pull_or_launch(self):
        body = b'{"synthetic":"manifest"}'
        digest = 'sha256:' + hashlib.sha256(body).hexdigest()
        calls = []

        def open_url(request):
            calls.append(request)
            return self.token() if len(calls) == 1 else self.Response(body, {'Docker-Content-Digest': digest})

        with patch('scripts.pilot_runtime_preflight.BASE_DIGEST', digest):
            out = image_access(self.image.split('@')[0] + '@' + digest, open_url=open_url)
            self.assertTrue(valid_image_result(out))
        self.assertEqual(out['reason'], 'manifest_verified')
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0].full_url, 'http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token')
        self.assertTrue(calls[1].full_url.startswith('https://us-central1-docker.pkg.dev/v2/'))
        self.assertTrue(calls[1].get_header('Authorization').startswith('Basic '))
        self.assertNotIn('synthetic-token', json.dumps(out))
        for key in ('image_pull_attempted', 'runtime_started', 'broker_called', 'configuration_changed'):
            self.assertIs(out[key], False)

    def test_denial_stops_after_one_manifest_request_and_hides_resource(self):
        calls = []

        def open_url(request):
            calls.append(request)
            if len(calls) == 1:
                return self.token()
            raise urllib.error.HTTPError(request.full_url, 403, 'private-error', {},
                io.BytesIO(b'artifactregistry.repositories.downloadArtifacts denied on private-resource'))

        out = image_access(self.image, open_url=open_url)
        self.assertTrue(valid_image_result(out))
        self.assertEqual(out['reason'], 'registry_access_denied')
        self.assertEqual(out['denial_reason'], 'artifact_download_permission')
        self.assertEqual(len(calls), 2)
        self.assertNotIn('private-resource', json.dumps(out))

    def test_invalid_bindings_never_request_a_token(self):
        for image in (self.image.replace('us-central1-docker.pkg.dev', 'evil.example'),
                self.image.replace(BASE_DIGEST, 'latest'), self.image.replace('/runtime@', '/../runtime@'),
                self.image.replace('sha256:7', 'sha256:8')):
            out = image_access(image, open_url=lambda _: self.fail('network called'))
            self.assertEqual(out['reason'], 'image_binding_invalid')
            self.assertTrue(valid_image_result(out))

    def test_missing_metadata_header_cannot_supply_credentials(self):
        calls = []

        def open_url(request):
            calls.append(request)
            return self.Response(b'{"access_token":"untrusted"}')

        out = image_access(self.image, open_url=open_url)
        self.assertEqual(out['reason'], 'vm_token_unavailable')
        self.assertEqual(len(calls), 1)

    def test_wrong_manifest_digest_stays_unverified(self):
        calls = []

        def open_url(request):
            calls.append(request)
            return self.token() if len(calls) == 1 else self.Response(b'wrong-manifest')

        out = image_access(self.image, open_url=open_url)
        self.assertEqual(out['reason'], 'manifest_digest_mismatch')
        self.assertTrue(valid_image_result(out))

    def test_redirect_handler_never_forwards_credentials(self):
        from scripts.pilot_runtime_preflight import NoRedirect
        request = urllib.request.Request('https://us-central1-docker.pkg.dev', headers={'Authorization': 'Basic synthetic'})
        self.assertIsNone(NoRedirect().redirect_request(request, None, 302, 'redirect', {}, 'https://evil.example'))

    def test_transport_preserves_fixed_denial_without_entering_native_reader(self):
        out = image_result()
        out.update(reason='registry_access_denied', vm_token_obtained=True,
            manifest_http_status=403, denial_reason='artifact_download_permission')
        with tempfile.TemporaryDirectory() as folder:
            key = Path(folder) / 'key'; key.touch(mode=0o600)
            env = dict(GCP_PROJECT_ID='synthetic-project', GCE_INSTANCE_NAME='synthetic-vm',
                GCE_ZONE='us-central1-a', GCE_USER='synthetic', IB_GATEWAY_CONTAINER_NAME='synthetic-gateway',
                IB_GATEWAY_MODE='live', SSH_KEY_FILE=str(key), RUNTIME_IMAGE_ACCESS='true',
                PILOT_RUNTIME_BASE_IMAGE=self.image)
            output = io.StringIO()
            with patch.dict(os.environ, env, clear=True), \
                    patch('scripts.run_native_cash_ssh.subprocess.run', return_value=SimpleNamespace(returncode=0, stdout=json.dumps(out))), \
                    patch('scripts.run_native_cash_ssh.remote_program') as native, redirect_stdout(output):
                self.assertEqual(transport_main(), 1)
            native.assert_not_called()
            self.assertEqual(json.loads(output.getvalue()), out)
            with patch.dict(os.environ, {**env, 'RUNTIME_PREFLIGHT': 'true'}, clear=True), \
                    patch('scripts.run_native_cash_ssh.subprocess.run') as child, redirect_stdout(io.StringIO()):
                self.assertEqual(transport_main(), 1)
            child.assert_not_called()


if __name__ == '__main__':
    unittest.main()
