from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import math
import mmap
import os
import re
import sqlite3
import struct
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SKILL_ROOT = Path(__file__).resolve().parent.parent
LOCK_PATH = SKILL_ROOT / "references" / "dependencies.lock.json"
PIPE_PATH = r"\\.\pipe\codex-ipc"
MAX_FRAME = 32 * 1024 * 1024
TERMINAL_STATUSES = {"completed", "failed", "interrupted"}
PROFILE_CHARS = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-")
PROFILE_FIRST_CHARS = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789")
ID_CHARS = PROFILE_CHARS


@dataclass(frozen=True)
class Context:
    hermes_home: Path
    profile: str
    runtime: Path
    desktop_home: Path
    jobs: Path
    tmp: Path
    tools: Path
    node: Path
    lock: dict[str, Any]


def _absolute(value: str | Path, label: str, *, must_exist: bool = False) -> Path:
    raw = Path(value)
    if not raw.is_absolute():
        raise ValueError(f"{label} must be an absolute path")
    try:
        return raw.resolve(strict=must_exist)
    except OSError as exc:
        raise ValueError(f"{label} cannot be resolved: {raw}") from exc


def _safe_profile(value: str) -> str:
    if not value or len(value) > 64 or value[0] not in PROFILE_FIRST_CHARS or any(c not in PROFILE_CHARS for c in value):
        raise ValueError("Profile must contain only ASCII letters, digits, underscore, or hyphen")
    return value


def _is_within(child: Path, parent: Path) -> bool:
    try:
        return os.path.commonpath([os.path.normcase(str(child)), os.path.normcase(str(parent))]) == os.path.normcase(str(parent))
    except ValueError:
        return False


def load_lock() -> dict[str, Any]:
    data = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    if data.get("format_version") != 1 or data.get("platform") != "windows-x86_64":
        raise RuntimeError("Unsupported dependency lock format or platform")
    return data


def resolve_context(*, hermes_home: str | Path, profile: str, desktop_codex_home: str | Path) -> Context:
    hermes = _absolute(hermes_home, "Hermes home")
    desktop = _absolute(desktop_codex_home, "Desktop Codex home")
    profile = _safe_profile(profile)
    profiles_root = (hermes / "skill-data" / "codex-desktop-control" / "profiles").resolve(strict=False)
    runtime = (profiles_root / profile).resolve(strict=False)
    if not _is_within(runtime, profiles_root) or runtime == profiles_root:
        raise ValueError("Profile runtime escaped the Hermes skill-data root")
    tools = runtime / "tools"
    return Context(
        hermes_home=hermes,
        profile=profile,
        runtime=runtime,
        desktop_home=desktop,
        jobs=runtime / "jobs",
        tmp=runtime / "tmp",
        tools=tools,
        node=tools / "node" / "node.exe",
        lock=load_lock(),
    )


def ensure_runtime_layout(ctx: Context) -> None:
    for path in (ctx.runtime, ctx.jobs, ctx.tmp):
        path.mkdir(parents=True, exist_ok=True)
        if not _is_within(path.resolve(strict=True), ctx.runtime.resolve(strict=True)):
            raise RuntimeError(f"Runtime path escaped the selected profile: {path}")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def scan_protocol_payload(path: Path, contract: dict[str, Any]) -> dict[str, Any]:
    payload_path = Path(path).resolve(strict=True)
    required_anchors = [str(value) for value in contract.get("required_anchors", [])]
    expected_versions = {
        str(name): int(version)
        for name, version in dict(contract.get("method_versions", {})).items()
    }
    issues: list[str] = []
    anchors: dict[str, bool] = {}
    versions: dict[str, int] = {}
    with payload_path.open("rb") as handle:
        if payload_path.stat().st_size == 0:
            issues.append("Desktop protocol payload is empty")
        else:
            with mmap.mmap(handle.fileno(), 0, access=mmap.ACCESS_READ) as payload:
                for anchor in required_anchors:
                    present = payload.find(anchor.encode("utf-8")) >= 0
                    anchors[anchor] = present
                    if not present:
                        issues.append(f"missing protocol anchor: {anchor}")
                for method, expected in expected_versions.items():
                    pattern = re.compile(rb'["`]' + re.escape(method.encode("utf-8")) + rb'["`]\s*:\s*(\d+)')
                    observed = sorted({int(value) for value in pattern.findall(payload)})
                    if observed == [expected]:
                        versions[method] = expected
                    else:
                        issues.append(f"protocol method version mismatch for {method}: expected {expected}, observed {observed}")
    fingerprint = {
        "anchors": {name: anchors.get(name, False) for name in sorted(required_anchors)},
        "method_versions": {name: versions.get(name) for name in sorted(expected_versions)},
    }
    encoded = json.dumps(fingerprint, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return {
        "ok": not issues,
        "issues": issues,
        "payload": str(payload_path),
        "payload_sha256": sha256_file(payload_path),
        "fingerprint_sha256": hashlib.sha256(encoded).hexdigest(),
        "anchors": anchors,
        "method_versions": versions,
    }


def _migration_rows(connection: sqlite3.Connection) -> list[tuple[Any, ...]]:
    tables = {str(row[0]) for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if "_sqlx_migrations" not in tables:
        raise RuntimeError("Codex state database has no _sqlx_migrations table")
    result: list[tuple[Any, ...]] = []
    for row in connection.execute("SELECT version, description, success, checksum FROM _sqlx_migrations ORDER BY version"):
        checksum = bytes(row[3]).hex() if row[3] is not None else None
        result.append((row[0], row[1], row[2], checksum))
    return result


def schema_report(ctx: Context) -> dict[str, Any]:
    database = ctx.desktop_home / str(ctx.lock["desktop_compatibility"]["state_database"])
    report: dict[str, Any] = {"database": str(database), "ok": False, "issues": [], "warnings": [], "drift": False}
    if not database.is_file():
        report["issues"].append("state database missing")
        return report
    try:
        connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
        try:
            quick = str(connection.execute("PRAGMA quick_check").fetchone()[0])
            columns = {str(row[1]) for row in connection.execute("PRAGMA table_info(threads)")}
            missing = sorted(set(ctx.lock["desktop_compatibility"]["required_thread_columns"]) - columns)
            rows = _migration_rows(connection)
        finally:
            connection.close()
        payload = json.dumps(rows, ensure_ascii=False, separators=(",", ":"))
        migration_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        all_migrations_successful = bool(rows) and all(bool(row[2]) for row in rows)
        report.update({
            "quick_check": quick,
            "migration_count": len(rows),
            "migration_sha256": migration_hash,
            "all_migrations_successful": all_migrations_successful,
        })
        if quick != "ok":
            report["issues"].append(f"quick_check={quick}")
        if missing:
            report["issues"].append("missing thread columns: " + ", ".join(missing))
        if not all_migrations_successful:
            report["issues"].append("one or more database migrations are missing or unsuccessful")
        expected = ctx.lock["desktop_compatibility"]
        if len(rows) != int(expected["migration_count"]):
            report["drift"] = True
            report["warnings"].append("migration count changed; write capabilities require recertification")
        if migration_hash != expected["migration_sha256"]:
            report["drift"] = True
            report["warnings"].append("migration fingerprint changed; write capabilities require recertification")
    except Exception as exc:
        report["issues"].append(f"{type(exc).__name__}: {exc}")
    report["ok"] = not report["issues"]
    return report


def dependency_report(ctx: Context, capability: str | None = None) -> dict[str, Any]:
    manifest_path = ctx.tools / "install-manifest.json"
    report: dict[str, Any] = {"manifest": str(manifest_path), "ok": False, "issues": [], "files": {}}
    required = {"node": ctx.node}
    if not manifest_path.is_file():
        report["issues"].append("private dependency install manifest missing")
        manifest: dict[str, Any] = {}
    else:
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
        except Exception as exc:
            report["issues"].append(f"invalid install manifest: {exc}")
            manifest = {}
    if manifest.get("format_version") != 1:
        report["issues"].append("install manifest format is unsupported")
    if manifest.get("profile") != ctx.profile:
        report["issues"].append("install manifest profile does not match selected profile")
    lock_hash = sha256_file(LOCK_PATH)
    if manifest.get("lock_sha256") != lock_hash:
        report["issues"].append("install manifest does not match dependency lock")
    manifest_files = manifest.get("files") if isinstance(manifest.get("files"), dict) else {}
    expected_hashes = {"node": ctx.lock["node"]["executable_sha256"]}
    rels = {"node": "node/node.exe"}
    for name, path in required.items():
        entry: dict[str, Any] = {"path": str(path), "exists": path.is_file()}
        report["files"][name] = entry
        if not path.is_file():
            report["issues"].append(f"private {name} executable missing")
            continue
        actual = sha256_file(path)
        entry["sha256"] = actual
        manifest_hash = manifest_files.get(rels[name])
        if not isinstance(manifest_hash, str) or actual != manifest_hash.lower():
            report["issues"].append(f"private {name} differs from install manifest")
        if name in expected_hashes and actual != expected_hashes[name]:
            report["issues"].append(f"private {name} differs from dependency lock")
    report["ok"] = not report["issues"]
    return report


def runtime_hygiene_report(ctx: Context) -> dict[str, Any]:
    if not ctx.runtime.exists():
        return {"ok": True, "issues": [], "bootstrap_staging": [], "previous_tools": [], "bootstrap_lock": False}
    staging = sorted(path.name for path in ctx.runtime.glob(".bootstrap-*") if path.is_dir())
    previous = sorted(path.name for path in ctx.runtime.glob(".tools-previous-*") if path.is_dir())
    lock_exists = (ctx.runtime / ".bootstrap.lock").exists()
    issues: list[str] = []
    if lock_exists:
        issues.append("bootstrap lock exists")
    if staging:
        issues.append("stale bootstrap staging exists")
    if previous:
        issues.append("unresolved previous tools directory exists")
    return {"ok": not issues, "issues": issues, "bootstrap_staging": staging, "previous_tools": previous, "bootstrap_lock": lock_exists}


def protocol_contract_sha256(ctx: Context) -> str:
    contract = ctx.lock["desktop_compatibility"]["protocol_contract"]
    encoded = json.dumps(contract, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def compatibility_identity(ctx: Context, desktop: dict[str, Any], schema: dict[str, Any]) -> dict[str, Any]:
    build = desktop.get("build")
    if not isinstance(build, dict) or not desktop.get("ok") or not schema.get("ok"):
        raise RuntimeError("Cannot identify an incompatible Desktop build or schema")
    return {
        "skill_version": str(ctx.lock["skill_version"]),
        "protocol_contract_sha256": protocol_contract_sha256(ctx),
        "desktop_version": str(build["version"]),
        "desktop_executable_sha256": str(build["desktop_executable_sha256"]),
        "desktop_protocol_payload_sha256": str(build["desktop_protocol_payload_sha256"]),
        "protocol_fingerprint_sha256": str(build["protocol_fingerprint_sha256"]),
        "migration_count": int(schema["migration_count"]),
        "migration_sha256": str(schema["migration_sha256"]),
    }


def certification_path(ctx: Context) -> Path:
    return ctx.runtime / "certification" / "desktop-build.json"


def certification_report(ctx: Context, identity: dict[str, Any]) -> dict[str, Any]:
    path = certification_path(ctx)
    report: dict[str, Any] = {"certified": False, "path": str(path), "issues": []}
    if not path.is_file():
        report["issues"].append("certification receipt is missing")
        return report
    try:
        receipt = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        report["issues"].append(f"invalid certification receipt: {exc}")
        return report
    if not isinstance(receipt, dict) or receipt.get("format_version") != 1:
        report["issues"].append("certification receipt format is unsupported")
        return report
    if receipt.get("identity") != identity:
        report["issues"].append("certification receipt does not match the current Desktop build and schema")
    checks = receipt.get("checks") if isinstance(receipt.get("checks"), dict) else {}
    for name in ("probe", "send_wait_status", "settings_round_trip", "steer", "interrupt", "final_probe"):
        value = checks.get(name)
        if not isinstance(value, dict) or value.get("ok") is not True:
            report["issues"].append(f"certification receipt is missing a successful {name} check")
    if receipt.get("overall_ok") is not True:
        report["issues"].append("certification receipt is not successful")
    thread_id = receipt.get("certification_thread_id")
    if not isinstance(thread_id, str) or not thread_id:
        report["issues"].append("certification receipt has no test thread")
    report["certified"] = not report["issues"]
    if report["certified"]:
        report["certification_thread_id"] = thread_id
        report["certified_at_utc"] = receipt.get("certified_at_utc")
    return report


def platform_report() -> dict[str, Any]:
    architecture = os.environ.get("PROCESSOR_ARCHITECTURE", "")
    python_ok = sys.version_info >= (3, 11) and struct.calcsize("P") == 8
    architecture_ok = architecture.upper() in {"AMD64", "X86_64"}
    return {
        "ok": os.name == "nt" and architecture_ok and python_ok,
        "os_name": os.name,
        "architecture": architecture,
        "python": ".".join(str(part) for part in sys.version_info[:3]),
        "python_64bit": struct.calcsize("P") == 8,
    }


def _process_image(pid: int) -> Path | None:
    if os.name != "nt":
        return None
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    handle = kernel32.OpenProcess(0x1000, False, pid)
    if not handle:
        return None
    try:
        size = wintypes.DWORD(32768)
        buffer = ctypes.create_unicode_buffer(size.value)
        if not kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
            return None
        return Path(buffer.value).resolve(strict=True)
    finally:
        kernel32.CloseHandle(handle)


def _running_processes_by_name(executable_name: str) -> list[tuple[int, Path | None]]:
    if os.name != "nt":
        return []
    from ctypes import wintypes

    class PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.c_size_t),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", wintypes.LONG),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", wintypes.WCHAR * 260),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
    kernel32.Process32FirstW.restype = wintypes.BOOL
    kernel32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
    kernel32.Process32NextW.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    snapshot = kernel32.CreateToolhelp32Snapshot(0x00000002, 0)
    invalid_handle = wintypes.HANDLE(-1).value
    if snapshot == invalid_handle:
        raise OSError(ctypes.get_last_error(), "Cannot enumerate Desktop processes")
    entry = PROCESSENTRY32W()
    entry.dwSize = ctypes.sizeof(entry)
    result: list[tuple[int, Path | None]] = []
    try:
        ok = kernel32.Process32FirstW(snapshot, ctypes.byref(entry))
        while ok:
            if str(entry.szExeFile).lower() == executable_name.lower():
                pid = int(entry.th32ProcessID)
                result.append((pid, _process_image(pid)))
            ok = kernel32.Process32NextW(snapshot, ctypes.byref(entry))
    finally:
        kernel32.CloseHandle(snapshot)
    return result


def desktop_process_report(ctx: Context) -> dict[str, Any]:
    expected = ctx.lock["desktop_compatibility"]
    executable = str(expected["desktop_executable"])
    install_root_raw = Path(str(expected["desktop_install_root"]))
    if not install_root_raw.is_absolute():
        raise RuntimeError("Locked Desktop install root is not absolute")
    install_root = Path(os.path.normpath(str(install_root_raw)))
    publisher_id = str(expected["desktop_publisher_id"])
    payload_relative = Path(str(expected["desktop_protocol_payload"]))
    protocol_contract = dict(expected["protocol_contract"])
    reference_build = dict(expected["reference_build"])
    if payload_relative.is_absolute() or ".." in payload_relative.parts:
        raise RuntimeError("Locked Desktop protocol payload path is unsafe")
    processes = _running_processes_by_name(executable)
    details: list[dict[str, Any]] = []
    issues: list[str] = []
    hash_cache: dict[Path, str] = {}
    protocol_cache: dict[Path, dict[str, Any]] = {}
    builds: dict[tuple[str, str, str, str], dict[str, Any]] = {}

    def verified_hash(path: Path) -> str:
        if path not in hash_cache:
            hash_cache[path] = sha256_file(path)
        return hash_cache[path]

    for pid, image in processes:
        detail: dict[str, Any] = {"pid": pid, "image": str(image) if image else None}
        if image is not None and image.name.lower() == executable.lower() and image.parent.name.lower() == "app":
            package_dir = image.parent.parent
            if package_dir.parent == install_root:
                match = re.fullmatch(rf"OpenAI\.Codex_([^_]+)_x64__{re.escape(publisher_id)}", package_dir.name, re.IGNORECASE)
                if match:
                    version = match.group(1)
                    payload_path = package_dir / payload_relative
                    try:
                        executable_hash = verified_hash(image)
                        if payload_path not in protocol_cache:
                            protocol_cache[payload_path] = scan_protocol_payload(payload_path, protocol_contract)
                        protocol = protocol_cache[payload_path]
                    except (OSError, ValueError) as exc:
                        issues.append(f"cannot inspect Desktop build for PID {pid}: {exc}")
                    else:
                        detail.update({
                            "version": version,
                            "executable_sha256": executable_hash,
                            "protocol_payload": str(payload_path),
                            "protocol_payload_sha256": protocol["payload_sha256"],
                            "protocol_fingerprint_sha256": protocol["fingerprint_sha256"],
                            "protocol_ok": protocol["ok"],
                        })
                        if not protocol["ok"]:
                            issues.extend(f"PID {pid}: {issue}" for issue in protocol["issues"])
                        else:
                            key = (version, executable_hash, protocol["payload_sha256"], protocol["fingerprint_sha256"])
                            builds[key] = {
                                "version": version,
                                "desktop_executable_sha256": executable_hash,
                                "desktop_protocol_payload_sha256": protocol["payload_sha256"],
                                "protocol_fingerprint_sha256": protocol["fingerprint_sha256"],
                                "reference_build": (
                                    version == reference_build["version"]
                                    and executable_hash == reference_build["desktop_executable_sha256"]
                                    and protocol["payload_sha256"] == reference_build["desktop_protocol_payload_sha256"]
                                    and protocol["fingerprint_sha256"] == reference_build["protocol_fingerprint_sha256"]
                                ),
                            }
        details.append(detail)
        if "version" not in detail:
            issues.append(f"cannot verify Desktop image/version for PID {pid}")
    if not processes:
        issues.append(f"{executable} is not running")
    if len(builds) > 1:
        issues.append("multiple distinct Codex Desktop builds are running")
    build = next(iter(builds.values())) if len(builds) == 1 else None
    return {
        "ok": not issues and build is not None,
        "compatibility": "structurally-compatible" if not issues and build is not None else "incompatible",
        "build": build,
        "processes": details,
        "issues": issues,
    }


def compatibility_gate(ctx: Context, capability: str) -> None:
    platform = platform_report()
    if not platform["ok"]:
        raise RuntimeError("This Skill requires Windows x86-64 and 64-bit Python 3.11 or newer")
    desktop: dict[str, Any] | None = None
    if capability in {"probe", "certify", "send", "steer", "interrupt"}:
        desktop = desktop_process_report(ctx)
        if not desktop["ok"]:
            raise RuntimeError("Desktop protocol compatibility gate failed: " + "; ".join(desktop["issues"]))
    hygiene = runtime_hygiene_report(ctx)
    if not hygiene["ok"]:
        raise RuntimeError("Private runtime hygiene gate failed: " + "; ".join(hygiene["issues"]))
    schema = schema_report(ctx)
    if not schema["ok"]:
        raise RuntimeError("Desktop schema compatibility gate failed: " + "; ".join(schema["issues"]))
    deps = dependency_report(ctx, capability)
    if not deps["ok"]:
        raise RuntimeError("Private dependency gate failed: " + "; ".join(deps["issues"]))
    if capability in {"send", "steer", "interrupt"}:
        assert desktop is not None
        identity = compatibility_identity(ctx, desktop, schema)
        certification = certification_report(ctx, identity)
        if not certification["certified"]:
            raise RuntimeError("Desktop write certification gate failed: " + "; ".join(certification["issues"]))


def minimal_environment(ctx: Context) -> dict[str, str]:
    allowed = ("SystemRoot", "WINDIR", "COMSPEC", "NUMBER_OF_PROCESSORS", "PROCESSOR_ARCHITECTURE")
    env = {key: os.environ[key] for key in allowed if key in os.environ}
    env.update({"TEMP": str(ctx.tmp), "TMP": str(ctx.tmp), "TMPDIR": str(ctx.tmp), "NO_PROXY": "127.0.0.1,localhost"})
    return env


NODE_BRIDGE = r"""
import fs from 'node:fs';
import net from 'node:net';
import { randomUUID } from 'node:crypto';
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const owners = new Map();
const ownerUpdatedAt = new Map();
const OWNER_SETTLE_MS = 250;
const pending = new Map();
let socket, buffer = Buffer.alloc(0), clientId = null;
function writeFrame(frame) { const body = Buffer.from(JSON.stringify(frame), 'utf8'); const header = Buffer.alloc(4); header.writeUInt32LE(body.length, 0); socket.write(Buffer.concat([header, body])); }
function sendRequest(method, params, options = {}) {
  const requestId = randomUUID();
  const frame = {type:'request', requestId, method, params, sourceClientId:options.sourceClientId || clientId || 'initializing-client', version:options.version ?? 1};
  if (options.targetClientId) frame.targetClientId = options.targetClientId;
  const promise = new Promise((resolve,reject) => { const timer=setTimeout(()=>{pending.delete(requestId);reject(new Error(`IPC request timed out: ${method}`));},options.timeoutMs||20000);pending.set(requestId,{resolve,reject,timer,method}); });
  writeFrame(frame); return promise;
}
function handleFrame(frame) {
  if (frame.type==='client-discovery-request') { writeFrame({type:'client-discovery-response',requestId:frame.requestId,response:{canHandle:false}}); return; }
  if (frame.type==='request') { writeFrame({type:'response',requestId:frame.requestId,resultType:'error',error:'no-handler-for-request'}); return; }
  if (frame.type==='broadcast' && frame.method==='thread-stream-following-changed' && frame.params?.following===true && frame.sourceClientId) { const id=frame.params.conversationId||frame.params.threadId; if(id) { owners.set(id,frame.sourceClientId); ownerUpdatedAt.set(id,Date.now()); } }
  if (frame.type!=='response') return; const item=pending.get(frame.requestId); if(!item) return; pending.delete(frame.requestId); clearTimeout(item.timer);
  if(frame.resultType==='error') item.reject(new Error(`IPC ${item.method} failed: ${JSON.stringify(frame.error)}`)); else item.resolve(frame);
}
function handleData(chunk) { buffer=Buffer.concat([buffer,chunk]); while(buffer.length>=4){const size=buffer.readUInt32LE(0);if(size>32*1024*1024)throw new Error(`IPC frame too large: ${size}`);if(buffer.length<size+4)return;const frame=JSON.parse(buffer.subarray(4,size+4).toString('utf8'));buffer=buffer.subarray(size+4);handleFrame(frame);} }
function waitForOwner(id,timeoutMs=7000,ownerSettleMs=OWNER_SETTLE_MS){return new Promise((resolve,reject)=>{const deadline=Date.now()+timeoutMs;const timer=setInterval(()=>{const owner=owners.get(id);if(owner && Date.now()-ownerUpdatedAt.get(id)>=ownerSettleMs){clearInterval(timer);resolve(owner);}else if(Date.now()>=deadline){clearInterval(timer);reject(new Error(`No visible Codex Desktop owner announced thread ${id}`));}},20);});}
async function discoverOwner(id){const response=await sendRequest('thread-owner-discovery',{hostId:'local',conversationId:id});return typeof response.handledByClientId==='string'&&response.handledByClientId.length>0?response.handledByClientId:null;}
async function main(){
  socket=net.createConnection(input.pipe);socket.on('data',handleData);await new Promise((resolve,reject)=>{socket.once('connect',resolve);socket.once('error',reject);});
  const init=await sendRequest('initialize',{clientType:'farfield'},{sourceClientId:'initializing-client'});clientId=init?.result?.clientId;if(!clientId)throw new Error('IPC initialize did not return clientId');
  let ownerClientId;try{ownerClientId=await discoverOwner(input.threadId)}catch(error){if(String(error).includes('no-client-found'))throw error;if(!String(error).includes('no-handler-for-request'))throw error;}if(!ownerClientId)ownerClientId=await waitForOwner(input.threadId);let result=null;
  if((input.operation==='send' || input.operation==='steer' || input.operation==='settings') && input.threadSettings && Object.keys(input.threadSettings).length>0){
    await sendRequest('thread-follower-update-thread-settings',{conversationId:input.threadId,threadSettings:input.threadSettings},{targetClientId:ownerClientId});
  }
  if(input.operation==='send'){
    const response=await sendRequest('thread-follower-start-turn',input.params,{targetClientId:ownerClientId,version:input.startTurnVersion??1});result=response.result??null;
  } else if(input.operation==='steer'){
    const response=await sendRequest('thread-follower-steer-turn',input.params,{targetClientId:ownerClientId});result=response.result??null;
  } else if(input.operation==='interrupt'){
    const response=await sendRequest('thread-follower-interrupt-turn',input.params,{targetClientId:ownerClientId,version:4});result=response.result??null;
  }
  process.stdout.write(JSON.stringify({connected:true,threadId:input.threadId,clientId,ownerClientId,result}));socket.destroy();
}
main().catch(error=>{if(socket)socket.destroy();process.stderr.write(error?.stack||String(error));process.exitCode=1;});
"""


def run_ipc(ctx: Context, payload: dict[str, Any], timeout: float = 55, retry_owner_missing: bool = True) -> dict[str, Any]:
    """Run an IPC request with one fresh-connection recovery for a dead owner.

    `no-client-found` is an explicit negative acknowledgement: the addressed
    Desktop client no longer exists and therefore cannot have created a turn.
    Only that response may be retried, once, on a new pipe connection. Every
    timeout, malformed response, and other IPC failure remains fail-closed.
    """
    for attempt in range(2 if retry_owner_missing else 1):
        completed = subprocess.run(
            [str(ctx.node), "--input-type=module", "-e", NODE_BRIDGE],
            input=json.dumps(payload, ensure_ascii=False), text=True, capture_output=True, timeout=timeout,
            cwd=ctx.runtime, env=minimal_environment(ctx),
        )
        if completed.returncode == 0:
            try:
                result = json.loads(completed.stdout)
            except json.JSONDecodeError as exc:
                raise RuntimeError("Codex Desktop IPC bridge returned malformed JSON") from exc
            if not isinstance(result, dict):
                raise RuntimeError("Codex Desktop IPC bridge returned a non-object result")
            return result
        message = completed.stderr.strip() or completed.stdout.strip() or f"exit {completed.returncode}"
        if attempt == 0 and 'no-client-found' in message:
            continue
        raise RuntimeError(f"Codex Desktop IPC bridge failed: {message}")
    raise AssertionError("unreachable")


def _validate_rollout_path(home: Path, rollout_path: str | Path) -> Path:
    raw = str(rollout_path)
    if os.name == "nt" and raw.lower().startswith("\\\\?\\unc\\"):
        raise RuntimeError("UNC rollout paths are not allowed")
    if os.name == "nt" and raw.startswith("\\\\?\\"):
        raw = raw[4:]
    if raw.startswith("\\\\") and not raw.startswith("\\\\?\\"):
        raise RuntimeError("UNC rollout paths are not allowed")
    candidate = Path(raw).resolve(strict=True)
    roots = ((home / "sessions").resolve(strict=False), (home / "archived_sessions").resolve(strict=False))
    if not any(_is_within(candidate, root) for root in roots):
        raise RuntimeError(f"Rollout path escaped Desktop session roots: {candidate}")
    return candidate


def _database(ctx: Context) -> Path:
    return ctx.desktop_home / str(ctx.lock["desktop_compatibility"]["state_database"])


def find_rollout(ctx: Context, thread_id: str) -> Path | None:
    connection = sqlite3.connect(f"file:{_database(ctx)}?mode=ro", uri=True)
    try:
        row = connection.execute("SELECT rollout_path FROM threads WHERE id=?", (thread_id,)).fetchone()
    finally:
        connection.close()
    return _validate_rollout_path(ctx.desktop_home, row[0]) if row and row[0] else None


def thread_cwd(ctx: Context, thread_id: str) -> str:
    connection = sqlite3.connect(f"file:{_database(ctx)}?mode=ro", uri=True)
    try:
        row = connection.execute("SELECT cwd FROM threads WHERE id=?", (thread_id,)).fetchone()
    finally:
        connection.close()
    if row is None or not isinstance(row[0], str) or not row[0]:
        raise RuntimeError("Desktop thread has no verified cwd")
    return str(_absolute(row[0], "Desktop thread cwd", must_exist=True))


def _safe_id(value: str, label: str) -> str:
    if not value or len(value) > 128 or any(c not in ID_CHARS for c in value):
        raise ValueError(f"Invalid {label}")
    return value


def _valid_turn_id(value: Any) -> bool:
    return isinstance(value, str) and 0 < len(value) <= 128 and all(character in ID_CHARS for character in value)


def _job_path(ctx: Context, job_id: str) -> Path:
    return ctx.jobs / f"{_safe_id(job_id, 'job id')}.json"


def _atomic_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def save_job(ctx: Context, job: dict[str, Any]) -> None:
    _atomic_json(_job_path(ctx, str(job["job_id"])), job)


def load_job(ctx: Context, job_id: str) -> dict[str, Any]:
    data = json.loads(_job_path(ctx, job_id).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise RuntimeError("Desktop job is not a JSON object")
    return data


def normalize_event(record: dict[str, Any]) -> dict[str, Any] | None:
    if record.get("type") != "event_msg" or not isinstance(record.get("payload"), dict):
        return None
    payload = record["payload"]
    kind = payload.get("type")
    if kind == "task_started":
        return {"event": "turn.started", "turn_id": payload.get("turn_id")}
    if kind == "agent_message":
        return {"event": "agent.message", "message": payload.get("message"), "phase": payload.get("phase")}
    if kind == "task_complete":
        return {"event": "turn.completed", "turn_id": payload.get("turn_id"), "final_response": payload.get("last_agent_message"), "duration_ms": payload.get("duration_ms")}
    if kind == "task_failed":
        return {"event": "turn.failed", "turn_id": payload.get("turn_id"), "error": payload.get("message") or payload.get("error") or kind}
    if kind in {"turn_aborted", "turn_interrupted"}:
        return {"event": "turn.interrupted", "turn_id": payload.get("turn_id"), "error": payload.get("message") or payload.get("error") or kind}
    return None


def read_events(path: Path, baseline: int) -> list[dict[str, Any]]:
    if path.stat().st_size < baseline:
        raise RuntimeError("Rollout was truncated below the job baseline")
    events: list[dict[str, Any]] = []
    with path.open("rb") as handle:
        handle.seek(baseline)
        for raw in handle:
            if not raw.endswith(b"\n"):
                continue
            try:
                record = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise RuntimeError("Malformed complete JSONL record in rollout") from exc
            event = normalize_event(record)
            if event:
                if event["event"] in {"turn.started", "turn.completed", "turn.failed", "turn.interrupted"} and not _valid_turn_id(event.get("turn_id")):
                    raise RuntimeError("Turn lifecycle event is missing a valid turn ID")
                events.append(event)
    return events


def _validated_job_rollout(ctx: Context, job: dict[str, Any]) -> Path:
    mapped = find_rollout(ctx, str(job["thread_id"]))
    stored = _validate_rollout_path(ctx.desktop_home, str(job["rollout_path"]))
    if mapped is None or os.path.normcase(str(mapped)) != os.path.normcase(str(stored)):
        raise RuntimeError("Job rollout no longer matches the Desktop database")
    return stored


def summarize_job(ctx: Context, job: dict[str, Any]) -> dict[str, Any]:
    events = read_events(_validated_job_rollout(ctx, job), int(job.get("baseline_offset", 0)))
    target = job.get("accepted_turn_id") or job.get("target_turn_id")
    active = bool(job.get("target_active_at_baseline"))
    status = "running" if active else str(job.get("submission_status") or "submitted")
    if status == "accepted":
        status = "submitted"
    scoped: list[dict[str, Any]] = []
    candidates: list[str] = []
    final_response = None
    error = job.get("submission_error") if status == "uncertain" else None
    last_message = None
    for event in events:
        event_id = event.get("turn_id")
        if event["event"] == "turn.started":
            if isinstance(event_id, str) and event_id not in candidates:
                candidates.append(event_id)
            if target is None or event_id != target:
                continue
            active, status, error = True, "running", None
            scoped.append(event)
        elif event["event"] == "agent.message" and active:
            scoped.append(event)
            if event.get("message"):
                last_message = event["message"]
        elif event["event"] in {"turn.completed", "turn.failed", "turn.interrupted"} and event_id == target:
            scoped.append(event)
            active = False
            if event["event"] == "turn.completed":
                status, final_response, error = "completed", event.get("final_response") or last_message, None
            elif event["event"] == "turn.failed":
                status, error = "failed", event.get("error")
            else:
                status, error = "interrupted", event.get("error")
            break
    return {**job, "status": status, "turn_id": target, "final_response": final_response, "error": error, "events": scoped, "reconcile_candidates": candidates if job.get("submission_status") == "uncertain" else []}


def reconcile_job(ctx: Context, job: dict[str, Any], turn_id: str) -> dict[str, Any]:
    if job.get("submission_status") != "uncertain":
        raise RuntimeError("Only an uncertain job can be reconciled")
    candidates = summarize_job(ctx, job)["reconcile_candidates"]
    if turn_id not in candidates:
        raise RuntimeError("Requested reconcile turn is not a post-baseline candidate")
    if len(candidates) != 1:
        raise RuntimeError("Uncertain job has ambiguous candidate turns; reconciliation is fail-closed")
    job["accepted_turn_id"] = turn_id
    job["submission_status"] = "accepted"
    job["reconciled_at"] = datetime.now(timezone.utc).isoformat()
    job.pop("submission_error", None)
    save_job(ctx, job)
    return summarize_job(ctx, job)


def build_turn_request(thread_id: str, prompt: str, model: str | None, effort: str | None, steering: bool) -> dict[str, Any]:
    request: dict[str, Any] = {
        "threadId": thread_id,
        "input": [{"type": "text", "text": prompt}],
        "attachments": [],
        "clientUserMessageId": str(uuid.uuid4()),
        "additionalContext": {},
    }
    if model is not None:
        request["model"] = model
    if effort is not None:
        request["effort"] = effort
    context = {
        "localTurnMetadata": None,
        "attachments": [],
        "commentAttachments": [],
        "useAppServerPermissionDefault": False,
        "usePermissionSelection": False,
        "inheritThreadSettings": True,
        "threadStartKind": "default",
        "mcpAppModelContextAttachments": [],
    }
    return {"conversationId": thread_id, "turnStart": {"request": request, "context": context}, "isSteering": steering}


def build_steer_request(thread_id: str, prompt: str, expected_turn_id: str, cwd: str) -> dict[str, Any]:
    return {
        "conversationId": thread_id,
        "expectedTurnId": expected_turn_id,
        "input": [{"type": "text", "text": prompt, "text_elements": []}],
        "restoreMessage": {
            "cwd": cwd,
            "context": {"workspaceRoots": [cwd], "collaborationMode": None},
            "responsesapiClientMetadata": {},
        },
        "serviceTier": None,
        "attachments": [],
        "clientUserMessageId": str(uuid.uuid4()),
        "additionalContext": {},
    }


def extract_ack_turn(result: dict[str, Any]) -> str | None:
    payload: Any = result.get("result")
    if isinstance(payload, dict) and isinstance(payload.get("result"), dict):
        payload = payload["result"]
    if isinstance(payload, dict) and isinstance(payload.get("turnId"), str):
        return payload["turnId"]
    turn = payload.get("turn") if isinstance(payload, dict) else None
    value = turn.get("id") if isinstance(turn, dict) else None
    return value if isinstance(value, str) and value else None


def submit_turn(ctx: Context, *, thread_id: str, prompt: str, model: str | None, effort: str | None, steering: bool = False, target_turn: str | None = None, parent_job: str | None = None) -> dict[str, Any]:
    rollout = find_rollout(ctx, thread_id)
    if rollout is None:
        raise RuntimeError("No persisted rollout exists for the Desktop thread")
    if steering and (not isinstance(target_turn, str) or find_active_turn(rollout) != target_turn):
        raise RuntimeError("Steer target is no longer the exact active turn")
    job: dict[str, Any] = {
        "job_id": "job-" + uuid.uuid4().hex, "thread_id": thread_id, "rollout_path": str(rollout),
        "baseline_offset": rollout.stat().st_size, "submitted_at": datetime.now(timezone.utc).isoformat(),
        "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(), "model": model, "effort": effort,
        "is_steering": steering, "target_turn_id": target_turn, "target_active_at_baseline": bool(steering and target_turn),
        "parent_job_id": parent_job, "submission_status": "submitting",
    }
    save_job(ctx, job)
    settings = {key: value for key, value in (("model", model), ("effort", effort)) if value is not None}
    if steering and find_active_turn(rollout) != target_turn:
        job.update({"submission_status": "rejected", "submission_error": "Steer target changed before IPC submission"})
        save_job(ctx, job)
        raise RuntimeError("Steer target changed immediately before IPC submission")
    try:
        operation = "steer" if steering else "send"
        params = build_steer_request(thread_id, prompt, target_turn, thread_cwd(ctx, thread_id)) if steering else build_turn_request(thread_id, prompt, model, effort, False)
        result = run_ipc(ctx, {
            "operation": operation,
            "pipe": PIPE_PATH,
            "threadId": thread_id,
            "threadSettings": settings,
            "params": params,
            "startTurnVersion": 2,
        })
    except Exception as exc:
        job.update({"submission_status": "uncertain", "submission_error": f"{type(exc).__name__}: {exc}"})
        save_job(ctx, job)
        raise RuntimeError(f"Desktop submission outcome is uncertain; inspect job {job['job_id']} before any retry") from exc
    ack = extract_ack_turn(result)
    if ack is None:
        job.update({"submission_status": "uncertain", "submission_error": "IPC response omitted turn.id"})
        save_job(ctx, job)
        raise RuntimeError(f"Desktop submission outcome is uncertain; inspect job {job['job_id']}")
    if steering and ack != target_turn:
        job.update({"submission_status": "uncertain", "submission_error": f"Steer acknowledged unexpected turn {ack}"})
        save_job(ctx, job)
        raise RuntimeError(f"Desktop steer outcome is uncertain; inspect job {job['job_id']}")
    job.update({"owner_client_id": result.get("ownerClientId"), "controller_client_id": result.get("clientId"), "ipc_ack_turn_id": ack, "accepted_turn_id": None if steering else ack, "submission_status": "accepted"})
    save_job(ctx, job)
    return summarize_job(ctx, job)


def require_active(summary: dict[str, Any], operation: str) -> str:
    turn = summary.get("turn_id")
    if summary.get("status") != "running" or not isinstance(turn, str) or not turn:
        raise RuntimeError(f"{operation} requires a running job with a known turn id")
    return turn


def interrupt_job(ctx: Context, job_id: str) -> dict[str, Any]:
    job = load_job(ctx, job_id)
    turn = require_active(summarize_job(ctx, job), "Interrupt")
    thread = str(job["thread_id"])
    result = run_ipc(ctx, {"operation": "interrupt", "pipe": PIPE_PATH, "threadId": thread, "params": {"conversationId": thread, "mode": "user-stop", "expectedTurnId": turn}})
    nested = result.get("result")
    interrupted = nested.get("interruptedTurnId") if isinstance(nested, dict) else None
    if interrupted != turn:
        raise RuntimeError(f"Desktop interrupt acknowledgement did not match the exact turn: expected {turn}, received {interrupted!r}")
    job["interrupt_requested_at"] = datetime.now(timezone.utc).isoformat()
    save_job(ctx, job)
    return {"job_id": job_id, "thread_id": thread, "turn_id": turn, "status": "interrupt_requested", "result": nested}


def wait_job(ctx: Context, job_id: str, timeout: float, *, target_statuses: set[str] | None = None) -> dict[str, Any]:
    if os.name != "nt":
        raise RuntimeError("Desktop wait requires Windows")
    timeout = float(timeout)
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("Timeout must be positive and finite")
    job = load_job(ctx, job_id)
    if job.get("submission_status") == "uncertain":
        raise RuntimeError("Uncertain jobs must be explicitly reconciled before wait")
    targets = TERMINAL_STATUSES if target_statuses is None else set(target_statuses)
    summary = summarize_job(ctx, job)
    if summary["status"] in targets:
        return summary

    from ctypes import wintypes

    rollout = _validated_job_rollout(ctx, job)
    directory = str(rollout.parent)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    class OVERLAPPED(ctypes.Structure):
        _fields_ = [
            ("Internal", ctypes.c_size_t),
            ("InternalHigh", ctypes.c_size_t),
            ("Offset", wintypes.DWORD),
            ("OffsetHigh", wintypes.DWORD),
            ("hEvent", wintypes.HANDLE),
        ]

    create_file = kernel32.CreateFileW
    create_file.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    create_file.restype = wintypes.HANDLE
    create_event = kernel32.CreateEventW
    create_event.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR]
    create_event.restype = wintypes.HANDLE
    reset_event = kernel32.ResetEvent
    reset_event.argtypes = [wintypes.HANDLE]
    reset_event.restype = wintypes.BOOL
    read_changes = kernel32.ReadDirectoryChangesW
    read_changes.argtypes = [wintypes.HANDLE, wintypes.LPVOID, wintypes.DWORD, wintypes.BOOL, wintypes.DWORD, wintypes.LPVOID, ctypes.POINTER(OVERLAPPED), wintypes.LPVOID]
    read_changes.restype = wintypes.BOOL
    wait_for_single = kernel32.WaitForSingleObject
    wait_for_single.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    wait_for_single.restype = wintypes.DWORD
    get_result = kernel32.GetOverlappedResult
    get_result.argtypes = [wintypes.HANDLE, ctypes.POINTER(OVERLAPPED), ctypes.POINTER(wintypes.DWORD), wintypes.BOOL]
    get_result.restype = wintypes.BOOL
    cancel_io = kernel32.CancelIoEx
    cancel_io.argtypes = [wintypes.HANDLE, ctypes.POINTER(OVERLAPPED)]
    cancel_io.restype = wintypes.BOOL
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = [wintypes.HANDLE]
    close_handle.restype = wintypes.BOOL

    handle = create_file(
        directory,
        0x0001,
        0x00000001 | 0x00000002 | 0x00000004,
        None,
        3,
        0x02000000 | 0x40000000,
        None,
    )
    invalid_handle = wintypes.HANDLE(-1).value
    if handle == invalid_handle:
        raise OSError(ctypes.get_last_error(), f"Cannot watch rollout directory: {directory}")
    event_handle = create_event(None, True, False, None)
    if not event_handle:
        close_handle(handle)
        raise OSError(ctypes.get_last_error(), "Cannot create rollout notification event")

    buffer: Any = None
    overlapped: Any = None

    def arm() -> None:
        nonlocal buffer, overlapped
        if not reset_event(event_handle):
            raise OSError(ctypes.get_last_error(), "Cannot reset rollout notification event")
        buffer = ctypes.create_string_buffer(64 * 1024)
        overlapped = OVERLAPPED()
        overlapped.hEvent = event_handle
        ok = read_changes(
            handle,
            buffer,
            len(buffer),
            False,
            0x00000001 | 0x00000008 | 0x00000010,
            None,
            ctypes.byref(overlapped),
            None,
        )
        error = ctypes.get_last_error() if not ok else 0
        if not ok and error != 997:
            raise OSError(error, "ReadDirectoryChangesW failed while arming the desktop job watcher")

    deadline = time.monotonic() + timeout
    try:
        arm()
        while True:
            job = load_job(ctx, job_id)
            summary = summarize_job(ctx, job)
            if summary["status"] in targets:
                return summary
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(f"Timed out waiting for desktop job {job_id}")
            wait_ms = min(max(1, int(remaining * 1000)), 0xFFFFFFFE)
            wait_result = wait_for_single(event_handle, wait_ms)
            if wait_result == 258:
                raise TimeoutError(f"Timed out waiting for desktop job {job_id}")
            if wait_result != 0:
                raise OSError(ctypes.get_last_error(), "Waiting for rollout notification failed")
            transferred = wintypes.DWORD()
            if not get_result(handle, ctypes.byref(overlapped), ctypes.byref(transferred), False):
                raise OSError(ctypes.get_last_error(), "Reading rollout notification result failed")
            arm()
    finally:
        if overlapped is not None:
            cancel_io(handle, ctypes.byref(overlapped))
            cancelled_bytes = wintypes.DWORD()
            # CancelIoEx is asynchronous. Keep OVERLAPPED and buffer alive until
            # GetOverlappedResult reports completion or ERROR_OPERATION_ABORTED.
            get_result(handle, ctypes.byref(overlapped), ctypes.byref(cancelled_bytes), True)
        close_handle(event_handle)
        close_handle(handle)


def wait_for_running_job(ctx: Context, job_id: str, timeout: float) -> dict[str, Any]:
    summary = wait_job(ctx, job_id, timeout, target_statuses={"running", *TERMINAL_STATUSES})
    if summary.get("status") != "running":
        raise RuntimeError(f"Certification task reached {summary.get('status')} before becoming steerable")
    return summary


def find_active_turn(path: Path | str) -> str | None:
    active = None
    with Path(path).open("rb") as handle:
        for raw in handle:
            if not raw.endswith(b"\n"):
                continue
            try:
                record = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise RuntimeError("Malformed complete JSONL record in rollout") from exc
            event = normalize_event(record)
            if not event:
                continue
            if event["event"] in {"turn.started", "turn.completed", "turn.failed", "turn.interrupted"} and not _valid_turn_id(event.get("turn_id")):
                raise RuntimeError("Turn lifecycle event is missing a valid turn ID")
            if event["event"] == "turn.started":
                active = event["turn_id"]
            elif event["event"] in {"turn.completed", "turn.failed", "turn.interrupted"} and active is not None and event["turn_id"] == active:
                active = None
    return active


def certification_thread_info(ctx: Context, thread_id: str) -> dict[str, Any]:
    thread_id = _safe_id(thread_id, "certification thread id")
    connection = sqlite3.connect(f"file:{_database(ctx)}?mode=ro", uri=True)
    try:
        row = connection.execute(
            "SELECT title, archived, model, reasoning_effort, rollout_path FROM threads WHERE id=?",
            (thread_id,),
        ).fetchone()
    finally:
        connection.close()
    if row is None:
        raise RuntimeError("Certification thread does not exist in the Desktop database")
    if bool(row[1]):
        raise RuntimeError("Certification thread is archived")
    rollout = _validate_rollout_path(ctx.desktop_home, row[4])
    active = find_active_turn(rollout)
    if active is not None:
        raise RuntimeError(f"Certification thread already has an active turn: {active}")
    return {
        "title": row[0],
        "archived": False,
        "model": row[2],
        "effort": row[3],
        "rollout_path": str(rollout),
    }


def thread_settings_info(ctx: Context, thread_id: str) -> dict[str, Any]:
    thread_id = _safe_id(thread_id, "thread id")
    connection = sqlite3.connect(f"file:{_database(ctx)}?mode=ro", uri=True)
    try:
        row = connection.execute(
            "SELECT model, reasoning_effort FROM threads WHERE id=?",
            (thread_id,),
        ).fetchone()
    finally:
        connection.close()
    if row is None:
        raise RuntimeError("Desktop thread does not exist while checking settings")
    return {"model": row[0], "effort": row[1]}


def restore_thread_settings(ctx: Context, thread_id: str, model: str, effort: str) -> None:
    result = run_ipc(
        ctx,
        {
            "operation": "settings",
            "pipe": PIPE_PATH,
            "threadId": thread_id,
            "threadSettings": {"model": model, "effort": effort},
        },
    )
    if result.get("connected") is not True:
        raise RuntimeError("Could not reconnect while restoring certification thread settings")
    restored = thread_settings_info(ctx, thread_id)
    if restored.get("model") != model or restored.get("effort") != effort:
        raise RuntimeError("Certification thread settings were not restored")


def abort_active_certification_turn(ctx: Context, thread_id: str) -> dict[str, Any]:
    rollout = find_rollout(ctx, thread_id)
    if rollout is None:
        return {"interrupted": False, "turn_id": None}
    turn_id = find_active_turn(rollout)
    if turn_id is None:
        return {"interrupted": False, "turn_id": None}
    result = run_ipc(
        ctx,
        {
            "operation": "interrupt",
            "pipe": PIPE_PATH,
            "threadId": thread_id,
            "params": {
                "conversationId": thread_id,
                "mode": "user-stop",
                "expectedTurnId": turn_id,
            },
        },
    )
    nested = result.get("result")
    interrupted = nested.get("interruptedTurnId") if isinstance(nested, dict) else None
    if interrupted != turn_id:
        raise RuntimeError("Certification cleanup interrupt did not acknowledge the exact active turn")
    return {"interrupted": True, "turn_id": turn_id}


def _certification_result(summary: dict[str, Any], *, status: str, response: str | None = None) -> dict[str, Any]:
    ok = summary.get("status") == status
    if response is not None:
        ok = ok and summary.get("final_response") == response
    return {
        "ok": ok,
        "job_id": summary.get("job_id"),
        "turn_id": summary.get("turn_id"),
        "status": summary.get("status"),
        "final_response": summary.get("final_response"),
        "error": summary.get("error"),
    }


def certify_build(ctx: Context, thread_id: str, timeout: float) -> dict[str, Any]:
    thread = certification_thread_info(ctx, thread_id)
    original_model = thread.get("model")
    original_effort = thread.get("effort")
    if not isinstance(original_model, str) or not original_model:
        raise RuntimeError("Certification thread has no current model to restore")
    supported_efforts = ("low", "medium", "high", "xhigh", "max", "ultra")
    if original_effort not in supported_efforts:
        raise RuntimeError("Certification thread has no supported reasoning effort to restore")
    try:
        receipt = _certify_build_e2e(ctx, thread_id, timeout, thread, original_model, original_effort)
    except BaseException:
        certification_path(ctx).unlink(missing_ok=True)
        try:
            abort_active_certification_turn(ctx, thread_id)
        except Exception:
            pass
        try:
            restore_thread_settings(ctx, thread_id, original_model, original_effort)
        except Exception:
            pass
        raise
    try:
        restore_thread_settings(ctx, thread_id, original_model, original_effort)
    except Exception:
        certification_path(ctx).unlink(missing_ok=True)
        raise
    return receipt


def _certify_build_e2e(
    ctx: Context,
    thread_id: str,
    timeout: float,
    thread: dict[str, Any],
    original_model: str,
    original_effort: str,
) -> dict[str, Any]:
    timeout = float(timeout)
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("Certification timeout must be positive and finite")
    desktop = desktop_process_report(ctx)
    schema = schema_report(ctx)
    identity = compatibility_identity(ctx, desktop, schema)
    alternate_effort = "medium" if original_effort != "medium" else "high"
    receipt_path = certification_path(ctx)
    receipt_path.unlink(missing_ok=True)

    probe = run_ipc(ctx, {"operation": "probe", "pipe": PIPE_PATH, "threadId": thread_id})
    if probe.get("connected") is not True:
        raise RuntimeError("Certification probe did not connect")

    send = submit_turn(
        ctx,
        thread_id=thread_id,
        prompt="Codex Desktop compatibility certification. Do not read or modify files and do not call tools. Reply exactly: CODEX_DESKTOP_CERT_SEND_OK",
        model=original_model,
        effort=alternate_effort,
    )
    send_wait = wait_job(ctx, str(send["job_id"]), timeout)
    send_status = summarize_job(ctx, load_job(ctx, str(send["job_id"])))
    send_check = _certification_result(send_wait, status="completed", response="CODEX_DESKTOP_CERT_SEND_OK")
    send_check["status_readback_ok"] = (
        send_status.get("status") == "completed"
        and send_status.get("turn_id") == send_wait.get("turn_id")
        and send_status.get("final_response") == "CODEX_DESKTOP_CERT_SEND_OK"
    )
    send_check["ok"] = bool(send_check["ok"] and send_check["status_readback_ok"])
    if not send_check["ok"]:
        raise RuntimeError("Certification send/wait/status check failed")
    changed_settings = thread_settings_info(ctx, thread_id)
    changed_ok = (
        changed_settings.get("model") == original_model
        and changed_settings.get("effort") == alternate_effort
    )
    if not changed_ok:
        raise RuntimeError("Certification settings update was not persisted")

    steer_parent = submit_turn(
        ctx,
        thread_id=thread_id,
        prompt=(
            "Codex Desktop compatibility certification. Run this harmless command and wait for it to finish before replying: "
            "python -c \"import time; time.sleep(30)\". Then reply CERT_STEER_PARENT_UNEXPECTED."
        ),
        model=original_model,
        effort=original_effort,
    )
    steer_parent = wait_for_running_job(ctx, str(steer_parent["job_id"]), timeout)
    restored_settings = thread_settings_info(ctx, thread_id)
    restored_ok = (
        restored_settings.get("model") == original_model
        and restored_settings.get("effort") == original_effort
    )
    if not restored_ok:
        raise RuntimeError("Certification did not restore the original thread settings")
    settings_check = {
        "ok": True,
        "model": original_model,
        "original_effort": original_effort,
        "temporary_effort": alternate_effort,
        "temporary_settings_verified": True,
        "original_settings_restored": True,
    }
    steer_turn = require_active(steer_parent, "Certification steer")
    steer = submit_turn(
        ctx,
        thread_id=thread_id,
        prompt="Certification correction: stop the planned response and reply exactly CODEX_DESKTOP_CERT_STEER_OK.",
        model=None,
        effort=None,
        steering=True,
        target_turn=steer_turn,
        parent_job=str(steer_parent["job_id"]),
    )
    if steer.get("turn_id") != steer_turn:
        raise RuntimeError("Certification steer did not acknowledge the exact active turn")
    steer_wait = wait_job(ctx, str(steer["job_id"]), timeout)
    steer_check = _certification_result(steer_wait, status="completed", response="CODEX_DESKTOP_CERT_STEER_OK")
    steer_check["same_turn_ack"] = steer_wait.get("turn_id") == steer_turn
    steer_check["parent_job_id"] = steer_parent.get("job_id")
    steer_check["ok"] = bool(steer_check["ok"] and steer_check["same_turn_ack"])
    if not steer_check["ok"]:
        raise RuntimeError("Certification steer check failed")

    interrupt_parent = submit_turn(
        ctx,
        thread_id=thread_id,
        prompt=(
            "Codex Desktop compatibility certification. Run this harmless command and wait for it to finish before replying: "
            "python -c \"import time; time.sleep(120)\". Then reply CERT_INTERRUPT_PARENT_UNEXPECTED."
        ),
        model=None,
        effort=None,
    )
    interrupt_parent = wait_for_running_job(ctx, str(interrupt_parent["job_id"]), timeout)
    interrupt_turn = require_active(interrupt_parent, "Certification interrupt")
    interrupt_ack = interrupt_job(ctx, str(interrupt_parent["job_id"]))
    if interrupt_ack.get("turn_id") != interrupt_turn:
        raise RuntimeError("Certification interrupt did not acknowledge the exact active turn")
    interrupt_wait = wait_job(ctx, str(interrupt_parent["job_id"]), timeout)
    interrupt_check = _certification_result(interrupt_wait, status="interrupted")
    interrupt_check["exact_ack"] = interrupt_ack.get("turn_id") == interrupt_turn
    interrupt_check["ok"] = bool(interrupt_check["ok"] and interrupt_check["exact_ack"])
    if not interrupt_check["ok"]:
        raise RuntimeError("Certification interrupt check failed")

    final_probe = run_ipc(ctx, {"operation": "probe", "pipe": PIPE_PATH, "threadId": thread_id})
    if final_probe.get("connected") is not True:
        raise RuntimeError("Certification final probe did not connect")
    receipt = {
        "format_version": 1,
        "certified_at_utc": datetime.now(timezone.utc).isoformat(),
        "identity": identity,
        "certification_thread_id": thread_id,
        "thread": thread,
        "checks": {
            "probe": {"ok": True, "owner_discovered": bool(probe.get("ownerClientId"))},
            "send_wait_status": send_check,
            "settings_round_trip": settings_check,
            "steer": steer_check,
            "interrupt": interrupt_check,
            "final_probe": {"ok": True, "owner_discovered": bool(final_probe.get("ownerClientId"))},
        },
        "overall_ok": True,
    }
    _atomic_json(receipt_path, receipt)
    return receipt


def doctor_report(*, hermes_home: str, profile: str, desktop_codex_home: str, offline: bool, thread_id: str | None = None) -> dict[str, Any]:
    checks: dict[str, Any] = {}
    issues: list[str] = []
    warnings: list[str] = []
    try:
        ctx = resolve_context(hermes_home=hermes_home, profile=profile, desktop_codex_home=desktop_codex_home)
    except Exception as exc:
        return {"ok": False, "offline": offline, "issues": [f"configuration: {type(exc).__name__}: {exc}"], "checks": {}}
    checks["platform"] = platform_report()
    if not checks["platform"]["ok"]:
        issues.append("unsupported platform")
    checks["paths"] = {"ok": _is_within(ctx.runtime, ctx.hermes_home / "skill-data" / "codex-desktop-control" / "profiles"), "runtime": str(ctx.runtime), "desktop_codex_home": str(ctx.desktop_home)}
    if not checks["paths"]["ok"]:
        issues.append("runtime path escaped Hermes home")
    checks["dependencies"] = dependency_report(ctx)
    checks["schema"] = schema_report(ctx)
    checks["desktop"] = desktop_process_report(ctx)
    checks["runtime_hygiene"] = runtime_hygiene_report(ctx)
    if not checks["dependencies"]["ok"]:
        issues.extend(checks["dependencies"]["issues"])
    if not checks["schema"]["ok"]:
        issues.extend(checks["schema"]["issues"])
    if not checks["desktop"]["ok"]:
        issues.extend(checks["desktop"]["issues"])
    if not checks["runtime_hygiene"]["ok"]:
        issues.extend(checks["runtime_hygiene"]["issues"])
    if checks["schema"].get("warnings"):
        warnings.extend(str(value) for value in checks["schema"]["warnings"])
    checks["certification"] = {"certified": False, "issues": ["compatibility checks did not pass"]}
    if checks["desktop"].get("ok") and checks["schema"].get("ok"):
        identity = compatibility_identity(ctx, checks["desktop"], checks["schema"])
        checks["certification"] = certification_report(ctx, identity)
        if not checks["certification"]["certified"]:
            warnings.append("write capabilities are disabled until automatic certification succeeds")
    checks["ipc"] = {"ok": None, "mode": "not-run-offline" if offline else "not-requested"}
    if not offline and thread_id and not issues:
        try:
            result = run_ipc(ctx, {"operation": "probe", "pipe": PIPE_PATH, "threadId": thread_id})
            checks["ipc"] = {"ok": True, "thread_id": thread_id, "owner_client_id": result.get("ownerClientId")}
        except Exception as exc:
            checks["ipc"] = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
            issues.append("Desktop IPC probe failed")
    certified = bool(checks["certification"].get("certified"))
    compatibility_level = "certified" if certified else checks["desktop"].get("compatibility", "incompatible")
    return {
        "ok": not issues,
        "offline": offline,
        "profile": profile,
        "runtime": str(ctx.runtime),
        "compatibility_level": compatibility_level,
        "write_capabilities_enabled": certified,
        "issues": issues,
        "warnings": warnings,
        "checks": checks,
    }


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Isolated Windows controller for existing Codex Desktop tasks")
    result.add_argument("--hermes-home", required=True)
    result.add_argument("--profile", default="default")
    result.add_argument("--desktop-codex-home", required=True)
    sub = result.add_subparsers(dest="command", required=True)
    probe = sub.add_parser("probe"); probe.add_argument("--thread", required=True)
    send = sub.add_parser("send"); send.add_argument("--thread", required=True); send.add_argument("--prompt", required=True); send.add_argument("--model"); send.add_argument("--effort", choices=("low", "medium", "high", "xhigh", "max", "ultra"))
    status = sub.add_parser("status"); status.add_argument("--job", required=True); status.add_argument("--reconcile-turn")
    wait = sub.add_parser("wait"); wait.add_argument("--job", required=True); wait.add_argument("--timeout", type=float, default=600)
    steer = sub.add_parser("steer"); steer.add_argument("--job", required=True); steer.add_argument("--prompt", required=True); steer.add_argument("--model"); steer.add_argument("--effort", choices=("low", "medium", "high", "xhigh", "max", "ultra"))
    interrupt = sub.add_parser("interrupt"); interrupt.add_argument("--job", required=True)
    certify = sub.add_parser("certify"); certify.add_argument("--thread", required=True); certify.add_argument("--timeout", type=float, default=240)
    return result


def main() -> int:
    args = parser().parse_args()
    ctx = resolve_context(hermes_home=args.hermes_home, profile=args.profile, desktop_codex_home=args.desktop_codex_home)
    ensure_runtime_layout(ctx)
    compatibility_gate(ctx, args.command)
    if args.command == "probe":
        output = run_ipc(ctx, {"operation": "probe", "pipe": PIPE_PATH, "threadId": args.thread})
    elif args.command == "send":
        output = submit_turn(ctx, thread_id=args.thread, prompt=args.prompt, model=args.model, effort=args.effort)
    elif args.command == "status":
        job = load_job(ctx, args.job)
        output = reconcile_job(ctx, job, args.reconcile_turn) if args.reconcile_turn else summarize_job(ctx, job)
    elif args.command == "wait":
        output = wait_job(ctx, args.job, args.timeout)
    elif args.command == "steer":
        parent = load_job(ctx, args.job); turn = require_active(summarize_job(ctx, parent), "Steer")
        output = submit_turn(ctx, thread_id=str(parent["thread_id"]), prompt=args.prompt, model=args.model, effort=args.effort, steering=True, target_turn=turn, parent_job=args.job)
    elif args.command == "interrupt":
        output = interrupt_job(ctx, args.job)
    elif args.command == "certify":
        output = certify_build(ctx, args.thread, args.timeout)
    else:
        return 2
    print(json.dumps(output, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())