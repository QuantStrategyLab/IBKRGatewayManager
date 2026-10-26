"""Use the existing protected target/SSH identity for one native cash inventory.

Private request binding travels only on SSH stdin; raw values never leave Linux.
The helper never creates keys, edits SSH metadata, installs or restarts software.
"""
import base64
import gzip
import hashlib
import inspect
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import tempfile
from uuid import UUID, uuid4

from scripts.read_native_cash import SCHEDULE_TAGS, TAGS, request_value, result, saved_result
from scripts.pilot_runtime_preflight import valid_result as valid_preflight_result, valid_image_result

RETENTION_REASONS=frozenset({'retention_binding_invalid','retention_directory_invalid',
    'retention_file_invalid','retention_digest_mismatch','retention_source_unavailable',
    'retention_copy_unavailable','retention_archive_invalid','retention_readback_failed',
    'retention_failed','retention_permission_denied','retention_transport_timeout'})


def retain_saved_on_host(container, request, save_bytes):
    """Copy one verified observation onto the existing Linux host, never SSH stdout."""
    import hashlib
    import io
    import os
    from pathlib import Path
    import re
    import stat
    import subprocess
    import tarfile
    from uuid import UUID

    capture, expected = request['capture_id'], request['evidence_sha256']
    if str(UUID(capture)) != capture or not re.fullmatch(r'[0-9a-f]{64}', expected):
        raise ValueError('retention_binding_invalid')
    root = Path.home()/'.qsl-native-cash-evidence'
    root.mkdir(mode=0o700, exist_ok=True)
    def private_directory(path):
        info=path.lstat()
        if not stat.S_ISDIR(info.st_mode) or stat.S_IMODE(info.st_mode)!=0o700 or info.st_uid!=os.geteuid():
            raise ValueError('retention_directory_invalid')
    private_directory(root)
    destination=root/capture
    if destination.exists() or destination.is_symlink():
        private_directory(destination)
        fd=os.open(destination/'observation.json',os.O_RDONLY|os.O_NOFOLLOW)
        with os.fdopen(fd,'rb') as stream:
            info=os.fstat(stream.fileno())
            if (not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode)!=0o600
                    or info.st_uid!=os.geteuid() or not 0<info.st_size<=4_000_000):
                raise ValueError('retention_file_invalid')
            existing=stream.read(4_000_001)
        if hashlib.sha256(existing).hexdigest()!=expected:
            raise ValueError('retention_digest_mismatch')
        return expected
    # Only a private basename is returned to this host process. Neither the
    # basename nor the captured archive/body is forwarded to the SSH caller.
    found=subprocess.run(['sudo','-n','docker','exec',container,'find','/tmp','-maxdepth','2',
        '-path','/tmp/qsl-native-cash-'+capture+'-*/observation.json','-type','f'],
        capture_output=True,timeout=20)
    names=found.stdout.decode('ascii').splitlines()
    if (found.returncode or len(names)!=1 or not re.fullmatch(
            r'/tmp/qsl-native-cash-'+re.escape(capture)+r'-[A-Za-z0-9_-]+/observation.json',names[0])):
        raise ValueError('retention_source_unavailable')
    copied=subprocess.run(['sudo','-n','docker','cp',container+':'+names[0],'-'],
        capture_output=True,timeout=20)
    if copied.returncode or len(copied.stdout)>4_100_000:
        raise ValueError('retention_copy_unavailable')
    with tarfile.open(fileobj=io.BytesIO(copied.stdout),mode='r:') as archive:
        members=archive.getmembers()
        if (len(members)!=1 or not members[0].isfile() or members[0].name!='observation.json'
                or not 0<members[0].size<=4_000_000):
            raise ValueError('retention_archive_invalid')
        with archive.extractfile(members[0]) as stream:
            body=stream.read(4_000_001)
    if hashlib.sha256(body).hexdigest()!=expected:
        raise ValueError('retention_digest_mismatch')
    destination.mkdir(mode=0o700)
    if save_bytes(destination,body)!=expected:
        raise ValueError('retention_readback_failed')
    return expected


def remote_program(container, collector, request, *, retain_on_host=False):
    """Keep the SSH stdin envelope small; verify exact public source on Linux."""
    body=collector.encode()
    encoded=base64.b64encode(gzip.compress(body,mtime=0)).decode('ascii')
    digest=hashlib.sha256(body).hexdigest()
    if retain_on_host and set(request)!={'account_ids','capture_id','evidence_sha256'}:
        raise ValueError('retention_requires_saved_read')
    return (
        "import subprocess,json,sys,base64,gzip,hashlib\n"
        "code=gzip.decompress(base64.b64decode("+repr(encoded)+"))\n"
        "if hashlib.sha256(code).hexdigest()!="+repr(digest)+": raise ValueError('public_source_digest_mismatch')\n"
        +inspect.getsource(retain_saved_on_host)+"\n"
        "p=subprocess.run(['sudo','-n','docker','exec','-i',"+repr(container)+
        ",'python3','-c',code.decode('utf-8')],input="+repr(json.dumps(request).encode())+
        ",capture_output=True,timeout="+str(30 if retain_on_host else 65)+")\n"
        "try:\n r=json.loads(p.stdout)\nexcept Exception:\n r={'status':'unavailable','reason':'native_response_invalid'}\n"
        "if "+repr(retain_on_host)+":\n"
        " r['existing_host_retention_status']='UNAVAILABLE'\n"
        " r['existing_host_retention_reason']='retention_failed'\n"
        " try:\n"
        "  request="+repr(request)+"\n"
        "  if (r.get('schema_version')!='ibkr.saved_native_cash_inventory_result.v1' or r.get('status')!='observed' or not r.get('account_matched') or not r.get('saved_readback_verified') or r.get('capture_id')!=request['capture_id'] or r.get('evidence_sha256')!=request['evidence_sha256']): raise ValueError()\n"
        "  ns={'__name__':'qsl_private_host_copy'}\n"
        "  exec(compile(code.decode('utf-8'),'<reviewed-collector>','exec'),ns)\n"
        "  host_digest=retain_saved_on_host("+repr(container)+",request,ns['save_private_bytes'])\n"
        "  r.update(existing_host_retention_status='HOST_DISK_COPY_VERIFIED',existing_host_readback_verified=True,existing_host_evidence_sha256=host_digest,existing_host_retention_reason=None)\n"
        " except Exception as error:\n"
        "  reason=str(error)\n"
        "  r['existing_host_retention_reason']=reason if reason in "+repr(sorted(RETENTION_REASONS))+" else ('retention_permission_denied' if isinstance(error,PermissionError) else 'retention_transport_timeout' if isinstance(error,subprocess.TimeoutExpired) else 'retention_failed')\n"
        "print(json.dumps(r,sort_keys=True))\n"
    )


def preflight_program(container, collector):
    body = collector.encode()
    encoded = base64.b64encode(gzip.compress(body, mtime=0)).decode('ascii')
    return ("import json,base64,gzip,hashlib\n"
        "code=gzip.decompress(base64.b64decode(" + repr(encoded) + "))\n"
        "if hashlib.sha256(code).hexdigest()!=" + repr(hashlib.sha256(body).hexdigest()) + ": raise ValueError('public_source_digest_mismatch')\n"
        "ns={'__name__':'qsl_pilot_preflight'}\nexec(compile(code.decode(),'<reviewed-preflight>','exec'),ns)\n"
        "print(json.dumps(ns['observe'](" + repr(container) + "),sort_keys=True))\n")


def main():
    out = dict(status="unavailable", reason="transport_failed")
    retain_on_host=False
    try:
        env = os.environ
        patterns = {
            "GCP_PROJECT_ID":r"[a-z][a-z0-9-]{4,28}[a-z0-9]",
            "GCE_INSTANCE_NAME":r"[a-z][a-z0-9-]{0,62}",
            "GCE_ZONE":r"[a-z]+(?:-[a-z]+)*[0-9]+-[a-z]",
            "GCE_USER":r"[A-Za-z_][A-Za-z0-9_.-]*",
            "IB_GATEWAY_CONTAINER_NAME":r"[A-Za-z0-9][A-Za-z0-9_.-]*",
        }
        if any(not re.fullmatch(pattern,env.get(name,"")) for name,pattern in patterns.items()):
            raise ValueError()
        if env.get("IB_GATEWAY_MODE") not in ("live","paper"):
            raise ValueError()
        capture_id, digest = env.get('SAVED_CAPTURE_ID',''), env.get('SAVED_EVIDENCE_SHA256','')
        if env.get('RUNTIME_PREFLIGHT','false') not in ('true','false'):raise ValueError()
        preflight=env.get('RUNTIME_PREFLIGHT','false')=='true'
        if env.get('RUNTIME_IMAGE_ACCESS','false') not in ('true','false'):raise ValueError()
        image_access=env.get('RUNTIME_IMAGE_ACCESS','false')=='true'
        if preflight and image_access:raise ValueError()
        preflight=preflight or image_access
        if env.get('RETAIN_SAVED_ON_HOST','false') not in ('true','false'):raise ValueError()
        retain_on_host=env.get('RETAIN_SAVED_ON_HOST','false')=='true'
        if preflight and (capture_id or digest or retain_on_host):raise ValueError()
        if retain_on_host and (not capture_id or not digest):raise ValueError()
        if not preflight:
            request = request_value(dict(account_ids=json.loads(env["EXPECTED_ACCOUNT_SELECTOR_JSON"]),
                port=4001 if env["IB_GATEWAY_MODE"]=="live" else 4002,capture_id=capture_id or str(uuid4())))
            if capture_id or digest:
                if not capture_id or not re.fullmatch(r'[0-9a-f]{64}',digest):raise ValueError()
                request.pop('port')
                request['evidence_sha256']=digest
        key=Path(env["SSH_KEY_FILE"])
        if not key.is_file() or key.stat().st_mode & 0o077:
            raise ValueError()
        # Code argument is public reviewed source. All binding values go on stdin.
        if preflight:
            collector=Path(__file__).with_name('pilot_runtime_preflight.py').read_text()
            if image_access:
                collector+='\nobserve=image_access\n'
            remote=preflight_program(env.get('PILOT_RUNTIME_BASE_IMAGE','') if image_access else env['IB_GATEWAY_CONTAINER_NAME'],collector)
        else:
            collector=Path(__file__).with_name("read_native_cash.py").read_text()
            remote=remote_program(env["IB_GATEWAY_CONTAINER_NAME"],collector,request,retain_on_host=retain_on_host)
            print('NATIVE_CASH_CAPTURE_ID='+request['capture_id'],flush=True)
        proxy=shlex.join(['gcloud','compute','start-iap-tunnel',env['GCE_INSTANCE_NAME'],'22',
            '--listen-on-stdin','--project='+env['GCP_PROJECT_ID'],'--zone='+env['GCE_ZONE'],
            '--quiet','--verbosity=error'])
        with tempfile.TemporaryDirectory(prefix='gateway-native-ssh-') as folder:
            known=Path(folder)/'known_hosts';known.touch(mode=0o600)
            args=['ssh','-i',str(key),'-o','IdentitiesOnly=yes','-o','BatchMode=yes',
                '-o','ControlMaster=no','-o','ControlPath=none','-o','ConnectionAttempts=1',
                '-o','ConnectTimeout=20','-o','StrictHostKeyChecking=accept-new',
                '-o','UserKnownHostsFile='+str(known),'-o','HostKeyAlias=gateway-native-target',
                '-o','ProxyCommand='+proxy,env['GCE_USER']+'@gateway-native-target','python3 -']
            p=subprocess.run(args,input=remote.encode(),capture_output=True,timeout=95)
        value=json.loads(p.stdout)
        # Strict shape prevents raw SDK output or a transport page becoming logs.
        validator=valid_image_result if image_access else valid_preflight_result if preflight else valid_safe_result
        if p.returncode or not validator(value):
            raise ValueError()
        out=value
    except subprocess.TimeoutExpired:
        out['reason']='transport_timeout'
    except Exception:
        pass
    print(json.dumps(out,sort_keys=True))
    return 0 if out['status']=='observed' and (not retain_on_host or out.get('existing_host_readback_verified') is True) else 1


def valid_safe_result(value):
    if isinstance(value,dict) and value.get('schema_version')=='ibkr.saved_native_cash_inventory_result.v1':
        return valid_saved_result(value)
    if not isinstance(value,dict) or set(value)!=set(result()):
        return False
    if value['schema_version'] != 'ibkr.native_cash_inventory_result.v1':
        return False
    if value['reason'] not in {'read_failed','request_invalid','existing_sdk_not_supported',
            'outbound_message_not_allowed','native_field_invalid','native_response_too_large',
            'physical_account_mismatch','account_download_end_missing','account_reset_in_progress',
            'open_order_end_missing','private_readback_failed','native_read_timeout',
            'native_read_failed','native_read_saved_and_readback_verified'}:
        return False
    if value['status'] not in ('observed','unavailable') or value['account_ready'] not in ('TRUE','FALSE','UNKNOWN'):
        return False
    for key in ('native_connection_ready','account_matched','account_download_end_observed',
                'api_open_orders_end_observed','private_evidence_readback_verified',
                'durable_cloud_store_verified','complete_cash_obligations_verified',
                'spendable_cash_verified','execution_authorized','production_configuration_changed'):
        if type(value[key]) is not bool:return False
    for key in ('durable_cloud_store_verified','complete_cash_obligations_verified',
                'spendable_cash_verified','execution_authorized','production_configuration_changed'):
        if value[key] is not False:return False
    for key in ('api_selected_account_order_count','native_field_name_count','settled_exact_usd_rows',
                'settled_exact_base_rows','other_settled_tag_rows','unbound_order_rows'):
        if value[key] is not None and (type(value[key]) is not int or not 0<=value[key]<=5000):return False
    if value['capture_id'] is not None:
        try:
            if str(UUID(value['capture_id'])) != value['capture_id']:return False
        except (ValueError, TypeError, AttributeError):return False
    if not isinstance(value['started_at'],str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}T[0-9:.]+\+00:00',value['started_at']):return False
    if value['evidence_sha256'] is not None and not re.fullmatch(r'[0-9a-f]{64}',value['evidence_sha256']):return False
    if value['private_evidence_scope']!='EXISTING_GATEWAY_CONTAINER_ONLY':return False
    if value['status']=='observed' and (
            value['reason']!='native_read_saved_and_readback_verified'
            or value['capture_id'] is None or value['evidence_sha256'] is None
            or value['account_ready']=='FALSE'
            or not all(value[key] for key in ('native_connection_ready','account_matched',
                'account_download_end_observed','api_open_orders_end_observed',
                'private_evidence_readback_verified'))):return False
    if (not isinstance(value['native_error_codes'],list) or len(value['native_error_codes'])>100
            or any(type(code) is not int or not 0<=code<=99999 for code in value['native_error_codes'])):return False
    inventory=value['settlement_schedule_inventory']
    if not isinstance(inventory,list) or len(inventory)>5000:return False
    for field in inventory:
        if (not isinstance(field,dict) or set(field)!={'tag','currency','row_count','raw_rows','value_shapes'}
                or field['tag'] not in SCHEDULE_TAGS or not isinstance(field['currency'],str)
                or not re.fullmatch(r'(?:[A-Z]{3}|BASE|)',field['currency'])
                or type(field['row_count']) is not int or type(field['raw_rows']) is not int
                or not 0<=field['raw_rows']<=field['row_count']<=5000
                or not isinstance(field['value_shapes'],list) or len(field['value_shapes'])>10
                or any(not isinstance(shape,str) or len(shape)>256
                    or re.search(r'[^DAWX{}\[\]():;,.=+_/|\-\"\x27]',shape)
                    for shape in field['value_shapes'])):return False
    return (isinstance(value['usd_field_states'],dict) and set(value['usd_field_states'])==set(TAGS)
            and all(state in ('OBSERVED','MISSING','INVALID','AMBIGUOUS') for state in value['usd_field_states'].values()))


def valid_saved_result(value):
    if set(value)!=set(saved_result()) or value['status'] not in ('observed','unavailable'):
        return False
    if value['reason'] not in ('saved_evidence_invalid','saved_inventory_readback_verified','native_read_failed'):
        return False
    for key in ('account_matched','saved_readback_verified','native_connection_attempted',
                'spendable_cash_verified','complete_cash_obligations_verified',
                'execution_authorized','production_configuration_changed',
                'existing_host_readback_verified','durable_cloud_store_verified'):
        if type(value[key]) is not bool:return False
    for key in ('native_connection_attempted','spendable_cash_verified','complete_cash_obligations_verified',
                'execution_authorized','production_configuration_changed','durable_cloud_store_verified'):
        if value[key] is not False:return False
    try:
        if value['capture_id'] is not None and str(UUID(value['capture_id']))!=value['capture_id']:return False
    except (ValueError,TypeError,AttributeError):return False
    if (value['source_started_at'] is not None and (not isinstance(value['source_started_at'],str)
            or not re.fullmatch(r'\d{4}-\d{2}-\d{2}T[0-9:.]+\+00:00',value['source_started_at']))):return False
    if value['evidence_sha256'] is not None and not re.fullmatch(r'[0-9a-f]{64}',value['evidence_sha256']):return False
    if value['status']=='observed' and (value['reason']!='saved_inventory_readback_verified'
            or not value['account_matched'] or not value['saved_readback_verified']
            or any(value[key] is None for key in ('capture_id','source_started_at','evidence_sha256'))):return False
    if not isinstance(value['settled_tag_inventory'],list) or len(value['settled_tag_inventory'])>5000:return False
    for field in value['settled_tag_inventory']:
        if (not isinstance(field,dict) or set(field)!={'tag','currency','row_count','numeric_rows'}
                or not isinstance(field['tag'],str) or 'settled' not in field['tag'].lower()
                or not re.fullmatch(r'[A-Za-z$][A-Za-z0-9$_.:-]{0,63}',field['tag'])
                or not isinstance(field['currency'],str) or not re.fullmatch(r'(?:[A-Z]{3}|BASE|)',field['currency'])
                or type(field['row_count']) is not int or type(field['numeric_rows']) is not int
                or not 0<=field['numeric_rows']<=field['row_count']<=5000):return False
    if value['existing_host_retention_status'] not in ('NOT_REQUESTED','UNAVAILABLE','HOST_DISK_COPY_VERIFIED'):return False
    if value['existing_host_retention_status']=='HOST_DISK_COPY_VERIFIED':
        if (not value['existing_host_readback_verified'] or value['evidence_sha256'] is None
                or value['existing_host_evidence_sha256']!=value['evidence_sha256']
                or value['existing_host_retention_reason'] is not None):return False
    elif value['existing_host_readback_verified'] or value['existing_host_evidence_sha256'] is not None:return False
    if value['existing_host_retention_status']=='UNAVAILABLE':
        if value['existing_host_retention_reason'] not in RETENTION_REASONS:return False
    elif value['existing_host_retention_reason'] is not None:return False
    return (value['settlement_structure'] is None and value['status']=='unavailable'
            or valid_schedule_structure(value['settlement_structure']))


def valid_schedule_structure(value):
    if (not isinstance(value,dict) or set(value)!={'scope','fields','relationships',
            'date_key_semantics_verified','settled_cash_equivalence_verified','current_settlement_selected'}
            or value['scope']!='SAVED_SAME_CAPTURE_SYNTAX_AND_ARITHMETIC_ONLY'
            or any(value[key] is not False for key in ('date_key_semantics_verified',
                'settled_cash_equivalence_verified','current_settlement_selected'))
            or not isinstance(value['fields'],list) or len(value['fields'])>5000
            or not isinstance(value['relationships'],list) or len(value['relationships'])>5000):return False
    seen=set()
    for field in value['fields']:
        if (not isinstance(field,dict) or set(field)!={'tag','currency','row_count','syntax_status','key_shape'}
                or field['tag'] not in SCHEDULE_TAGS or not isinstance(field['currency'],str)
                or not re.fullmatch(r'(?:[A-Z]{3}|BASE|)',field['currency'])
                or type(field['row_count']) is not int or not 0<field['row_count']<=5000
                or field['syntax_status'] not in ('SINGLE_PAIR','REPEATED_CONSISTENT_PAIR','RAW_NOT_PRESERVED','EMPTY',
                    'UNSUPPORTED_FORMAT','INVALID_NUMBER','AMBIGUOUS_ROWS')
                or field['key_shape'] not in ('UNKNOWN','ZERO_KEY','INTEGER_KEY',
                    'CALENDAR_DATE_SHAPED','INVALID_CALENDAR_DATE_SHAPED')):return False
        key=(field['tag'],field['currency'])
        if key in seen:return False
        seen.add(key)
    currencies=[]
    for row in value['relationships']:
        if (not isinstance(row,dict) or set(row)!={'currency','segment_consistency','same_capture_ledger_relation'}
                or not isinstance(row['currency'],str) or not re.fullmatch(r'(?:[A-Z]{3}|BASE|)',row['currency'])
                or row['segment_consistency'] not in ('INCOMPLETE_OR_INVALID','KEYS_DIFFER',
                    'SAME_KEY_TOTAL_EQUALS_SEGMENTS','SAME_KEY_TOTAL_DIFFERS')
                or row['same_capture_ledger_relation'] not in ('UNKNOWN','EQUAL','DIFFERENT')):return False
        currencies.append(row['currency'])
    return len(currencies)==len(set(currencies)) and set(currencies)=={currency for _,currency in seen}


if __name__=='__main__':
    raise SystemExit(main())
