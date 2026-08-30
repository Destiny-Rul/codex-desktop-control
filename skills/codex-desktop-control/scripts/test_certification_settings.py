"""Behavioral regression checks for portable certification settings."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


SOURCE = Path(__file__).with_name("desktop_controller.py")


def controller_module():
    spec = importlib.util.spec_from_file_location("desktop_controller_certification_test", SOURCE)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def main() -> None:
    controller = controller_module()
    defaults = controller.parser().parse_args([
        "--hermes-home", "C:/hermes", "--desktop-codex-home", "C:/codex",
        "certify", "--thread", "thread-1",
    ])
    assert (defaults.model, defaults.effort) == ("gpt-5.6-sol", "low")
    overrides = controller.parser().parse_args([
        "--hermes-home", "C:/hermes", "--desktop-codex-home", "C:/codex",
        "certify", "--thread", "thread-1", "--model", "custom-model", "--effort", "high",
    ])
    assert (overrides.model, overrides.effort) == ("custom-model", "high")

    ctx = SimpleNamespace(runtime=Path.cwd() / ".certification-test-runtime")
    eligible = {"title": "test", "archived": False, "model": "old", "effort": "medium"}
    events: list[object] = []

    def inspect(*_args):
        events.append("inspect")
        return dict(eligible)

    def apply(*args):
        events.append(("apply", args[2], args[3]))

    def certify(*args):
        events.append(("certify", args[4], args[5], args[3]["model"], args[3]["effort"]))
        return {"overall_ok": True}

    with patch.object(controller, "certification_thread_info", side_effect=inspect), patch.object(
        controller, "set_thread_settings", side_effect=apply
    ), patch.object(controller, "_certify_build_e2e", side_effect=certify), patch.object(
        controller, "restore_thread_settings"
    ) as restore:
        result = controller.certify_build(ctx, "thread-1", 30, "gpt-5.6-sol", "low")
    assert result == {"overall_ok": True}
    assert events == ["inspect", ("apply", "gpt-5.6-sol", "low"), ("certify", "gpt-5.6-sol", "low", "gpt-5.6-sol", "low")]
    restore.assert_called_once_with(ctx, "thread-1", "gpt-5.6-sol", "low")

    with patch.object(controller, "certification_thread_info", return_value=dict(eligible)), patch.object(
        controller, "set_thread_settings"
    ), patch.object(controller, "_certify_build_e2e", side_effect=RuntimeError("test failure")), patch.object(
        controller, "abort_active_certification_turn"
    ), patch.object(controller, "restore_thread_settings") as restore:
        try:
            controller.certify_build(ctx, "thread-1", 30, "custom-model", "high")
        except RuntimeError as exc:
            assert str(exc) == "test failure"
        else:
            raise AssertionError("failed certification unexpectedly succeeded")
    restore.assert_called_once_with(ctx, "thread-1", "custom-model", "high")

    with patch.object(controller, "run_ipc", return_value={"connected": True}), patch.object(
        controller, "thread_settings_info", return_value={"model": "wrong", "effort": "low"}
    ):
        try:
            controller.set_thread_settings(ctx, "thread-1", "gpt-5.6-sol", "low")
        except RuntimeError as exc:
            assert "readback" in str(exc)
        else:
            raise AssertionError("settings readback mismatch unexpectedly succeeded")

    with patch.object(controller, "certification_thread_info", return_value=dict(eligible)), patch.object(
        controller, "set_thread_settings", side_effect=RuntimeError("write failed")
    ), patch.object(controller, "_certify_build_e2e") as certify:
        try:
            controller.certify_build(ctx, "thread-1", 30, "gpt-5.6-sol", "low")
        except RuntimeError as exc:
            assert str(exc) == "write failed"
        else:
            raise AssertionError("settings write failure unexpectedly certified")
    certify.assert_not_called()

    with patch.object(controller, "certification_thread_info", side_effect=RuntimeError("missing")), patch.object(
        controller, "set_thread_settings"
    ) as apply:
        try:
            controller.certify_build(ctx, "thread-1", 30, "gpt-5.6-sol", "low")
        except RuntimeError:
            pass
        else:
            raise AssertionError("missing thread unexpectedly certified")
    apply.assert_not_called()

    print("PASS: certification defaults, overrides, eligibility ordering, and restoration semantics")


if __name__ == "__main__":
    main()
