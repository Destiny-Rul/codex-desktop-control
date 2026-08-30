"""Regression contract for stale Codex Desktop IPC owners.

Run with:
  terminal(command="python <skill>/scripts/test_owner_recovery.py")

The owner-discovery fallback is inspected because the Desktop pipe is an
external Windows service. Retry behavior is exercised at the subprocess
boundary: only a validated structured `no-client-found` rejection may retry.
"""
from __future__ import annotations

import ast
import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


SOURCE = Path(__file__).with_name("desktop_controller.py")


def bridge_source() -> str:
    module = ast.parse(SOURCE.read_text(encoding="utf-8"), filename=str(SOURCE))
    for node in module.body:
        if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == "NODE_BRIDGE" for target in node.targets):
            assert isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)
            return node.value.value
    raise AssertionError("NODE_BRIDGE was not found")


def controller_module():
    spec = importlib.util.spec_from_file_location("desktop_controller_owner_test", SOURCE)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def completed(returncode: int, *, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess([], returncode, stdout, stderr)


def exercise(controller, outcomes):
    context = SimpleNamespace(node=Path("node.exe"), runtime=Path.cwd())
    with patch.object(controller, "minimal_environment", return_value={}), patch.object(
        controller.subprocess, "run", side_effect=outcomes
    ) as run:
        try:
            result = controller.run_ipc(context, {"operation": "send"})
        except (RuntimeError, subprocess.TimeoutExpired) as exc:
            return None, str(exc), run.call_count
        return result, None, run.call_count


def main() -> None:
    bridge = bridge_source()
    # A broadcast only says a client is following the thread; it is not the
    # authoritative owner lookup. Newer Desktop builds expose an explicit,
    # read-only discovery request that returns handledByClientId.
    assert "thread-owner-discovery" in bridge
    assert "handledByClientId" in bridge
    assert "await discoverOwner(input.threadId)" in bridge

    # The broadcast remains a timed fallback for older Desktop builds and must
    # not be used immediately: later broadcasts may announce a newer client.
    assert "ownerUpdatedAt" in bridge
    assert "ownerSettleMs" in bridge
    assert "Date.now()-ownerUpdatedAt.get(id)>=ownerSettleMs" in bridge
    assert "if(owners.has(id))return resolve(owners.get(id))" not in bridge

    controller = controller_module()
    explicit = json.dumps({"schema": 1, "type": "ipc-rejection", "reason": "no-client-found"})
    success = json.dumps({"connected": True})

    result, error, calls = exercise(controller, [completed(1, stderr=explicit), completed(0, stdout=success)])
    assert result == {"connected": True} and error is None and calls == 2

    result, error, calls = exercise(controller, [completed(1, stderr="request failed: no-client-found")])
    assert result is None and "no-client-found" in error and calls == 1

    malformed = '{"schema":1,"type":"ipc-rejection","reason":"no-client-found"'
    result, error, calls = exercise(controller, [completed(1, stderr=malformed)])
    assert result is None and "bridge failed" in error and calls == 1

    result, error, calls = exercise(controller, [subprocess.TimeoutExpired(["node"], 55)])
    assert result is None and "timed out" in error and calls == 1

    result, error, calls = exercise(controller, [completed(1, stderr=explicit), completed(1, stderr=explicit)])
    assert result is None and "bridge failed" in error and calls == 2

    print("PASS: native owner discovery precedes settled broadcast fallback; only explicit no-client-found retries once")


if __name__ == "__main__":
    main()
