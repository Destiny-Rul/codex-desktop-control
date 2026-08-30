from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import desktop_controller as controller


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only Codex Desktop Control compatibility doctor")
    parser.add_argument("--offline", action="store_true", help="Do not connect to Desktop IPC or launch any process")
    parser.add_argument("--hermes-home", required=True)
    parser.add_argument("--profile", default="default")
    parser.add_argument("--desktop-codex-home", required=True)
    parser.add_argument("--thread", help="Optional visible thread for an online read-only owner probe")
    args = parser.parse_args()

    report = controller.doctor_report(
        hermes_home=args.hermes_home,
        profile=args.profile,
        desktop_codex_home=args.desktop_codex_home,
        offline=args.offline,
        thread_id=args.thread,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
