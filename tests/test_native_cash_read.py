import asyncio
from contextlib import redirect_stdout
import hashlib
import io
import json
import tarfile
from decimal import Decimal
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.read_native_cash import (ReadError, field_states, guard_send, main, observe,
    inspect_saved_schedule, read_saved_inventory, request_value, result, save_private,
    save_private_bytes, saved_result, schedule_pair, value_shape)
from scripts.run_native_cash_ssh import remote_program, retain_saved_on_host, valid_safe_result

ACCOUNT='U1234567'
REQUEST=dict(account_ids=[ACCOUNT],port=4001,capture_id='12345678-1234-4234-8234-123456789abc')


class Event:
    def __iadd__(self,item):return self


class FakeIB:
    def __init__(self,accounts=None,ended=True):
        self.accounts=accounts if accounts is not None else [ACCOUNT]
        self.ended=ended;self.sent=[];self.disconnected=False
        self.wrapper=SimpleNamespace(updateAccountValue=lambda *a:None,accountDownloadEnd=lambda *a:None,
            openOrderEnd=lambda:None,openOrder=lambda *a:None)
        self.errorEvent=Event()
        self.client=SimpleNamespace(send=lambda *a,**k:self.sent.append(a),isReady=lambda:True,
            reqAccountUpdates=lambda flag,acct:self.client.send(6,2,flag,acct))
        async def connect(*args,**kwargs):self.client.send(71,2,args[2],'')
        self.client.connectAsync=connect
    def managedAccounts(self):return self.accounts
    async def reqAccountUpdatesAsync(self,account):
        self.client.send(6,2,True,account)
        for tag,value in (('CashBalance','100.25'),('SettledCash','90.125'),('AvailableFunds','150.0')):
            self.wrapper.updateAccountValue(tag,value,'USD',account)
        self.wrapper.updateAccountValue('OtherSettledCash','999','BASE',account)
        if self.ended:self.wrapper.accountDownloadEnd(account)
    async def reqAllOpenOrdersAsync(self):
        self.client.send(16,1);self.wrapper.openOrderEnd();return []
    def disconnect(self):self.disconnected=True


class NativeCashTests(unittest.TestCase):
    def test_exact_account_and_request(self):
        self.assertEqual(request_value(REQUEST),REQUEST)
        for update in ({'account_ids':[]},{'account_ids':['U1234567','U7654321']},{'port':5000},{'extra':'x'}):
            with self.subTest(update=update),self.assertRaises((ReadError,ValueError)):
                request_value({**REQUEST,**update})
    def test_wire_guard_blocks_order_and_other_account(self):
        seen=[];send=guard_send(lambda *a:seen.append(a),ACCOUNT,33)
        for msg in ((71,2,33,''),(6,2,True,ACCOUNT),(6,2,False,ACCOUNT),(16,1)):send(*msg)
        for msg in ((3,45,1),(4,1,1),(58,1,True),(6,2,True,'U7654321'),(71,2,0,''),(7,3,1)):
            with self.subTest(msg=msg),self.assertRaises(ReadError):send(*msg)
        self.assertEqual(len(seen),4)
    def test_native_end_and_private_values(self):
        ib=FakeIB();out=result();payload=asyncio.run(observe(ib,REQUEST,out))
        self.assertTrue(out['account_matched']);self.assertTrue(out['account_download_end_observed'])
        self.assertTrue(out['api_open_orders_end_observed']);self.assertTrue(ib.disconnected)
        self.assertEqual(out['usd_field_states']['SettledCash'],'OBSERVED')
        self.assertEqual(out['usd_field_states']['AvailableFunds'],'OBSERVED')
        self.assertEqual(out['other_settled_tag_rows'],1)
        self.assertEqual(payload['cash_rows'][1]['value'],'90.125')
        self.assertNotIn('90.125',json.dumps(out));self.assertNotIn(ACCOUNT,json.dumps(out))
        with tempfile.TemporaryDirectory() as directory:
            digest=save_private(Path(directory),payload)
            self.assertEqual(len(digest),64)
            self.assertEqual((Path(directory)/'observation.json').stat().st_mode & 0o777,0o600)
            with self.assertRaises(FileExistsError):save_private(Path(directory),payload)
    def test_wrong_gateway_account_stops_before_updates(self):
        ib=FakeIB(accounts=['U7654321'])
        with self.assertRaisesRegex(ReadError,'physical_account_mismatch'):asyncio.run(observe(ib,REQUEST,result()))
        self.assertEqual(len(ib.sent),1);self.assertTrue(ib.disconnected)
    def test_no_end_is_not_success(self):
        ib=FakeIB(ended=False)
        with self.assertRaisesRegex(ReadError,'account_download_end_missing'):asyncio.run(observe(ib,REQUEST,result()))
        self.assertTrue(ib.disconnected);self.assertNotIn((16,1),ib.sent)
    def test_disconnect_even_if_unsubscribe_fails(self):
        ib=FakeIB()
        def unsubscribe(*_args):raise ConnectionError('synthetic disconnect')
        ib.client.reqAccountUpdates=unsubscribe
        with self.assertRaises(ConnectionError):asyncio.run(observe(ib,REQUEST,result()))
        self.assertTrue(ib.disconnected)
    def test_no_open_order_end_is_not_success(self):
        ib=FakeIB()
        async def orders():ib.client.send(16,1);return []
        ib.reqAllOpenOrdersAsync=orders
        with self.assertRaisesRegex(ReadError,'open_order_end_missing'):
            asyncio.run(observe(ib,REQUEST,result()))
        self.assertTrue(ib.disconnected)
    def test_currency_precision_duplicates(self):
        rows=[{'tag':'SettledCash','currency':'BASE','value':'999'},
              {'tag':'CashBalance','currency':'USD','value':'-0.000000001'},
              {'tag':'CashBalance','currency':'USD','value':'-0.0000000010'}]
        self.assertEqual(field_states(rows)['SettledCash'],'MISSING')
        self.assertEqual(field_states(rows)['CashBalance'],'OBSERVED')
        rows.append({'tag':'CashBalance','currency':'USD','value':'0'})
        self.assertEqual(field_states(rows)['CashBalance'],'AMBIGUOUS')
    def test_safe_transport_rejects_raw_values_or_qualification(self):
        out=result();self.assertTrue(valid_safe_result(out))
        self.assertFalse(valid_safe_result({**out,'account_id':ACCOUNT}))
        self.assertFalse(valid_safe_result({**out,'reason':'raw '+ACCOUNT}))
        self.assertFalse(valid_safe_result({**out,'schema_version':ACCOUNT}))
        self.assertFalse(valid_safe_result({**out,'status':'observed'}))
        self.assertFalse(valid_safe_result({**out,'capture_id':'-'*36}))
        self.assertFalse(valid_safe_result({**out,'usd_field_states':{'SettledCash':'90.125'}}))
        for key in ('execution_authorized','spendable_cash_verified','complete_cash_obligations_verified'):
            self.assertFalse(valid_safe_result({**out,key:True}))

    def test_saved_inventory_uses_exact_private_file_without_sdk_or_native_connection(self):
        payload=asyncio.run(observe(FakeIB(),REQUEST,result()))
        with tempfile.TemporaryDirectory() as folder:
            directory=Path(folder)/('qsl-native-cash-'+REQUEST['capture_id']+'-fixture')
            directory.mkdir(mode=0o700)
            digest=save_private(directory,payload)
            request=dict(account_ids=[ACCOUNT],capture_id=REQUEST['capture_id'],evidence_sha256=digest)
            output=io.StringIO()
            with (patch('tempfile.gettempdir',return_value=folder),patch('sys.platform','linux'),
                  patch('importlib.metadata.version',side_effect=AssertionError('SDK must not load')) as sdk,
                  patch('sys.stdin',SimpleNamespace(buffer=io.BytesIO(json.dumps(request).encode()))),
                  redirect_stdout(output)):
                self.assertEqual(main(),0)
                sdk.assert_not_called()
            out=json.loads(output.getvalue())
            self.assertTrue(valid_safe_result(out))
            self.assertFalse(out['native_connection_attempted'])
            self.assertEqual(out['settled_tag_inventory'],[
                dict(tag='OtherSettledCash',currency='BASE',row_count=1,numeric_rows=1),
                dict(tag='SettledCash',currency='USD',row_count=1,numeric_rows=1)])
            self.assertNotIn(ACCOUNT,output.getvalue());self.assertNotIn('90.125',output.getvalue())
            with patch('tempfile.gettempdir',return_value=folder):
                for update in ({'evidence_sha256':'0'*64},{'account_ids':['U7654321']},
                               {'capture_id':'12345678-1234-4234-8234-123456789abd'}):
                    with self.subTest(update=update),self.assertRaises(ReadError):
                        read_saved_inventory({**request,**update})
                (directory/'observation.json').chmod(0o644)
                with self.assertRaises(ReadError):read_saved_inventory(request)

    def test_saved_inventory_validator_rejects_raw_values_and_false_qualification(self):
        out=saved_result();self.assertTrue(valid_safe_result(out))
        self.assertFalse(valid_safe_result({**out,'account_id':ACCOUNT}))
        self.assertFalse(valid_safe_result({**out,'status':'observed'}))
        self.assertFalse(valid_safe_result({**out,'native_connection_attempted':True}))
        self.assertFalse(valid_safe_result({**out,'settled_tag_inventory':[
            dict(tag='SettledCash',currency='USD',row_count=1,numeric_rows=1,value='90.125')]}))

    def test_schedule_text_is_preserved_privately_without_aliasing_scalar_cash(self):
        ib=FakeIB();original=ib.reqAccountUpdatesAsync
        raw='20261026:90.125;20261027:100.25'
        async def updates(account):
            ib.wrapper.updateAccountValue('SettledCashByDate',raw,'USD',account)
            await original(account)
        ib.reqAccountUpdatesAsync=updates
        out=result();payload=asyncio.run(observe(ib,REQUEST,out))
        schedule=next(row for row in payload['cash_rows'] if row['tag']=='SettledCashByDate')
        self.assertEqual(schedule['raw_value'],raw);self.assertIsNone(schedule['value'])
        self.assertEqual(out['settlement_schedule_inventory'],[
            dict(tag='SettledCashByDate',currency='USD',row_count=1,raw_rows=1,value_shapes=['D:D.D;D:D.D'])])
        self.assertTrue(valid_safe_result(out))
        self.assertNotIn('90.125',json.dumps(out));self.assertNotIn('20261026',json.dumps(out))
        self.assertEqual(value_shape('other text\n[20261026,-5.12]'),'AWAW[D,-D.D]')
        bad={**out,'settlement_schedule_inventory':[
            dict(tag='SettledCashByDate',currency='USD',row_count=1,raw_rows=1,value_shapes=[raw])]}
        self.assertFalse(valid_safe_result(bad))

    def test_compact_transport_reconstructs_exact_source_and_keeps_binding_on_stdin(self):
        source=(ROOT/'scripts/read_native_cash.py').read_text()
        remote=remote_program('gateway',source,REQUEST)
        self.assertLess(len(remote.encode()),16384)
        safe=saved_result()
        with (patch('subprocess.run',return_value=SimpleNamespace(stdout=json.dumps(safe).encode())) as child,
              redirect_stdout(io.StringIO())):
            exec(compile(remote,'<synthetic-remote>','exec'),{})
        args=child.call_args.args[0]
        self.assertEqual(args[:7],['sudo','-n','docker','exec','-i','gateway','python3'])
        self.assertEqual(args[-2:],['-c',source])
        self.assertEqual(json.loads(child.call_args.kwargs['input']),REQUEST)
        self.assertNotIn(ACCOUNT,' '.join(args))
        self.assertEqual(child.call_args.kwargs['timeout'],65)

    def test_compact_transport_rejects_changed_source_before_execution(self):
        source=(ROOT/'scripts/read_native_cash.py').read_text()
        remote=remote_program('gateway',source,REQUEST)
        remote=remote.replace(hashlib.sha256(source.encode()).hexdigest(),'0'*64)
        with patch('subprocess.run') as child,self.assertRaisesRegex(ValueError,'public_source_digest_mismatch'):
            exec(compile(remote,'<synthetic-remote>','exec'),{})
        child.assert_not_called()

    def test_schedule_syntax_does_not_choose_a_date_or_offset(self):
        for raw,shape in [('0:1.25','ZERO_KEY'),('2:-1.25','INTEGER_KEY'),
                          ('20991231:1.25','CALENDAR_DATE_SHAPED'),
                          ('20260230:1.25','INVALID_CALENDAR_DATE_SHAPED')]:
            with self.subTest(raw=raw):
                status,key_shape,pair=schedule_pair(raw)
                self.assertEqual((status,key_shape),('SINGLE_PAIR',shape))
                self.assertIsInstance(pair[1],Decimal)
                out=inspect_saved_schedule([dict(tag='SettledCashByDate',currency='USD',value=None,raw_value=raw)])
                self.assertFalse(out['date_key_semantics_verified'])
                self.assertFalse(out['current_settlement_selected'])
                self.assertFalse(out['settled_cash_equivalence_verified'])
        for raw,status in [(None,'RAW_NOT_PRESERVED'),('','EMPTY'),('0:1;1:2','UNSUPPORTED_FORMAT'),
                           ('0:NaN','UNSUPPORTED_FORMAT'),('0:Infinity','UNSUPPORTED_FORMAT'),
                           ('0:1,200','UNSUPPORTED_FORMAT'),('0:'+'1'*4097,'INVALID_NUMBER')]:
            with self.subTest(raw_kind=status):self.assertEqual(schedule_pair(raw)[0],status)

    def test_saved_segment_arithmetic_is_exact_and_currency_scoped(self):
        rows=[]
        def add(tag,raw,currency='USD'):
            rows.append(dict(tag=tag,currency=currency,value=None,raw_value=raw))
        add('SettledCashByDate','0:100.000000000000000000000000000001')
        add('SettledCashByDate-C','0:0.000000000000000000000000000001')
        add('SettledCashByDate-S','0:100')
        rows.append(dict(tag='$LEDGER-CashBalance',currency='USD',value='100.000000000000000000000000000001'))
        for tag,raw in [('SettledCashByDate','0:3'),('SettledCashByDate-C','0:1'),('SettledCashByDate-S','0:2')]:add(tag,raw,'BASE')
        out=inspect_saved_schedule(rows)
        relationships={row['currency']:row for row in out['relationships']}
        self.assertEqual(relationships['USD']['segment_consistency'],'SAME_KEY_TOTAL_EQUALS_SEGMENTS')
        self.assertEqual(relationships['USD']['same_capture_ledger_relation'],'EQUAL')
        self.assertEqual(relationships['BASE']['same_capture_ledger_relation'],'UNKNOWN')
        self.assertNotIn('100.000000000000000000000000000001',json.dumps(out))
        rows[1]['raw_value']='1:0.000000000000000000000000000001'
        self.assertEqual(inspect_saved_schedule(rows)['relationships'][1]['segment_consistency'],'KEYS_DIFFER')
        rows[1]['raw_value']='0:2'
        self.assertEqual(inspect_saved_schedule(rows)['relationships'][1]['segment_consistency'],'SAME_KEY_TOTAL_DIFFERS')
        rows.append(dict(rows[0]))
        self.assertEqual(inspect_saved_schedule(rows)['fields'][1]['syntax_status'],'REPEATED_CONSISTENT_PAIR')
        rows[-1]['raw_value']='0:999'
        self.assertEqual(inspect_saved_schedule(rows)['fields'][1]['syntax_status'],'AMBIGUOUS_ROWS')

    def test_saved_structure_cannot_leak_values_or_certify_cash(self):
        out=saved_result()
        out['settlement_structure']=inspect_saved_schedule([
            dict(tag='SettledCashByDate',currency='USD',value=None,raw_value='0:-1.25')])
        self.assertTrue(valid_safe_result(out))
        for key in ('date_key_semantics_verified','settled_cash_equivalence_verified','current_settlement_selected'):
            changed={**out,'settlement_structure':{**out['settlement_structure'],key:True}}
            self.assertFalse(valid_safe_result(changed))
        out['settlement_structure']['fields'][0]['value']='-1.25'
        self.assertFalse(valid_safe_result(out))

    def test_host_retention_copies_exact_bytes_once_without_stdout_or_native_connection(self):
        body=b'{"synthetic":true,"amount":"1.25"}'
        request=dict(account_ids=[ACCOUNT],capture_id=REQUEST['capture_id'],evidence_sha256=hashlib.sha256(body).hexdigest())
        archive=io.BytesIO()
        with tarfile.open(fileobj=archive,mode='w') as tar:
            entry=tarfile.TarInfo('observation.json');entry.size=len(body)
            tar.addfile(entry,io.BytesIO(body))
        found=SimpleNamespace(returncode=0,stdout=('/tmp/qsl-native-cash-'+REQUEST['capture_id']+'-fixture/observation.json\n').encode())
        copied=SimpleNamespace(returncode=0,stdout=archive.getvalue())
        output=io.StringIO()
        with tempfile.TemporaryDirectory() as folder,patch('pathlib.Path.home',return_value=Path(folder)):
            with patch('subprocess.run',side_effect=[found,copied]) as child,redirect_stdout(output):
                digest=retain_saved_on_host('gateway',request,save_private_bytes)
            self.assertEqual(digest,request['evidence_sha256']);self.assertEqual(output.getvalue(),'')
            args=' '.join(' '.join(call.args[0]) for call in child.call_args_list)
            self.assertNotIn(ACCOUNT,args);self.assertNotIn('1.25',args)
            path=Path(folder)/'.qsl-native-cash-evidence'/request['capture_id']/'observation.json'
            self.assertEqual(path.read_bytes(),body)
            self.assertEqual(path.stat().st_mode&0o777,0o600)
            self.assertEqual(path.parent.stat().st_mode&0o777,0o700)
            with patch('subprocess.run') as child:
                self.assertEqual(retain_saved_on_host('gateway',request,save_private_bytes),digest)
                child.assert_not_called()
            path.write_bytes(b'conflicting-private-evidence')
            with self.assertRaisesRegex(ValueError,'digest_mismatch'):
                retain_saved_on_host('gateway',request,save_private_bytes)
            self.assertEqual(path.read_bytes(),b'conflicting-private-evidence')

    def test_host_retention_rejects_unsafe_archive_and_requires_saved_mode(self):
        source=(ROOT/'scripts/read_native_cash.py').read_text()
        with self.assertRaisesRegex(ValueError,'retention_requires_saved_read'):
            remote_program('gateway',source,REQUEST,retain_on_host=True)
        request=dict(account_ids=[ACCOUNT],capture_id=REQUEST['capture_id'],evidence_sha256='0'*64)
        archive=io.BytesIO()
        with tarfile.open(fileobj=archive,mode='w') as tar:
            entry=tarfile.TarInfo('observation.json');entry.type=tarfile.SYMTYPE;entry.linkname='/etc/passwd'
            tar.addfile(entry)
        found=SimpleNamespace(returncode=0,stdout=('/tmp/qsl-native-cash-'+REQUEST['capture_id']+'-fixture/observation.json\n').encode())
        copied=SimpleNamespace(returncode=0,stdout=archive.getvalue())
        with tempfile.TemporaryDirectory() as folder,patch('pathlib.Path.home',return_value=Path(folder)):
            with patch('subprocess.run',side_effect=[found,copied]),self.assertRaisesRegex(ValueError,'archive_invalid'):
                retain_saved_on_host('gateway',request,save_private_bytes)
            self.assertFalse((Path(folder)/'.qsl-native-cash-evidence'/request['capture_id']).exists())

    def test_remote_retention_failure_emits_fixed_reason_without_raw_body(self):
        source=(ROOT/'scripts/read_native_cash.py').read_text()
        request=dict(account_ids=[ACCOUNT],capture_id=REQUEST['capture_id'],evidence_sha256='0'*64)
        safe=saved_result()
        safe.update(status='observed',reason='saved_inventory_readback_verified',
            capture_id=request['capture_id'],evidence_sha256=request['evidence_sha256'],
            source_started_at=result()['started_at'],account_matched=True,saved_readback_verified=True,
            settlement_structure=inspect_saved_schedule([]))
        collector=SimpleNamespace(returncode=0,stdout=json.dumps(safe).encode())
        failed=SimpleNamespace(returncode=1,stdout=b'',stderr=b'private source '+ACCOUNT.encode())
        output=io.StringIO()
        remote=remote_program('gateway',source,request,retain_on_host=True)
        self.assertLess(len(remote.encode()),16384)
        with (tempfile.TemporaryDirectory() as folder,patch('pathlib.Path.home',return_value=Path(folder)),
              patch('subprocess.run',side_effect=[collector,failed]),redirect_stdout(output)):
            exec(compile(remote,'<synthetic-remote>','exec'),{})
        out=json.loads(output.getvalue())
        self.assertTrue(valid_safe_result(out));self.assertTrue(out['saved_readback_verified'])
        self.assertEqual(out['existing_host_retention_status'],'UNAVAILABLE')
        self.assertEqual(out['existing_host_retention_reason'],'retention_source_unavailable')
        self.assertFalse(out['existing_host_readback_verified'])
        self.assertFalse(out['native_connection_attempted'])
        self.assertNotIn(ACCOUNT,output.getvalue());self.assertNotIn('private source',output.getvalue())


if __name__=='__main__':unittest.main()
