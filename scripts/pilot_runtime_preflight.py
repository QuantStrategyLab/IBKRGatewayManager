"""Inspect existing host/image/package metadata without starting a pilot."""
from datetime import datetime, timezone
import json
import platform
from pathlib import Path
import re
import shutil
import subprocess
import base64
import hashlib
import urllib.error
import urllib.request

CANDIDATE = '15427acb0ecc5e4c2450adf5276f90625a32e01a'
BASE_DIGEST = 'sha256:714c510974267e055d35dcb129a4ce2afc628b069daff1987127627d80573bd2'
PIN_STATES = {'UNKNOWN', 'MISSING', 'MATCHED', 'MISMATCHED', 'UNVERIFIED', 'AMBIGUOUS'}
REASONS = {'preflight_failed', 'request_invalid', 'container_metadata_failed',
           'image_metadata_failed', 'dependency_metadata_failed', 'host_resources_unavailable', 'metadata_observed'}
FALSE_FIELDS = ('runtime_ready', 'candidate_source_verified', 'broker_called',
                'strategy_computation_started', 'image_pull_attempted', 'configuration_changed')

# Distribution metadata only. -I -S -B skips site startup and bytecode writes;
# no broker, strategy or application package is imported.
PACKAGE_PROBE = r'''
import importlib.metadata as metadata, json, sys, sysconfig
paths = sorted(set(sysconfig.get_path(key) for key in ('purelib', 'platlib')))
expected = {'qpk': ('quant-platform-kit', 'bd8d06e50f88927eb525c2c585752435ab24492a'),
            'ues': ('us-equity-strategies', '4a3943883cd6b5bbfe32a559e56a91b40a81b7ce'),
            'hes': ('hk-equity-strategies', '709e5e1cde7841aed538d94eb26b552b46cb7806'),
            'sdk': ('ib-insync', '0.9.86')}
distributions = list(metadata.distributions(path=paths))
states = {}
for key, (name, pin) in expected.items():
    matches = [d for d in distributions if str(d.metadata.get('Name', '')).lower().replace('_', '-') == name]
    state = 'MISSING' if not matches else 'AMBIGUOUS' if len(matches) != 1 else 'UNVERIFIED'
    if len(matches) == 1:
        if key == 'sdk':
            state = 'MATCHED' if matches[0].version == pin else 'MISMATCHED'
        else:
            try:
                commit = json.loads(matches[0].read_text('direct_url.json') or '{}').get('vcs_info', {}).get('commit_id')
                state = ('MATCHED' if commit == pin else 'MISMATCHED') if isinstance(commit, str) else 'UNVERIFIED'
            except Exception:
                pass
    states[key] = state
print(json.dumps({'python_minor': '%s.%s' % sys.version_info[:2], 'dependency_pins': states}))
'''


def result():
    return dict(schema_version='ibkr.pilot_runtime_preflight.v1', status='unavailable', reason='preflight_failed',
        candidate=CANDIDATE, scope='EXISTING_GATEWAY_HOST_METADATA_ONLY',
        observed_at=datetime.now(timezone.utc).isoformat(), gateway_container_running=None,
        candidate_image_label_count=None, python_minor=None,
        dependency_pins=dict.fromkeys(('qpk', 'ues', 'hes', 'sdk'), 'UNKNOWN'),
        host_memory_available_mib=None, host_disk_free_mib=None, host_architecture=None,
        **dict.fromkeys(FALSE_FIELDS, False))


def command(args):
    child = subprocess.run(args, capture_output=True, text=True, timeout=12)
    if child.returncode or len(child.stdout.encode('utf-8')) > 1_000_000:
        raise ValueError()
    return child.stdout


def package_metadata_valid(value):
    return (isinstance(value, dict) and set(value) == {'python_minor', 'dependency_pins'}
        and isinstance(value['python_minor'], str) and re.fullmatch(r'[0-9]{1,2}\.[0-9]{1,2}', value['python_minor'])
        and isinstance(value['dependency_pins'], dict) and set(value['dependency_pins']) == {'qpk', 'ues', 'hes', 'sdk'}
        and all(isinstance(v, str) and v in PIN_STATES for v in value['dependency_pins'].values()))


def observe(container, *, run=command):
    out = result()
    if not isinstance(container, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', container):
        out['reason'] = 'request_invalid'
        return out
    stage = 'container_metadata_failed'
    try:
        running = json.loads(run(('sudo', '-n', 'docker', 'inspect', '--format', '{{json .State.Running}}', container)))
        if type(running) is not bool:
            raise ValueError()
        out['gateway_container_running'] = running
        stage = 'image_metadata_failed'
        images = set(run(('sudo', '-n', 'docker', 'image', 'ls', '--no-trunc', '--quiet')).splitlines())
        if len(images) > 64 or any(not re.fullmatch(r'sha256:[0-9a-f]{64}', value) for value in images):
            raise ValueError()
        labels = []
        if images:
            lines = run(('sudo', '-n', 'docker', 'image', 'inspect', '--format', '{{json .Config.Labels}}', *sorted(images))).splitlines()
            if len(lines) != len(images):
                raise ValueError()
            labels = [json.loads(line) for line in lines]
            if any(row is not None and not isinstance(row, dict) for row in labels):
                raise ValueError()
        out['candidate_image_label_count'] = sum(
            {row[key] for key in ('org.opencontainers.image.revision', 'commit-sha') if key in row} == {CANDIDATE}
            for row in labels if row is not None)
        stage = 'dependency_metadata_failed'
        if running:
            packages = json.loads(run(('sudo', '-n', 'docker', 'exec', container, 'python3', '-I', '-S', '-B', '-c', PACKAGE_PROBE)))
            if not package_metadata_valid(packages):
                raise ValueError()
            out.update(packages)
        stage = 'host_resources_unavailable'
        memory = re.search(r'^MemAvailable:\s*([0-9]+) kB$', Path('/proc/meminfo').read_text(), re.M)
        if memory is None:
            raise ValueError()
        out.update(host_memory_available_mib=int(memory[1]) // 1024,
            host_disk_free_mib=shutil.disk_usage(Path.home()).free // (1024 * 1024),
            host_architecture=platform.machine() if platform.machine() in {'x86_64', 'aarch64'} else 'other',
            status='observed', reason='metadata_observed')
    except Exception:
        out['reason'] = stage
    return out


def valid_result(value):
    if not isinstance(value, dict) or set(value) != set(result()):
        return False
    if (value['schema_version'] != 'ibkr.pilot_runtime_preflight.v1' or value['candidate'] != CANDIDATE
            or value['scope'] != 'EXISTING_GATEWAY_HOST_METADATA_ONLY'
            or not isinstance(value['status'], str) or value['status'] not in {'observed', 'unavailable'}
            or not isinstance(value['reason'], str) or value['reason'] not in REASONS
            or any(value[key] is not False for key in FALSE_FIELDS)
            or value['gateway_container_running'] is not None and type(value['gateway_container_running']) is not bool
            or value['host_architecture'] not in (None, 'x86_64', 'aarch64', 'other')):
        return False
    for key in ('candidate_image_label_count', 'host_memory_available_mib', 'host_disk_free_mib'):
        if value[key] is not None and (type(value[key]) is not int or not 0 <= value[key] < 2**50):
            return False
    if value['candidate_image_label_count'] is not None and value['candidate_image_label_count'] > 64:
        return False
    if not isinstance(value['observed_at'], str):
        return False
    try:
        if datetime.fromisoformat(value['observed_at']).utcoffset().total_seconds() != 0:
            return False
    except (ValueError, AttributeError):
        return False
    packages = {'python_minor': value['python_minor'], 'dependency_pins': value['dependency_pins']}
    if value['python_minor'] is None:
        packages['python_minor'] = '0.0'
    if not package_metadata_valid(packages):
        return False
    if value['status'] == 'observed':
        return (value['reason'] == 'metadata_observed' and value['gateway_container_running'] is not None
            and all(value[key] is not None for key in ('candidate_image_label_count',
                'host_memory_available_mib', 'host_disk_free_mib', 'host_architecture'))
            and (not value['gateway_container_running'] or value['python_minor'] is not None))
    return value['reason'] != 'metadata_observed'


def image_result():
    return dict(schema_version='ibkr.pilot_image_access.v1', status='unavailable', reason='image_binding_invalid',
        observed_at=datetime.now(timezone.utc).isoformat(), image_digest=BASE_DIGEST,
        vm_token_obtained=False, manifest_http_status=None, manifest_digest_verified=False,
        denial_reason=None, image_pull_attempted=False, runtime_started=False,
        broker_called=False, configuration_changed=False)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def read_request(request):
    # Tokens never pass through a proxy or an HTTP redirect.
    return urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect()).open(request, timeout=8)


def image_access(image, *, open_url=read_request):
    out = image_result()
    binding = re.fullmatch(r'(us-central1-docker\.pkg\.dev)/([a-z][a-z0-9-]{4,28}[a-z0-9]/[a-z0-9._/-]+)@'
        + re.escape(BASE_DIGEST), image) if isinstance(image, str) else None
    if binding is None or any(part in ('', '.', '..') for part in binding[2].split('/')) or len(binding[2].split('/')) < 3:
        return out
    stage = 'vm_token_unavailable'
    try:
        request = urllib.request.Request('http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token',
            headers={'Metadata-Flavor': 'Google'})
        with open_url(request) as response:
            if response.headers.get('Metadata-Flavor') != 'Google':
                raise ValueError()
            body = response.read(65537)
        if len(body) > 65536:
            raise ValueError()
        token = json.loads(body).get('access_token')
        if not isinstance(token, str) or not 0 < len(token) <= 8192:
            raise ValueError()
        out['vm_token_obtained'] = True
        stage = 'manifest_read_failed'
        authorization = base64.b64encode(('oauth2accesstoken:' + token).encode()).decode('ascii')
        request = urllib.request.Request('https://' + binding[1] + '/v2/' + binding[2] + '/manifests/' + BASE_DIGEST,
            headers={'Authorization': 'Basic ' + authorization,
                'Accept': 'application/vnd.docker.distribution.manifest.v2+json, application/vnd.oci.image.manifest.v1+json, application/vnd.oci.image.index.v1+json, application/vnd.docker.distribution.manifest.list.v2+json'})
        try:
            with open_url(request) as response:
                out['manifest_http_status'] = response.status
                body = response.read(4_000_001)
                digest = response.headers.get('Docker-Content-Digest')
        except urllib.error.HTTPError as error:
            out['manifest_http_status'] = error.code
            if error.code in (401, 403):
                detail = error.read(4096).decode('utf-8', errors='replace')
                out.update(reason='registry_access_denied', denial_reason='insufficient_vm_scopes'
                    if 'insufficient authentication scopes' in detail else 'artifact_download_permission'
                    if 'artifactregistry.repositories.downloadArtifacts' in detail else 'unclassified')
            else:
                out['reason'] = 'registry_not_found' if error.code == 404 else stage
            return out
        stage = 'manifest_digest_mismatch'
        if (out['manifest_http_status'] != 200 or not 0 < len(body) <= 4_000_000
                or 'sha256:' + hashlib.sha256(body).hexdigest() != BASE_DIGEST
                or digest is not None and digest != BASE_DIGEST):
            raise ValueError()
        out.update(status='observed', reason='manifest_verified', manifest_digest_verified=True)
    except Exception:
        out['reason'] = stage
    return out


def valid_image_result(value):
    if not isinstance(value, dict) or set(value) != set(image_result()):
        return False
    if (value['schema_version'] != 'ibkr.pilot_image_access.v1' or value['image_digest'] != BASE_DIGEST
            or value['status'] not in ('observed', 'unavailable')
            or value['reason'] not in ('image_binding_invalid', 'vm_token_unavailable', 'manifest_read_failed',
                'registry_access_denied', 'registry_not_found', 'manifest_digest_mismatch', 'manifest_verified')
            or value['denial_reason'] not in (None, 'insufficient_vm_scopes', 'artifact_download_permission', 'unclassified')
            or any(value[key] is not False for key in ('image_pull_attempted', 'runtime_started', 'broker_called', 'configuration_changed'))
            or any(type(value[key]) is not bool for key in ('vm_token_obtained', 'manifest_digest_verified'))):
        return False
    code = value['manifest_http_status']
    if code is not None and (type(code) is not int or not 100 <= code <= 599):
        return False
    try:
        if datetime.fromisoformat(value['observed_at']).utcoffset().total_seconds() != 0:
            return False
    except (TypeError, ValueError, AttributeError):
        return False
    if value['status'] == 'observed':
        return (value['reason'] == 'manifest_verified' and value['vm_token_obtained'] is True
            and code == 200 and value['manifest_digest_verified'] is True and value['denial_reason'] is None)
    return (value['reason'] != 'manifest_verified' and value['manifest_digest_verified'] is False
        and (value['reason'] != 'registry_access_denied' or code in (401, 403) and value['denial_reason'] is not None))
