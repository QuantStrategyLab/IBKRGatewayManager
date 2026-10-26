"""Use the existing protected target/SSH identity for one native cash inventory.

Private request binding travels only on SSH stdin; raw values never leave Linux.
The helper never creates keys, edits SSH metadata, installs or restarts software.
"""
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


def main():
    out = dict(status="unavailable", reason="transport_failed")
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
        request = request_value(dict(account_ids=json.loads(env["EXPECTED_ACCOUNT_SELECTOR_JSON"]),
            port=4001 if env["IB_GATEWAY_MODE"]=="live" else 4002,capture_id=capture_id or str(uuid4())))
        if capture_id or digest:
            if not capture_id or not re.fullmatch(r'[0-9a-f]{64}',digest):raise ValueError()
            request.pop('port')
            request['evidence_sha256']=digest
        key=Path(env["SSH_KEY_FILE"])
        if not key.is_file() or key.stat().st_mode & 0o077:
            raise ValueError()
        collector=Path(__file__).with_name("read_native_cash.py").read_text()
        # Code argument is public reviewed source. All binding values go on stdin.
        remote = (
            "import subprocess,json,sys\n"
            "p=subprocess.run(['sudo','-n','docker','exec','-i',"+repr(env["IB_GATEWAY_CONTAINER_NAME"])+
            ",'python3','-c',"+repr(collector)+"],input="+repr(json.dumps(request).encode())+
            ",capture_output=True,timeout=65)\n"
            "try:\n r=json.loads(p.stdout)\nexcept Exception:\n r={'status':'unavailable','reason':'native_response_invalid'}\n"
            "print(json.dumps(r,sort_keys=True))\n"
        )
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
        if p.returncode or not valid_safe_result(value):
            raise ValueError()
        out=value
    except subprocess.TimeoutExpired:
        out['reason']='transport_timeout'
    except Exception:
        pass
    print(json.dumps(out,sort_keys=True))
    return 0 if out['status']=='observed' else 1


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
                'execution_authorized','production_configuration_changed'):
        if type(value[key]) is not bool:return False
    for key in ('native_connection_attempted','spendable_cash_verified','complete_cash_obligations_verified',
                'execution_authorized','production_configuration_changed'):
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
    return True


if __name__=='__main__':
    raise SystemExit(main())
