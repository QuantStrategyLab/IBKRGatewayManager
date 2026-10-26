"""One bounded native read inside an existing Gateway container.

Input binding arrives on stdin. Only fixed statuses leave the container;
selected cash values remain in a new private, create-only Linux directory.
No install, login, strategy execution, summary request or broker write.
"""
from __future__ import annotations

import asyncio
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import importlib.metadata
import json
import logging
import os
from pathlib import Path
import re
import secrets
import sys
import tempfile
from uuid import UUID

TAGS = ("$LEDGER-CashBalance", "$LEDGER-TotalCashBalance", "CashBalance",
        "TotalCashBalance", "SettledCash", "AvailableFunds", "FullAvailableFunds")


class ReadError(Exception):
    pass


def now():
    return datetime.now(timezone.utc).isoformat()


def request_value(value):
    if (not isinstance(value, dict) or set(value) != {"account_ids", "port", "capture_id"}
            or not isinstance(value["account_ids"], list) or len(value["account_ids"]) != 1
            or not isinstance(value["account_ids"][0], str)
            or not re.fullmatch(r"(?:U|DU)[0-9]+", value["account_ids"][0])
            or type(value["port"]) is not int or value["port"] not in (4001, 4002)
            or str(UUID(value["capture_id"])) != value["capture_id"]):
        raise ReadError("request_invalid")
    return value


def decimal_text(value):
    try:
        amount = Decimal(value)
        if not amount.is_finite() or len(amount.as_tuple().digits) + abs(amount.as_tuple().exponent) > 4096:
            return None
        return str(amount)
    except (InvalidOperation, ValueError, TypeError):
        return None


def field_states(rows):
    states = {}
    for tag in TAGS:
        values = [row["value"] for row in rows if row["tag"] == tag and row["currency"] == "USD"]
        if not values:
            state = "MISSING"
        elif any(value is None for value in values):
            state = "INVALID"
        elif len({Decimal(value) for value in values}) != 1:
            state = "AMBIGUOUS"
        else:
            state = "OBSERVED"
        states[tag] = state
    return states


def guard_send(original, expected_account, client_id):
    def send(*fields, **kwargs):
        allowed = (
            fields == (71, 2, client_id, "")
            or fields == (16, 1)
            or (len(fields) == 4 and fields[:2] == (6, 2)
                and type(fields[2]) is bool and fields[3] == expected_account)
        )
        if not allowed:
            raise ReadError("outbound_message_not_allowed")
        return original(*fields, **kwargs)
    return send


def save_private(directory, payload):
    body = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    path = directory / "observation.json"
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(body)
        stream.flush()
        os.fsync(stream.fileno())
    if path.read_bytes() != body:
        raise ReadError("private_readback_failed")
    return hashlib.sha256(body).hexdigest()


async def observe(ib, request, out):
    expected = request["account_ids"][0]
    client_id = secrets.randbelow(2**30) + 1
    rows, inventory, orders, errors = [], Counter(), [], []
    ended = orders_ended = False
    original_value = ib.wrapper.updateAccountValue
    original_end = ib.wrapper.accountDownloadEnd
    original_orders_end = ib.wrapper.openOrderEnd
    original_open_order = ib.wrapper.openOrder

    def value(tag, val, currency, account):
        if account == expected and not ended:
            if (not isinstance(tag, str) or not re.fullmatch(r"[A-Za-z$][A-Za-z0-9$_.:-]{0,63}", tag)
                    or not isinstance(currency, str) or not re.fullmatch(r"(?:[A-Z]{3}|BASE|)", currency)):
                raise ReadError("native_field_invalid")
            inventory[(tag, currency)] += 1
            if sum(inventory.values()) > 5000:
                raise ReadError("native_response_too_large")
            if tag in TAGS or "cash" in tag.lower() or "settled" in tag.lower():
                rows.append(dict(tag=tag, currency=currency, value=decimal_text(val)))
            if tag == "AccountReady":
                out["account_ready"] = {"true":"TRUE", "false":"FALSE"}.get(str(val).lower(), "UNKNOWN")
        original_value(tag, val, currency, account)

    def end(account):
        nonlocal ended
        if account == expected:
            ended = True
        original_end(account)

    def orders_end():
        nonlocal orders_ended
        orders_ended = True
        original_orders_end()

    def open_order(order_id, contract, order, order_state):
        # Never save another account's row or raw vendor diagnostic text.
        if len(orders) + out["unbound_order_rows"] >= 5000:
            raise ReadError("native_response_too_large")
        if order.account == expected:
            orders.append(dict(order_id=order_id, client_id=order.clientId,
                account_id=expected, symbol=contract.symbol, currency=contract.currency,
                action=order.action, quantity=decimal_text(str(order.totalQuantity)),
                limit_price=decimal_text(str(order.lmtPrice)), status=order_state.status))
        else:
            out["unbound_order_rows"] += 1
        original_open_order(order_id, contract, order, order_state)

    def error(_req_id, code, _text, *_rest):
        errors.append(code)

    ib.wrapper.clientId = client_id
    ib.client.send = guard_send(ib.client.send, expected, client_id)
    ib.wrapper.updateAccountValue = value
    ib.wrapper.accountDownloadEnd = end
    ib.wrapper.openOrderEnd = orders_end
    ib.wrapper.openOrder = open_order
    ib.errorEvent += error
    ib.RaiseRequestErrors = True
    subscribed = False
    try:
        # Low-level connect avoids the SDK's automatic all-account/position/
        # execution sync. Only three allowlisted outgoing message kinds exist.
        await ib.client.connectAsync("127.0.0.1", request["port"], client_id, timeout=10)
        out["native_connection_ready"] = ib.client.isReady()
        if ib.managedAccounts() != [expected]:
            raise ReadError("physical_account_mismatch")
        out["account_matched"] = True
        subscribed = True
        await asyncio.wait_for(ib.reqAccountUpdatesAsync(expected), 25)
        if not ended:
            raise ReadError("account_download_end_missing")
        if out["account_ready"] == "FALSE":
            raise ReadError("account_reset_in_progress")
        out["account_download_end_observed"] = True
        await asyncio.wait_for(ib.reqAllOpenOrdersAsync(), 10)
        if not orders_ended:
            raise ReadError("open_order_end_missing")
        out["api_open_orders_end_observed"] = True
        out["api_selected_account_order_count"] = len(orders)
        out["usd_field_states"] = field_states(rows)
        out["native_field_name_count"] = len({tag for tag, _currency in inventory})
        out["settled_exact_usd_rows"] = inventory[("SettledCash", "USD")]
        out["settled_exact_base_rows"] = inventory[("SettledCash", "BASE")]
        out["other_settled_tag_rows"] = sum(count for (tag, _), count in inventory.items()
                                            if "settled" in tag.lower() and tag != "SettledCash")
        out["native_error_codes"] = sorted(set(errors))
        return dict(schema_version="ibkr.native_cash_inventory_observation.v1", synthetic=False,
            capture_id=request["capture_id"], account_id=expected,
            started_at=out["started_at"], received_at=now(), source_method="reqAccountUpdates",
            snapshot_atomic=False, fields=[dict(tag=tag, currency=currency, count=count)
                for (tag,currency),count in sorted(inventory.items())],
            cash_rows=rows, api_open_orders=orders, safe_result=dict(out))
    finally:
        try:
            if subscribed and ib.client.isReady():
                ib.client.reqAccountUpdates(False, expected)
        finally:
            ib.disconnect()


def result():
    return dict(schema_version="ibkr.native_cash_inventory_result.v1", status="unavailable",
        reason="read_failed", capture_id=None, started_at=now(), native_connection_ready=False,
        account_matched=False, account_download_end_observed=False, account_ready="UNKNOWN",
        api_open_orders_end_observed=False, api_selected_account_order_count=None,
        unbound_order_rows=0, usd_field_states=dict.fromkeys(TAGS,"MISSING"),
        native_field_name_count=None, settled_exact_usd_rows=None, settled_exact_base_rows=None,
        other_settled_tag_rows=None, native_error_codes=[],
        private_evidence_readback_verified=False, evidence_sha256=None,
        private_evidence_scope="EXISTING_GATEWAY_CONTAINER_ONLY", durable_cloud_store_verified=False,
        complete_cash_obligations_verified=False, spendable_cash_verified=False,
        execution_authorized=False, production_configuration_changed=False)


def main():
    logging.disable(logging.CRITICAL)
    out = result()
    try:
        request = request_value(json.loads(sys.stdin.buffer.read(16384)))
        out["capture_id"] = request["capture_id"]
        if sys.platform != "linux" or importlib.metadata.version("ib_insync") != "0.9.86":
            raise ReadError("existing_sdk_not_supported")
        from ib_insync import IB
        directory = Path(tempfile.mkdtemp(prefix="qsl-native-cash-" + request["capture_id"] + "-"))
        directory.chmod(0o700)
        payload = asyncio.run(observe(IB(), request, out))
        out["evidence_sha256"] = save_private(directory, payload)
        out.update(status="observed", reason="native_read_saved_and_readback_verified",
                   private_evidence_readback_verified=True)
    except ReadError as error:
        out["reason"] = str(error)
    except (asyncio.TimeoutError, TimeoutError):
        out["reason"] = "native_read_timeout"
    except Exception:
        out["reason"] = "native_read_failed"
    print(json.dumps(out,sort_keys=True))
    return 0 if out["status"] == "observed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
