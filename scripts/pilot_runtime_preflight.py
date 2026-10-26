"""Inspect existing host/image/package metadata without starting a pilot."""
from datetime import datetime, timezone
import json
import platform
from pathlib import Path
import re
import shutil
import subprocess

CANDIDATE = '15427acb0ecc5e4c2450adf5276f90625a32e01a'
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
