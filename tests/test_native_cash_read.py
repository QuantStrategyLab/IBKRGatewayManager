import asyncio
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.read_native_cash import (ReadError, field_states, guard_send, main, observe,
    read_saved_inventory, request_value, result, save_private, saved_result)
from scripts.run_native_cash_ssh import valid_safe_result

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


if __name__=='__main__':unittest.main()
