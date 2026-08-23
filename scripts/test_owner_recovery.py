"""Regression contract for stale Codex Desktop IPC owners.

Run with:
  terminal(command="python <skill>/scripts/test_owner_recovery.py")

This test intentionally inspects the bundled Node IPC bridge because the
Desktop pipe is an external Windows service. It asserts the bridge waits for a
short quiet period after owner announcements and retries only an explicit
`no-client-found` rejection once; all other failed submissions remain errors.
"""
from __future__ import annotations

import ast
from pathlib import Path


SOURCE = Path(__file__).with_name("desktop_controller.py")


def bridge_source() -> str:
    module = ast.parse(SOURCE.read_text(encoding="utf-8"), filename=str(SOURCE))
    for node in module.body:
        if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == "NODE_BRIDGE" for target in node.targets):
            assert isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)
            return node.value.value
    raise AssertionError("NODE_BRIDGE was not found")


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

    # The only automatic retry is a single, explicitly rejected delivery to a
    # missing target, performed through a fresh IPC connection. Timeouts,
    # malformed responses, and unknown IPC errors remain fail-closed and
    # therefore cannot cause a duplicate turn.
    source = SOURCE.read_text(encoding="utf-8")
    assert "retry_owner_missing: bool = True" in source
    assert "range(2 if retry_owner_missing else 1)" in source
    assert "attempt == 0 and \'no-client-found\' in message" in source

    print("PASS: native owner discovery precedes settled broadcast fallback; only explicit no-client-found retries once")


if __name__ == "__main__":
    main()
