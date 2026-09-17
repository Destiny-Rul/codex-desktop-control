"""Offline single-slot regressions; native transport is a loopback fake, never Desktop."""
import json
import multiprocessing as mp
import shutil
import socket
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import desktop_controller as c
import native_queue as q


def context(root, profile='a'):
    return SimpleNamespace(desktop_home=Path(root)/'desktop', runtime=Path(root)/profile)


def contender(root, ready, release):
    ctx = context(root)
    def hold(*args, **kwargs):
        ready.set()
        if not release.wait(15):
            raise RuntimeError('test timed out')
        raise RuntimeError('uncertain')
    with patch.object(q, 'slot_root', return_value=Path(root)/'slots'), patch.object(q, 'queue_gate'), patch.object(q, 'capture_baseline', return_value={}), patch.object(c, 'thread_cwd', return_value=root), patch.object(c, 'run_ipc', side_effect=hold):
        q.enqueue(ctx, 'thread', 'test', adopt_empty_exclusive=True, acceptance_test=True)


class QueueTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.ctx = context(self.root)
        self.patches = [patch.object(q, 'slot_root', return_value=self.root/'slots'),
                        patch.object(q, 'capture_baseline', return_value={}),
                        patch.object(q, 'queue_gate'),
                        patch.object(c, 'thread_cwd', return_value=str(self.root))]
        for item in self.patches: item.start()

    def tearDown(self):
        for item in reversed(self.patches): item.stop()
        self.temp.cleanup()

    def test_adoption_required_without_ipc(self):
        with patch.object(c, 'run_ipc') as ipc:
            with self.assertRaisesRegex(RuntimeError, 'adopt'):
                q.enqueue(self.ctx, 'thread', 'test')
            ipc.assert_not_called()

    def test_durable_intent_precedes_ipc_and_second_enqueue_blocked(self):
        def ipc(ctx, payload, **kwargs):
            saved = json.loads(q.slot_path(ctx, 'thread').read_text())
            self.assertEqual(saved['state'], 'unknown')
            self.assertEqual(saved['item']['id'], payload['item']['id'])
            self.assertEqual(payload['operation'], 'queue-enqueue')
            self.assertFalse(kwargs['retry_owner_missing'])
            return {'connected': True, 'ownerClientId': 'owner', 'result': {'ok': True},
                    'queueObservation': {'kind': 'present', 'messages': [payload['item']]}}
        with patch.object(c, 'run_ipc', side_effect=ipc) as call:
            result = q.enqueue(self.ctx, 'thread', 'hello', adopt_empty_exclusive=True)
            self.assertEqual(result['state'], 'enqueued')
            with self.assertRaisesRegex(RuntimeError, 'reserved'):
                q.enqueue(context(self.root, 'other'), 'thread', 'second', adopt_empty_exclusive=True, acceptance_test=True)
            self.assertEqual(call.call_count, 1)

    def test_uncertain_submission_never_frees_slot(self):
        for error in (RuntimeError('no-client-found'), subprocess.TimeoutExpired('node', 1)):
            thread = str(type(error).__name__)
            with patch.object(c, 'run_ipc', side_effect=error) as call:
                result = q.enqueue(self.ctx, thread, 'test', adopt_empty_exclusive=True, acceptance_test=True)
                self.assertEqual(result['state'], 'unknown')
                self.assertTrue(result['slot_reserved'])
                self.assertEqual(call.call_count, 1)
            with patch.object(c, 'run_ipc') as ipc:
                with self.assertRaisesRegex(RuntimeError, 'reserved'):
                    q.enqueue(self.ctx, thread, 'retry', adopt_empty_exclusive=True, acceptance_test=True)
                ipc.assert_not_called()

    def test_silence_and_disappearance_never_mean_completed_or_empty(self):
        with patch.object(c, 'run_ipc', return_value={'result': {'ok': True}, 'queueObservation': {'kind': 'unknown'}}):
            q.enqueue(self.ctx, 'thread', 'test', adopt_empty_exclusive=True, acceptance_test=True)
        for observation in ({'kind': 'unknown'}, {'kind': 'empty', 'messages': []}):
            with patch.object(c, 'run_ipc', return_value={'queueObservation': observation}) as ipc:
                result = q.status(self.ctx, 'thread', observe=True)
                self.assertEqual(result['state'], 'unknown')
                self.assertTrue(result['slot_reserved'])
                self.assertIsNone(result['turn_id'])
                self.assertEqual(ipc.call_args.args[1]['operation'], 'queue-observe')

    def test_unknown_first_status_does_not_adopt(self):
        result = q.status(self.ctx, 'thread')
        self.assertEqual(result['state'], 'unadopted')
        self.assertEqual(result['native_state'], 'unknown')
        self.assertFalse(q.slot_path(self.ctx, 'thread').exists())

    def test_corrupt_slot_and_changed_native_item_never_release(self):
        path = q.slot_path(self.ctx, 'corrupt')
        path.parent.mkdir(parents=True); path.write_text('{')
        with patch.object(c, 'run_ipc') as ipc:
            with self.assertRaises(ValueError):
                q.enqueue(self.ctx, 'corrupt', 'test', adopt_empty_exclusive=True, acceptance_test=True)
            ipc.assert_not_called()
        with patch.object(c, 'run_ipc', return_value={'result': {'ok': True}}):
            result = q.enqueue(self.ctx, 'thread', 'test', adopt_empty_exclusive=True, acceptance_test=True)
        changed = dict(result['item'], text='unmanaged edit')
        with patch.object(c, 'run_ipc', return_value={'queueObservation': {'kind': 'present', 'messages': [changed]}}):
            result = q.status(self.ctx, 'thread', observe=True)
            self.assertEqual(result['native_state'], 'unmanaged-conflict')
            self.assertTrue(result['slot_reserved'])

    def test_failed_persistence_prevents_ipc(self):
        with patch.object(q, 'persist', side_effect=OSError('disk full')), patch.object(c, 'run_ipc') as ipc:
            with self.assertRaises(OSError):
                q.enqueue(self.ctx, 'thread', 'test', adopt_empty_exclusive=True, acceptance_test=True)
            ipc.assert_not_called()

    def test_cross_process_and_profile_contention_then_crash_retains_intent(self):
        spawn = mp.get_context('spawn')
        ready, release = spawn.Event(), spawn.Event()
        process = spawn.Process(target=contender, args=(str(self.root), ready, release))
        process.start()
        try:
            self.assertTrue(ready.wait(10))
            ctx = context(self.root, 'other-profile')
            ctx.desktop_home = self.root/'desktop'/'..'/'desktop'
            with patch.object(c, 'run_ipc') as ipc:
                with self.assertRaisesRegex(RuntimeError, 'already running'):
                    q.enqueue(ctx, 'thread', 'second', adopt_empty_exclusive=True, acceptance_test=True)
                ipc.assert_not_called()
            process.terminate(); process.join(10)
            with self.assertRaisesRegex(RuntimeError, 'reserved'):
                q.enqueue(ctx, 'thread', 'after crash', adopt_empty_exclusive=True, acceptance_test=True)
        finally:
            if process.is_alive(): process.terminate()
            process.join(10)


class GateTests(unittest.TestCase):
    def test_current_queue_pin_and_method_versions(self):
        self.assertEqual(q.BUILD, '26.911.7940.0')
        self.assertEqual(q.ASAR_SHA256, '74e7aaf2c112f84ef68a7846d10d1411403e72763f7e93fe046df2f264adf6e0')
        self.assertEqual(q.QUEUE_CONTRACT['method_versions'], {
            'thread-follower-set-queued-follow-ups-state': 1,
            'thread-queued-followups-changed': 2,
        })

    def test_explicit_rejection_with_retry_disabled(self):
        ctx = SimpleNamespace(node=Path('node'), runtime=Path.cwd())
        failure = subprocess.CompletedProcess([], 1, '', json.dumps({'schema': 1, 'type': 'ipc-rejection', 'reason': 'no-client-found'}))
        with patch.object(c, 'minimal_environment', return_value={}), patch.object(c.subprocess, 'run', return_value=failure) as call:
            with self.assertRaisesRegex(RuntimeError, 'no-client-found'):
                c.run_ipc(ctx, {'operation': 'queue-enqueue'}, retry_owner_missing=False)
            self.assertEqual(call.call_count, 1)

    def test_parser_adoption_and_acceptance_are_explicit(self):
        args = c.parser().parse_args(['--hermes-home', 'unused', '--desktop-codex-home', 'unused', 'queue', 'enqueue', '--thread', 'thread', '--prompt', 'hello'])
        self.assertFalse(args.adopt_empty_exclusive)
        self.assertFalse(args.acceptance_test)

    def test_plain_native_input_has_text_elements(self):
        # Execute the pinned native converter, not a source-string assertion or
        # a made-up input field added to the follower's composer-context payload.
        fixture = Path(__file__).with_name('fixtures')/'queue-plain-native.js'
        source = fixture.read_text(encoding='utf-8')
        item = q.build_item('id', 'hello 🌱', str(Path.cwd()))
        self.assertEqual(set(item), {'id', 'text', 'context', 'cwd', 'createdAt'})
        self.assertEqual(item['context']['fileAttachments'], [])
        script = source + '\nconst c=JSON.parse(process.argv[1]);process.stdout.write(JSON.stringify(pFt({prompt:c.prompt,message:c.untrustedAppMessage,modelContextAttachments:c.mcpAppModelContextAttachments})));'
        result = subprocess.run([shutil.which('node'), '-e', script, json.dumps(item['context'])], text=True, encoding='utf-8', capture_output=True, check=True, timeout=5)
        self.assertEqual(json.loads(result.stdout), {'input': {'type': 'text', 'text': 'hello 🌱', 'text_elements': []}, 'responseItems': []})

    def test_profile_receipt_authorizes_only_current_identity_without_flag_bypass(self):
        with tempfile.TemporaryDirectory() as root:
            ctx = context(root)
            expected = {'skill_version': '0.3.15', 'desktop': q.ASAR_SHA256}
            desktop = {'ok': True, 'build': {'version': q.BUILD,
                       'desktop_protocol_payload_sha256': q.ASAR_SHA256},
                       'processes': [{'protocol_payload': 'unused'}]}
            receipt = {'format_version': 1, 'identity': expected, 'overall_ok': True,
                       'certification_thread_id': 'designated-test',
                       'checks': {name: {'ok': True} for name in ('probe', 'send_wait_status',
                           'settings_round_trip', 'steer', 'interrupt', 'final_probe')}}
            path = c.certification_path(ctx)
            path.parent.mkdir(parents=True)
            with patch.object(c, 'platform_report', return_value={'ok': True}), \
                 patch.object(c, 'runtime_hygiene_report', return_value={'ok': True}), \
                 patch.object(c, 'schema_report', return_value={'ok': True}), \
                 patch.object(c, 'dependency_report', return_value={'ok': True}), \
                 patch.object(c, 'desktop_process_report', return_value=desktop), \
                 patch.object(c, 'compatibility_identity', return_value=expected), \
                 patch.object(c, 'scan_protocol_payload', return_value={'ok': True}):
                for flag in (False, True):
                    with patch.object(c, 'run_ipc') as ipc:
                        with self.assertRaisesRegex(RuntimeError, 'certification'):
                            q.enqueue(ctx, 'thread', 'hello', adopt_empty_exclusive=True, acceptance_test=flag)
                        ipc.assert_not_called()
                        self.assertFalse(q.slot_path(ctx, 'thread').exists())
                path.write_text(json.dumps(receipt))
                q.queue_gate(ctx, write=True)
                q.queue_gate(ctx, write=True, acceptance_test=True)
                with self.assertRaisesRegex(RuntimeError, 'certification'):
                    q.queue_gate(context(root, 'another-profile'), write=True)
                with patch.object(q, 'capture_baseline', return_value={}), \
                     patch.object(c, 'thread_cwd', return_value=root), \
                     patch.object(c, 'run_ipc', return_value={'result': {'ok': True}}) as ipc:
                    result = q.enqueue(ctx, 'thread', 'normal enqueue', adopt_empty_exclusive=True)
                    self.assertTrue(result['setter_acknowledged'])
                    self.assertEqual(ipc.call_count, 1)
                    for flag in (False, True):
                        with self.assertRaisesRegex(RuntimeError, 'reserved'):
                            q.enqueue(ctx, 'thread', 'second', adopt_empty_exclusive=True, acceptance_test=flag)
                        with self.assertRaisesRegex(RuntimeError, 'adopt'):
                            q.enqueue(ctx, 'unadopted', 'hello', acceptance_test=flag)
                    self.assertEqual(ipc.call_count, 1)
                for field, value in (('version', 'other'), ('desktop_protocol_payload_sha256', 'other')):
                    original = desktop['build'][field]
                    desktop['build'][field] = value
                    for flag in (False, True):
                        with self.assertRaisesRegex(RuntimeError, 'build'):
                            q.queue_gate(ctx, write=True, acceptance_test=flag)
                    desktop['build'][field] = original
                receipt['identity'] = {'skill_version': 'old'}
                path.write_text(json.dumps(receipt))
                for flag in (False, True):
                    with self.assertRaisesRegex(RuntimeError, 'certification'):
                        q.queue_gate(ctx, write=True, acceptance_test=flag)
                q.queue_gate(ctx, write=False)

    def test_local_status_needs_no_certification_or_native_access(self):
        with tempfile.TemporaryDirectory() as root, patch.object(q, 'queue_gate', side_effect=AssertionError('gate')), patch.object(c, 'run_ipc', side_effect=AssertionError('IPC')):
            self.assertEqual(q.status(context(root), 'thread')['state'], 'unadopted')

    def test_capability_mismatch_blocks(self):
        with patch.object(c, 'compatibility_gate'), patch.object(c, 'desktop_process_report', return_value={
            'ok': True, 'build': {'version': q.BUILD, 'desktop_protocol_payload_sha256': q.ASAR_SHA256},
            'processes': [{'protocol_payload': 'unused'}]}), patch.object(c, 'scan_protocol_payload', return_value={'ok': False}):
            with self.assertRaisesRegex(RuntimeError, 'capability'):
                q.queue_gate(None, write=True, acceptance_test=True)


class BridgeTests(unittest.TestCase):
    def exchange(self, mode='own', operation='queue-enqueue'):
        node = shutil.which('node')
        self.assertIsNotNone(node, 'Node is required for offline transport regressions')
        server = socket.socket(); server.bind(('127.0.0.1', 0)); server.listen(1); server.settimeout(8)
        seen, errors = [], []
        item = q.build_item('item-id', 'hello', str(Path.cwd()))
        def serve():
            try:
                conn, _ = server.accept()
                with conn:
                    conn.settimeout(8)
                    def send(frame):
                        data = json.dumps(frame).encode(); conn.sendall(len(data).to_bytes(4, 'little')+data)
                    def broadcast(messages, source='owner', host='local'):
                        send({'type': 'broadcast', 'method': 'thread-queued-followups-changed', 'version': 2,
                              'sourceClientId': source, 'params': {'hostId': host, 'conversationId': 'thread', 'messages': messages}})
                    def read(n):
                        result = b''
                        while len(result)<n:
                            part = conn.recv(n-len(result))
                            if not part: return None
                            result += part
                        return result
                    discoveries = 0
                    while True:
                        header = read(4)
                        if header is None: break
                        request = json.loads(read(int.from_bytes(header, 'little'))); seen.append(request)
                        method = request['method']
                        response = {'type': 'response', 'requestId': request['requestId'], 'resultType': 'success', 'result': {}}
                        if method == 'initialize': response['result'] = {'clientId': 'test'}
                        elif method == 'thread-owner-discovery':
                            discoveries += 1
                            response['handledByClientId'] = 'other' if mode == 'owner-change' and discoveries > 1 else 'owner'
                        elif method == 'thread-follower-set-queued-follow-ups-state':
                            self.assertEqual(request['version'], 1)
                            self.assertEqual(request['params'], {'conversationId': 'thread', 'state': {'thread': [item]}})
                            response['result'] = {'ok': True} if mode != 'bad-ack' else {}
                            if mode == 'own': broadcast([item])
                            if mode == 'empty-after': broadcast([item]); broadcast([])
                            if mode == 'wrong-source': broadcast([item], 'unrelated')
                            if mode == 'wrong-host': broadcast([item], host='remote')
                        else: raise AssertionError('Unexpected native method: '+method)
                        send(response)
                        if method == 'thread-owner-discovery' and discoveries == 1:
                            if mode in ('unmanaged', 'stale-history'): broadcast([{'id': 'manual'}])
                            if mode == 'stale-history': broadcast([])
                            if mode == 'malformed': broadcast(None)
            except Exception as exc: errors.append(exc)
            finally: server.close()
        worker = threading.Thread(target=serve); worker.start()
        payload = {'operation': operation, 'threadId': 'thread', 'pipe': {'host': '127.0.0.1', 'port': server.getsockname()[1]}, 'item': item, 'adoptEmptyExclusive': True, 'observeMs': 30}
        result = subprocess.run([node, '--input-type=module', '-e', c.NODE_BRIDGE], input=json.dumps(payload), text=True, capture_output=True, timeout=10)
        worker.join(10)
        if errors: raise errors[0]
        return result, seen

    def test_owner_ack_and_no_steer(self):
        result, frames = self.exchange()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['queueObservation']['kind'], 'present')
        self.assertEqual(sum(f['method']=='thread-follower-set-queued-follow-ups-state' for f in frames), 1)

    def test_unmanaged_or_owner_change_blocks_before_setter(self):
        for mode in ('unmanaged', 'owner-change', 'stale-history', 'malformed'):
            result, frames = self.exchange(mode)
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(any(f['method']=='thread-follower-set-queued-follow-ups-state' for f in frames))

    def test_silence_wrong_source_host_and_disappearance(self):
        for mode, expected in (('silence', 'unknown'), ('wrong-source', 'unknown'), ('wrong-host', 'unknown'), ('empty-after', 'empty')):
            result, _ = self.exchange(mode)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)['queueObservation']['kind'], expected)

    def test_bad_ack_and_observe_never_writes(self):
        result, _ = self.exchange('bad-ack')
        self.assertNotEqual(result.returncode, 0)
        result, frames = self.exchange(operation='queue-observe')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(any(f['method']=='thread-follower-set-queued-follow-ups-state' for f in frames))


if __name__ == '__main__':
    unittest.main(verbosity=2)
