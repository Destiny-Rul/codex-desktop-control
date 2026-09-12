"""Exercise the actual bridge settings branch with an in-memory IPC peer."""
from __future__ import annotations

import json
import subprocess
import sys
from test_owner_recovery import bridge_source


def main() -> None:
    node = sys.argv[1] if len(sys.argv) > 1 else "node"
    source = bridge_source()
    start = source.index("  if((input.operation===")
    end = source.index("  process.stdout.write", start)
    branch = source[start:end]
    for operation in ("settings", "send", "steer"):
        for response in ({"resultType": "success", "result": {"applied": True}},
                         {"resultType": "success", "result": {"applied": False}},
                         {"resultType": "success", "result": {}},
                         {"resultType": "success", "result": {"applied": "true"}},
                         {"resultType": "success", "result": {"applied": None}},
                         {"resultType": "error", "result": {"applied": True}}):
            script = "const input=" + json.dumps({"operation": operation, "threadId": "test", "threadSettings": {"model": "m", "effort": "low"}, "params": {}, "startTurnVersion": 2}) + ";"
            script += "const ownerClientId='owner'; let result=null; const calls=[]; const response=" + json.dumps(response) + ";"
            script += "async function sendRequest(method,params,options){calls.push({method,params,options}); return method==='thread-follower-update-thread-settings'?response:{result:{}};}"
            script += "try {" + branch + "; console.log(JSON.stringify({ok:true,calls}));}catch(e){console.log(JSON.stringify({ok:false,calls}));}"
            run = subprocess.run([node, "--input-type=module", "-e", script], capture_output=True, text=True, check=True)
            report = json.loads(run.stdout)
            first = report["calls"][0]
            assert first["options"].get("version") == 2, first
            assert first["params"] == {"conversationId": "test", "threadSettings": {"model": "m", "effort": "low"}}
            expected = response["resultType"] == "success" and response["result"].get("applied") is True
            assert report["ok"] is expected, report
            assert len(report["calls"]) == (2 if expected and operation != "settings" else 1), report
    print("PASS: settings v2 acknowledgement and send/steer fail-closed ordering")


if __name__ == "__main__":
    main()
