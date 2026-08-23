"""Read-only diagnostic for Codex Desktop's native owner discovery IPC."""
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

BRIDGE = r"""
import net from 'node:net';
import {randomUUID} from 'node:crypto';
const input=JSON.parse(process.argv[1]);
let socket,buffer=Buffer.alloc(0),clientId=null;
const pending=new Map();
function frame(v){const b=Buffer.from(JSON.stringify(v),'utf8'),h=Buffer.alloc(4);h.writeUInt32LE(b.length,0);socket.write(Buffer.concat([h,b]));}
function request(method,params,opts={}){const requestId=randomUUID();frame({type:'request',requestId,method,params,sourceClientId:opts.sourceClientId||clientId||'initializing-client',version:opts.version??1});return new Promise((resolve,reject)=>{const timer=setTimeout(()=>{pending.delete(requestId);reject(Error('timeout '+method))},10000);pending.set(requestId,{resolve,reject,timer});});}
function receive(v){if(v.type!=='response')return;const p=pending.get(v.requestId);if(!p)return;pending.delete(v.requestId);clearTimeout(p.timer);v.resultType==='error'?p.reject(Error(JSON.stringify(v.error))):p.resolve(v);}
function data(c){buffer=Buffer.concat([buffer,c]);while(buffer.length>=4){const n=buffer.readUInt32LE(0);if(buffer.length<n+4)return;const v=JSON.parse(buffer.subarray(4,n+4));buffer=buffer.subarray(n+4);receive(v);}}
socket=net.createConnection('\\\\.\\pipe\\codex-ipc');socket.on('data',data);await new Promise((yes,no)=>{socket.once('connect',yes);socket.once('error',no)});const init=await request('initialize',{clientType:'farfield'},{sourceClientId:'initializing-client'});clientId=init.result?.clientId;const discovery=await request('thread-owner-discovery',{hostId:'local',conversationId:input.threadId});console.log(JSON.stringify({clientId,discovery}));socket.destroy();
"""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--node", required=True)
    parser.add_argument("--thread", required=True)
    args = parser.parse_args()
    completed = subprocess.run(
        [args.node, "--input-type=module", "-e", BRIDGE, json.dumps({"threadId": args.thread})],
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )
    if completed.returncode:
        raise SystemExit(completed.stderr.strip() or completed.stdout.strip())
    payload = json.loads(completed.stdout)
    if not isinstance(payload.get("discovery", {}).get("handledByClientId"), str):
        raise SystemExit(f"unexpected owner discovery response: {completed.stdout}")
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
