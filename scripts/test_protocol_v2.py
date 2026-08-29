"""Offline regression checks for Codex Desktop IPC v2 safety."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


SOURCE = Path(__file__).with_name("desktop_controller.py")


def controller_module():
    spec = importlib.util.spec_from_file_location("desktop_controller_test", SOURCE)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def main() -> None:
    controller = controller_module()
    request = controller.build_turn_request("thread-1", "hello", "model-1", "high", False)

    assert "turnStartParams" not in request
    assert request["conversationId"] == "thread-1"
    turn_start = request["turnStart"]
    assert turn_start["request"]["threadId"] == "thread-1"
    assert turn_start["request"]["input"] == [{"type": "text", "text": "hello"}]
    assert turn_start["request"]["model"] == "model-1"
    assert turn_start["request"]["effort"] == "high"
    assert turn_start["context"]["attachments"] == []
    assert turn_start["context"]["inheritThreadSettings"] is True

    source = SOURCE.read_text(encoding="utf-8")
    assert '"startTurnVersion": 2' in source
    assert "version:input.startTurnVersion??1" in source
    assert "if(String(error).includes('no-client-found'))throw error;" in source
    assert "if(!String(error).includes('no-handler-for-request'))throw error;" in source

    exact = {"status": "completed", "final_response": "CODEX_DESKTOP_CERT_STEER_OK"}
    padded = {"status": "completed", "final_response": "CODEX_DESKTOP_CERT_STEER_OK\n\n"}
    extra = {"status": "completed", "final_response": "prefix CODEX_DESKTOP_CERT_STEER_OK"}
    assert controller._certification_result(exact, status="completed", response="CODEX_DESKTOP_CERT_STEER_OK")["ok"]
    assert controller._certification_result(padded, status="completed", response="CODEX_DESKTOP_CERT_STEER_OK")["ok"]
    assert not controller._certification_result(extra, status="completed", response="CODEX_DESKTOP_CERT_STEER_OK")["ok"]

    print("PASS: IPC v2, owner fail-closed, and certification response normalization")


if __name__ == "__main__":
    main()
