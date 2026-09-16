"""Build-pinned native queue with exact persisted lifecycle; no replay or cancel."""
from __future__ import annotations

import hashlib
import json
import os
import time
import uuid
from pathlib import Path

import desktop_controller as c

BUILD = '26.908.9136.0'
ASAR_SHA256 = '7a46bd6fe162050afbac27d7d5271d19524e887fa0cdd06c0f2d3fa9b606a31d'
QUEUE_CONTRACT = {'required_anchors': ['thread-follower-set-queued-follow-ups-state', 'thread-queued-followups-changed'],
                  'method_versions': {'thread-follower-set-queued-follow-ups-state': 1, 'thread-queued-followups-changed': 2}}


def identity(ctx, thread):
    thread = c._safe_id(thread, 'thread id').lower()
    return os.path.normcase(str(ctx.desktop_home.resolve())), thread


def slot_root(ctx):
    # Controller-owned sidecar OUTSIDE Codex home, shared by all Hermes homes/profiles.
    home = ctx.desktop_home.resolve()
    if home == home.parent:
        raise RuntimeError('Desktop home cannot be a filesystem root')
    return home.parent / '.codex-desktop-control-queues'


def slot_path(ctx, thread):
    key = json.dumps(identity(ctx, thread), separators=(',', ':'))
    return slot_root(ctx) / (hashlib.sha256(key.encode()).hexdigest()+'.json')


def regular_path(path):
    if path.exists() or path.is_symlink():
        if path.is_symlink() or getattr(path.lstat(), 'st_file_attributes', 0) & 0x400:
            raise RuntimeError('Queue sidecar links/reparse points are forbidden')


def persist(path, value):
    regular_path(path.parent)
    path.parent.mkdir(parents=True, exist_ok=True)
    regular_path(path)
    tmp = path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    try:
        with tmp.open('x', encoding='utf-8') as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, path)
        if os.name != 'nt':
            fd = os.open(path.parent, os.O_RDONLY)
            try: os.fsync(fd)
            finally: os.close(fd)
    finally:
        tmp.unlink(missing_ok=True)


def queue_gate(ctx, *, write=False, acceptance_test=False):
    # Legacy acceptance flag grants no authority. Every write requires the same
    # profile-local certification as send, plus the narrower tested queue pin.
    c.compatibility_gate(ctx, 'send' if write else 'probe')
    desktop = c.desktop_process_report(ctx)
    build = desktop.get('build') or {}
    if not desktop.get('ok') or build.get('version') != BUILD or build.get('desktop_protocol_payload_sha256') != ASAR_SHA256:
        raise RuntimeError('Native queue requires the exact inspected Desktop build/payload')
    payload = Path(desktop['processes'][0]['protocol_payload'])
    if not c.scan_protocol_payload(payload, QUEUE_CONTRACT)['ok']:
        raise RuntimeError('Native queue protocol capability mismatch')


def build_item(item_id, prompt, cwd):
    if not isinstance(prompt, str) or not prompt.strip() or len(prompt.encode('utf-8')) > 65536:
        raise ValueError('Queue prompt must be nonempty plain text, at most 64 KiB')
    return {'id': c._safe_id(item_id, 'queue item id'), 'text': prompt,
            'context': {'prompt': prompt, 'addedFiles': [], 'fileAttachments': [],
                        'ideContext': None, 'imageAttachments': [], 'workspaceRoots': [cwd]},
            'cwd': cwd, 'createdAt': int(time.time()*1000)}


def load_slot(ctx, thread):
    path = slot_path(ctx, thread)
    regular_path(path.parent)
    regular_path(path)
    if not path.exists(): return None
    record = json.loads(path.read_text(encoding='utf-8'))
    if (not isinstance(record, dict) or record.get('schema') not in (1, 2)
            or record.get('identity') != list(identity(ctx, thread))
            or type(record.get('slot_reserved')) is not bool
            or (record.get('schema') == 1 and record.get('slot_reserved') is not True)):
        raise RuntimeError('Queue slot record is malformed; manual review required, never reset automatically')
    return record


def apply_observation(record, response):
    observation = response.get('queueObservation', {})
    messages = observation.get('messages')
    record['native_state'] = observation.get('kind', 'unknown')
    record['owner_client_id'] = response.get('ownerClientId')
    record['observation_at_ms'] = int(time.time()*1000)
    record['authoritative_snapshot'] = False
    record['state'] = 'unknown'
    if observation.get('kind') == 'present' and isinstance(messages, list) and len(messages) == 1:
        if isinstance(messages[0], dict) and all(messages[0].get(k) == v for k, v in record['item'].items()):
            record['state'] = 'enqueued'
            record['paused_reason'] = messages[0].get('pausedReason')
        else:
            record['native_state'] = 'unmanaged-conflict'
    elif messages:
        record['native_state'] = 'unmanaged-conflict'
    if record['native_state'] == 'unmanaged-conflict':
        record['exclusive_management_valid'] = False
    # Empty/no observation never correlates to a turn or releases the slot.
    record['turn_id'] = None


def rollout_data(ctx, thread):
    path = c.find_rollout(ctx, thread)
    if path is None:
        raise RuntimeError('Thread has no mapped rollout')
    path = c._validate_rollout_path(ctx.desktop_home, path)
    data = path.read_bytes()
    first = json.loads(data.split(b'\n', 1)[0])
    meta = first.get('payload', {})
    if (first.get('type') != 'session_meta' or meta.get('id') != thread
            or meta.get('session_id', thread) != thread):
        raise RuntimeError('Rollout session thread identity mismatch')
    return path, data


def capture_baseline(ctx, thread, *, offset=None):
    path, data = rollout_data(ctx, thread)
    offset = len(data) if offset is None else offset
    if type(offset) is not int or not 0 < offset <= len(data) or data[offset-1:offset] != b'\n':
        raise RuntimeError('Rollout baseline must be a complete record boundary')
    return {'path': str(path), 'offset': offset,
            'prefix_sha256': hashlib.sha256(data[:offset]).hexdigest()}


def import_legacy_baseline(ctx, thread, record, evidence_path):
    if 'rollout_baseline' in record:
        raise RuntimeError('Cannot replace an existing queue baseline')
    raw = Path(evidence_path).read_bytes()
    evidence = json.loads(raw)
    path, _ = rollout_data(ctx, thread)
    if (evidence.get('thread') != thread or
            Path(evidence.get('settings', {}).get('rollout_path', '')).resolve() != path.resolve()):
        raise RuntimeError('Legacy baseline evidence thread/path mismatch')
    # Explicit one-time migration of a pre-lifecycle intent. Never infer a
    # baseline from a prompt, time, or the matching message itself.
    record['rollout_baseline'] = capture_baseline(ctx, thread, offset=evidence['rollout_bytes'])
    record['baseline_import'] = {'path': str(Path(evidence_path).resolve()),
                                 'sha256': hashlib.sha256(raw).hexdigest()}
    record['schema'] = 2
    record['exclusive_management_valid'] = (record.get('adopted_empty_exclusive') is True
                                            and record.get('exclusive_management_valid') is not False
                                            and record.get('native_state') != 'unmanaged-conflict')


def reconcile(ctx, thread, record):
    baseline = record.get('rollout_baseline')
    if not baseline:
        raise RuntimeError('Legacy reservation needs explicit --baseline-evidence; no automatic inference')
    path, data = rollout_data(ctx, thread)
    if path.resolve() != Path(baseline['path']).resolve():
        raise RuntimeError('Queue rollout no longer matches database mapping')
    for checkpoint in (baseline, record.get('rollout_checkpoint', baseline)):
        offset = checkpoint['offset']
        if (type(offset) is not int or offset > len(data) or offset < 1
                or hashlib.sha256(data[:offset]).hexdigest() != checkpoint['prefix_sha256']):
            raise RuntimeError('Rollout truncated or rewritten since queue baseline/checkpoint')
    suffix = data[baseline['offset']:]
    if suffix and not suffix.endswith(b'\n'):
        raise RuntimeError('Partial trailing rollout record; retry read-only status after append completes')
    rows = []
    for raw in suffix.splitlines():
        row = json.loads(raw)
        if not isinstance(row, dict) or not isinstance(row.get('type'), str):
            raise RuntimeError('Malformed rollout record')
        if row['type'] == 'session_meta':
            raise RuntimeError('Unexpected session metadata after baseline')
        if row['type'] != 'event_msg':
            continue
        payload = row.get('payload')
        if not isinstance(payload, dict):
            raise RuntimeError('Malformed event payload')
        if payload.get('thread_id', thread) != thread:
            raise RuntimeError('Event thread identity mismatch')
        rows.append(row)
    matches = [(i, row) for i, row in enumerate(rows)
               if row['payload'].get('type') == 'item_completed'
               and isinstance(row['payload'].get('item'), dict)
               and row['payload']['item'].get('type') == 'UserMessage'
               and row['payload']['item'].get('client_id') == record['item']['id']]
    if len(matches) > 1:
        # Even identical duplicate mapping events are conservatively ambiguous.
        raise RuntimeError('Ambiguous duplicate client_id mapping')
    if not matches:
        record.update(state='unknown', turn_id=None)
        return None
    index, mapping = matches[0]
    payload = mapping['payload']
    turn = payload.get('turn_id')
    if payload.get('thread_id') != thread or not c._valid_turn_id(turn) or not c._valid_turn_id(payload['item'].get('id')):
        raise RuntimeError('Mapping requires exact thread, turn and native message IDs')
    starts = [(i, row) for i, row in enumerate(rows) if row['payload'].get('type') == 'task_started' and row['payload'].get('turn_id') == turn]
    terminal_names = {'task_complete': 'completed', 'task_failed': 'failed', 'turn_aborted': 'interrupted', 'turn_interrupted': 'interrupted'}
    terminals = [(i, row) for i, row in enumerate(rows) if row['payload'].get('type') in terminal_names and row['payload'].get('turn_id') == turn]
    if len(starts) != 1 or starts[0][0] >= index or len(terminals) > 1:
        raise RuntimeError('Ambiguous or missing ordered turn lifecycle')
    if terminals and (terminals[0][0] <= index or (terminals[0][1]['payload']['type'] == 'task_complete' and terminals[0][1]['payload'].get('error'))):
        raise RuntimeError('Invalid terminal ordering or completed-turn error')
    record['rollout_checkpoint'] = {'offset':len(data), 'prefix_sha256':hashlib.sha256(data).hexdigest()}
    record.update(state='running', turn_id=turn)
    record.pop('reconciliation_error', None)
    if not terminals:
        return None
    terminal = terminals[0][1]
    record['state'] = terminal_names[terminal['payload']['type']]
    return {'schema': 1, 'identity': record['identity'], 'item': record['item'],
            'rollout_baseline': baseline, 'baseline_import':record.get('baseline_import'),
            'state': record['state'], 'turn_id': turn,
            'evidence': {'start': starts[0][1], 'mapping': mapping, 'terminal': terminal},
            'intent_at_ms':record.get('intent_at_ms'), 'build':record.get('build'),
            'asar_sha256':record.get('asar_sha256')}


def archive_terminal(ctx, thread, receipt):
    directory = slot_path(ctx, thread).with_suffix('.history')
    regular_path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / (c._safe_id(receipt['item']['id'], 'queue item id')+'.json')
    regular_path(target)
    if target.exists():
        if json.loads(target.read_text(encoding='utf-8')) != receipt:
            raise RuntimeError('Immutable terminal receipt conflicts with evidence')
        return target
    tmp = directory / (uuid.uuid4().hex+'.tmp')
    try:
        with tmp.open('x', encoding='utf-8') as stream:
            json.dump(receipt, stream, ensure_ascii=False, indent=2)
            stream.flush(); os.fsync(stream.fileno())
        # Publish without replacement; process death can leave an archive and a
        # reserved slot. The next status validates the identical archive safely.
        os.link(tmp, target)
        if os.name != 'nt':
            fd = os.open(directory, os.O_RDONLY)
            try: os.fsync(fd)
            finally: os.close(fd)
    finally:
        tmp.unlink(missing_ok=True)
    return target


def validate_released(ctx, thread, record):
    path = slot_path(ctx, thread).with_suffix('.history') / (c._safe_id(record['item']['id'], 'queue item id')+'.json')
    regular_path(path.parent); regular_path(path)
    if (str(path) != record.get('terminal_receipt') or c.sha256_file(path) != record.get('terminal_receipt_sha256')):
        raise RuntimeError('Released slot terminal receipt is missing or changed')
    receipt = json.loads(path.read_text(encoding='utf-8'))
    if receipt.get('identity') != list(identity(ctx, thread)) or receipt.get('item') != record['item'] or receipt.get('state') not in c.TERMINAL_STATUSES:
        raise RuntimeError('Released slot terminal receipt identity mismatch')


def enqueue(ctx, thread, prompt, *, adopt_empty_exclusive=False, acceptance_test=False):
    home, thread = identity(ctx, thread)
    # Same canonical thread mutex as certification. No profile lock is taken:
    # certification orders receipt -> thread; queue takes only thread, so no cycle.
    with c._certification_lock('thread:'+home+':'+thread):
        previous = load_slot(ctx, thread)
        if previous is not None and previous['slot_reserved']:
            raise RuntimeError('Queue slot reserved (pending/unknown); no replace, retry or automatic reset')
        if previous is not None:
            validate_released(ctx, thread, previous)
            if (previous.get('exclusive_management_valid') is not True
                    or previous.get('build') != BUILD or previous.get('asar_sha256') != ASAR_SHA256):
                raise RuntimeError('Exclusive-management provenance invalid; no automatic re-adoption')
        elif not adopt_empty_exclusive:
            raise RuntimeError('First use requires --adopt-empty-exclusive: independently verify the visible queue is empty and commit to controller-only queue management')
        queue_gate(ctx, write=True, acceptance_test=acceptance_test)
        baseline = capture_baseline(ctx, thread)
        item = build_item(str(uuid.uuid4()), prompt, c.thread_cwd(ctx, thread))
        record = {'schema': 2, 'identity': [home, thread], 'item': item,
                  'rollout_baseline': baseline, 'exclusive_management_valid': True,
                  'previous_terminal_receipt': previous.get('terminal_receipt') if previous else None,
                  'slot_reserved': True, 'state': 'unknown', 'native_state': 'unknown',
                  'turn_id': None, 'setter_acknowledged': False, 'adopted_empty_exclusive': True,
                  'acceptance_test': acceptance_test, 'build': BUILD, 'asar_sha256': ASAR_SHA256,
                  'profile_runtime': str(ctx.runtime), 'intent_at_ms': int(time.time()*1000)}
        path = slot_path(ctx, thread)
        persist(path, record)  # MUST complete before even discovery IPC begins.
        try:
            response = c.run_ipc(ctx, {'operation': 'queue-enqueue', 'pipe': c.PIPE_PATH,
                                      'threadId': thread, 'item': item, 'adoptEmptyExclusive': True,
                                      'observeMs': 500}, retry_owner_missing=False)
            if response.get('result') != {'ok': True}:
                raise RuntimeError('Native queue setter acknowledgement missing/malformed')
            record['setter_acknowledged'] = True
            apply_observation(record, response)
        except Exception as exc:
            record['error'] = str(exc)
        persist(path, record)
        return record


def status(ctx, thread, *, observe=False, baseline_evidence=None):
    home, thread = identity(ctx, thread)
    with c._certification_lock('thread:'+home+':'+thread):
        record = load_slot(ctx, thread)
        if record is None:
            return {'state': 'unadopted', 'native_state': 'unknown', 'slot_reserved': False, 'turn_id': None}
        if not record['slot_reserved']:
            validate_released(ctx, thread, record)
            return dict(record, observation_is_historical=True)
        if baseline_evidence is not None:
            try:
                import_legacy_baseline(ctx, thread, record, baseline_evidence)
                persist(slot_path(ctx, thread), record)
            except Exception as exc:
                return dict(record, state='unknown', reconciliation_error=str(exc))
        if observe:
            queue_gate(ctx)
            try:
                response = c.run_ipc(ctx, {'operation': 'queue-observe', 'pipe': c.PIPE_PATH,
                                          'threadId': thread, 'observeMs': 500}, retry_owner_missing=False)
                apply_observation(record, response)
            except Exception as exc:
                record.update(state='unknown', native_state='unknown', error=str(exc))
        try:
            receipt = reconcile(ctx, thread, record)
            if receipt is not None:
                archived = archive_terminal(ctx, thread, receipt)
                record.update(terminal_receipt=str(archived), terminal_receipt_sha256=c.sha256_file(archived), slot_reserved=False)
        except Exception as exc:
            record.update(state='unknown', turn_id=None, reconciliation_error=str(exc), slot_reserved=True)
        persist(slot_path(ctx, thread), record)
        return dict(record, observation_is_historical=not observe)
