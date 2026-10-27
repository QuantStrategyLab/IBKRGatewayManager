"""One API session probe through the already installed, pinned Gateway client.

Only startApi is allowed on the outgoing SDK port. No account update, order,
execution, position, login, settings, installation, reconnect or retry request.
All native output stays captured on the existing Linux VM/container.
"""
from __future__ import annotations

import inspect
import json
import re
import subprocess
import sys


def probe_once(port):
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

            def guarded_send(*fields, **kwargs):
                if fields != (71, 2, client_id, "") or kwargs:
                    raise RuntimeError("outgoing_request_forbidden")
                return send(*fields)

            ib.client.send = guarded_send
            try:
                result["connection_attempts"] = 1
                # The low-level client only waits for nextValidId and managedAccounts.
                # IB.connect would additionally synchronize account/order data.
                ib.run(ib.client.connectAsync("127.0.0.1", port, client_id, timeout=10))
                ready = ib.client.isReady()
                accounts = ib.managedAccounts()
                if ready and accounts:
                    result.update(status="observed", reason="api_session_ready",
                                  api_session_ready=True, managed_account_count=len(accounts))
                else:
                    result["reason"] = "api_session_incomplete"
            finally:
                ib.disconnect()
        except (asyncio.TimeoutError, TimeoutError):
            result["reason"] = "api_session_timeout"
        except ConnectionRefusedError:
            result["reason"] = "api_connection_refused"
        except ImportError:
            result["reason"] = "client_prerequisite_unavailable"
        except Exception:
            result["reason"] = "api_probe_failed"
    return result


def main(argv=None, *, probe_source=None):
    args = sys.argv[1:] if argv is None else argv
    reasons = {"probe_failed", "client_prerequisite_unavailable", "api_session_ready",
               "api_session_incomplete", "api_session_timeout", "api_connection_refused", "api_probe_failed"}
    out = dict(status="unavailable", reason="probe_failed", connection_attempts=None,
               api_session_ready=False, managed_account_count=None,
               account_identity_verified=False, broker_write_attempts=0)
    phase = "binding"
    try:
        if len(args) != 2 or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", args[0]) or args[1] not in {"4001", "4002"}:
            raise ValueError()
        phase = "source"
        code = (probe_source if probe_source is not None else inspect.getsource(probe_once)) + "\nimport json\nprint(json.dumps(probe_once(" + args[1] + ")))\n"
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
        out = candidate
    except subprocess.TimeoutExpired:
        out["reason"] = "native_transport_timeout"
    except Exception:
        if phase in {"binding", "source"}:
            out["connection_attempts"] = 0
        out["reason"] = {"binding": "binding_invalid", "source": "probe_source_unavailable",
                         "native": "native_execution_failed", "response": "native_response_invalid"}[phase]
    print("GATEWAY_READONLY_API_STATUS=" + out["status"])
    print("GATEWAY_READONLY_API_REASON=" + out["reason"])
    print("GATEWAY_READONLY_API_CONNECTION_ATTEMPTS=" + (str(out["connection_attempts"]) if out["connection_attempts"] is not None else "unknown"))
    print("GATEWAY_READONLY_API_SESSION_READY=" + str(out["api_session_ready"]).lower())
    print("GATEWAY_READONLY_API_MANAGED_ACCOUNT_COUNT=" + (str(out["managed_account_count"]) if out["managed_account_count"] is not None else "unknown"))
    print("GATEWAY_READONLY_API_LIMIT=NO_ACCOUNT_IDENTITY_OR_ORDER_CAPABILITY_ASSERTION")
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
