"""One API session probe through the already installed, pinned Gateway client.

Only startApi is allowed by default. Explicit contract-details mode also admits
one fixed SOXL/SMART/USD security-definition request. No account update, order,
execution, position, login, settings, installation, reconnect or retry request.
All native output stays captured on the existing Linux VM/container.
"""
from __future__ import annotations

import inspect
import json
import re
import subprocess
import sys


def probe_once(port, contract_details=False):
    import asyncio
    import contextlib
    import importlib.metadata
    import io
    import logging
    import secrets
    import sys

    result = dict(status="unavailable", reason="probe_failed", connection_attempts=0,
                  api_session_ready=False, managed_account_count=None,
                  account_identity_verified=False, broker_write_attempts=0)
    if contract_details:
        result.update(contract_details_status="not_requested", contract_details_request_attempts=0,
                      contract_details_record_count=None, contract_details_end_observed=False,
                      contract_identity_match=None, contract_error_codes=[])
    logging.disable(logging.CRITICAL)
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        try:
            if sys.platform != "linux" or port not in (4001, 4002) or importlib.metadata.version("ib_insync") != "0.9.86":
                result["reason"] = "client_prerequisite_unavailable"
                return result
            from ib_insync import IB
            ib = IB()
            client_id = secrets.randbelow(2**30) + 1
            send = ib.client.send
            start_sent = False
            details_contract = None
            details_req_id = None
            error_codes = set()
            request_rejected = False
            disconnected = False

            def on_error(req_id, code, _message, _contract):
                nonlocal request_rejected
                if code in {1100, 1101, 1102, 2103, 2104, 2105, 2106, 2158, 326, 504, 200, 321, 354}:
                    error_codes.add(str(code))
                elif req_id == details_req_id:
                    error_codes.add("other")
                if details_req_id is not None and req_id == details_req_id:
                    request_rejected = True

            def on_disconnect():
                nonlocal disconnected
                disconnected = True

            def guarded_send(*fields, **kwargs):
                nonlocal start_sent
                if not kwargs and fields == (71, 2, client_id, "") and not start_sent:
                    start_sent = True
                    return send(*fields)
                if (contract_details and not kwargs and start_sent and details_contract is not None
                        and fields[:3] == (9, 8, details_req_id) and len(fields) in (7, 8)
                        and fields[3] is details_contract and fields[4:7] == (False, "", "")
                        and (len(fields) == 7 or fields[7] == "")
                        and result["contract_details_request_attempts"] == 0
                        and details_contract.symbol == "SOXL" and details_contract.secType == "STK"
                        and details_contract.exchange == "SMART" and details_contract.currency == "USD"
                        and details_contract.conId == 0):
                    result["contract_details_request_attempts"] = 1
                    return send(*fields)
                raise RuntimeError("outgoing_request_forbidden")

            ib.client.send = guarded_send
            try:
                if contract_details:
                    # IB's default 1102 handler automatically requests account
                    # summary even without IB.connect; this probe must not do so.
                    ib.errorEvent -= ib._onError
                    ib.errorEvent += on_error
                    ib.disconnectedEvent += on_disconnect
                result["connection_attempts"] = 1
                # The low-level client only waits for nextValidId and managedAccounts.
                # IB.connect would additionally synchronize account/order data.
                ib.run(ib.client.connectAsync("127.0.0.1", port, client_id, timeout=10))
                ready = ib.client.isReady()
                accounts = ib.managedAccounts()
                if ready and accounts:
                    result.update(status="observed", reason="api_session_ready",
                                  api_session_ready=True, managed_account_count=len(accounts))
                    if contract_details:
                        from ib_insync import Stock
                        details_contract = Stock("SOXL", "SMART", "USD")
                        details_req_id = ib.client.getReqId()
                        original_end = ib.wrapper.contractDetailsEnd

                        def on_end(req_id):
                            if req_id == details_req_id:
                                result["contract_details_end_observed"] = True
                            return original_end(req_id)

                        ib.wrapper.contractDetailsEnd = on_end
                        future = ib.wrapper.startReq(details_req_id, details_contract)
                        result.update(status="unavailable", reason="contract_details_failed",
                                      contract_details_status="probe_failed")
                        ib.client.reqContractDetails(details_req_id, details_contract)
                        try:
                            details = ib.run(asyncio.wait_for(future, timeout=10))
                        except (asyncio.TimeoutError, TimeoutError):
                            result.update(reason="contract_details_timeout", contract_details_status="timeout")
                        else:
                            if disconnected:
                                result.update(reason="contract_details_disconnected", contract_details_status="disconnected")
                            elif request_rejected:
                                result.update(reason="contract_details_rejected", contract_details_status="rejected")
                            elif result["contract_details_end_observed"] and isinstance(details, list):
                                result["contract_details_record_count"] = len(details)
                                if len(details) == 1:
                                    contract = details[0].contract
                                    matched = (contract.symbol == "SOXL" and contract.secType == "STK"
                                               and contract.exchange == "SMART" and contract.currency == "USD"
                                               and type(contract.conId) is int and contract.conId > 0)
                                    result["contract_identity_match"] = matched
                                    if matched:
                                        result.update(status="observed", reason="contract_details_ready", contract_details_status="ready")
                                    else:
                                        result.update(reason="contract_details_identity_mismatch", contract_details_status="identity_mismatch")
                                else:
                                    state = "empty" if not details else "ambiguous"
                                    result.update(reason="contract_details_" + state, contract_details_status=state)
                else:
                    result["reason"] = "api_session_incomplete"
            finally:
                ib.disconnect()
                if contract_details:
                    result["contract_error_codes"] = sorted(error_codes)
        except (asyncio.TimeoutError, TimeoutError):
            result["reason"] = "api_session_timeout"
        except ConnectionRefusedError:
            result["reason"] = "api_connection_refused"
        except ImportError:
            result["reason"] = "client_prerequisite_unavailable"
        except Exception:
            result["reason"] = "api_probe_failed"
            if contract_details and result["contract_details_request_attempts"]:
                result.update(status="unavailable", reason="contract_details_disconnected" if disconnected else "contract_details_failed",
                              contract_details_status="disconnected" if disconnected else "probe_failed")
    if contract_details and result["reason"] != "contract_details_ready":
        result["status"] = "unavailable"
    return result


def main(argv=None, *, probe_source=None):
    args = sys.argv[1:] if argv is None else argv
    contract_details = len(args) == 3 and args[2] == "--contract-details"
    reasons = {"probe_failed", "client_prerequisite_unavailable", "api_session_ready",
               "api_session_incomplete", "api_session_timeout", "api_connection_refused", "api_probe_failed"}
    out = dict(status="unavailable", reason="probe_failed", connection_attempts=None,
               api_session_ready=False, managed_account_count=None,
               account_identity_verified=False, broker_write_attempts=0)
    if contract_details:
        reasons.update({"contract_details_failed", "contract_details_ready", "contract_details_timeout",
                        "contract_details_disconnected", "contract_details_rejected", "contract_details_identity_mismatch",
                        "contract_details_empty", "contract_details_ambiguous"})
        out.update(contract_details_status="unknown", contract_details_request_attempts=None,
                   contract_details_record_count=None, contract_details_end_observed=None,
                   contract_identity_match=None, contract_error_codes=None)
    phase = "binding"
    try:
        if (len(args) != (3 if contract_details else 2)
                or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", args[0]) or args[1] not in {"4001", "4002"}):
            raise ValueError()
        phase = "source"
        code = ((probe_source if probe_source is not None else inspect.getsource(probe_once))
                + "\nimport json\nprint(json.dumps(probe_once(" + args[1] + ", contract_details=" + repr(contract_details) + ")))\n")
        phase = "native"
        native = subprocess.run(["sudo", "-n", "docker", "exec", "-i", args[0], "python3", "-c", code],
                                capture_output=True, timeout=25)
        if native.returncode or len(native.stdout) > 4096:
            raise ValueError()
        phase = "response"
        candidate = json.loads(native.stdout)
        if (not isinstance(candidate, dict) or set(candidate) != set(out)
                or candidate["status"] not in {"observed", "unavailable"}
                or candidate["reason"] not in reasons
                or type(candidate["connection_attempts"]) is not int or candidate["connection_attempts"] not in (0, 1)
                or type(candidate["api_session_ready"]) is not bool
                or candidate["managed_account_count"] is not None and (type(candidate["managed_account_count"]) is not int or not 0 <= candidate["managed_account_count"] <= 1000)
                or candidate["account_identity_verified"] is not False or candidate["broker_write_attempts"] != 0):
            raise ValueError()
        if contract_details:
            count = candidate["contract_details_record_count"]
            codes = candidate["contract_error_codes"]
            if (candidate["contract_details_status"] not in {"not_requested", "ready", "empty", "timeout", "rejected", "disconnected", "identity_mismatch", "ambiguous", "probe_failed"}
                    or type(candidate["contract_details_request_attempts"]) is not int or candidate["contract_details_request_attempts"] not in (0, 1)
                    or count is not None and (type(count) is not int or not 0 <= count <= 10000)
                    or type(candidate["contract_details_end_observed"]) is not bool
                    or candidate["contract_identity_match"] is not None and type(candidate["contract_identity_match"]) is not bool
                    or not isinstance(codes, list) or any(code not in {"1100", "1101", "1102", "2103", "2104", "2105", "2106", "2158", "326", "504", "200", "321", "354", "other"} for code in codes)
                    or codes != sorted(set(codes))
                    or count is not None and (not candidate["contract_details_end_observed"] or candidate["contract_details_request_attempts"] != 1)
                    or candidate["status"] == "observed" and
                    (candidate["contract_details_status"] != "ready" or candidate["reason"] != "contract_details_ready")
                    or candidate["contract_details_status"] == "ready" and
                    (count != 1 or candidate["contract_identity_match"] is not True or candidate["api_session_ready"] is not True)):
                raise ValueError()
        out = candidate
    except subprocess.TimeoutExpired:
        out["reason"] = "native_transport_timeout"
    except Exception:
        if phase in {"binding", "source"}:
            out["connection_attempts"] = 0
            if contract_details:
                out.update(contract_details_request_attempts=0, contract_details_status="not_requested")
        out["reason"] = {"binding": "binding_invalid", "source": "probe_source_unavailable",
                         "native": "native_execution_failed", "response": "native_response_invalid"}[phase]
    print("GATEWAY_READONLY_API_STATUS=" + out["status"])
    print("GATEWAY_READONLY_API_REASON=" + out["reason"])
    print("GATEWAY_READONLY_API_CONNECTION_ATTEMPTS=" + (str(out["connection_attempts"]) if out["connection_attempts"] is not None else "unknown"))
    print("GATEWAY_READONLY_API_SESSION_READY=" + str(out["api_session_ready"]).lower())
    print("GATEWAY_READONLY_API_MANAGED_ACCOUNT_COUNT=" + (str(out["managed_account_count"]) if out["managed_account_count"] is not None else "unknown"))
    print("GATEWAY_READONLY_API_LIMIT=NO_ACCOUNT_IDENTITY_OR_ORDER_CAPABILITY_ASSERTION")
    if contract_details:
        for field in ("status", "request_attempts", "record_count", "end_observed"):
            value = out["contract_details_" + field]
            print("GATEWAY_CONTRACT_DETAILS_" + field.upper() + "=" + ("unknown" if value is None else str(value).lower()))
        value = out["contract_identity_match"]
        print("GATEWAY_CONTRACT_DETAILS_IDENTITY_MATCH=" + ("unknown" if value is None else str(value).lower()))
        codes = out["contract_error_codes"]
        print("GATEWAY_CONTRACT_DETAILS_ERROR_CODES=" + ("unknown" if codes is None else ",".join(codes) or "none"))
    return 0


def render_remote():
    # Resolve the public function sources while the checkout file is available.
    # SSH stdin has no inspectable source file on the remote host.
    return ("import json, re, subprocess, sys\n" + inspect.getsource(main)
            + "\nraise SystemExit(main(probe_source=" + repr(inspect.getsource(probe_once)) + "))\n")


if __name__ == "__main__":
    if sys.argv[1:] == ["--render-remote"]:
        print(render_remote(), end="")
    else:
        raise SystemExit(main())
