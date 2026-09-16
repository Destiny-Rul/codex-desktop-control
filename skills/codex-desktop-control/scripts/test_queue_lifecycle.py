"""Baseline-scoped persisted queue lifecycle; no Desktop IPC is used."""
import json
import multiprocessing as mp
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import desktop_controller as c
import native_queue as q


def event(kind, **fields):
    return {'type': 'event_msg', 'payload': {'type': kind, **fields}}


def archive_holder(root, ready, release):
    root=Path(root)
    ctx=SimpleNamespace(desktop_home=root/'codex', runtime=root/'profile')
    original=q.archive_terminal
    def pause(*args):
        path=original(*args)
        ready.set()
        if not release.wait(10): raise RuntimeError('test timeout')
        return path
    with patch.object(q,'slot_root',return_value=root/'slots'), patch.object(c,'find_rollout',return_value=root/'codex'/'sessions'/'rollout.jsonl'), patch.object(q,'archive_terminal',side_effect=pause):
        q.status(ctx,'thread')


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.ctx = SimpleNamespace(desktop_home=self.root/'codex', runtime=self.root/'profile')
        self.rollout = self.ctx.desktop_home/'sessions'/'rollout.jsonl'
        self.rollout.parent.mkdir(parents=True)
        self.rollout.write_text(json.dumps({'type':'session_meta','payload':{'id':'thread','session_id':'thread'}})+'\n', encoding='utf-8')
        self.patches = [patch.object(q,'slot_root',return_value=self.root/'slots'),
                        patch.object(q,'queue_gate'), patch.object(c,'find_rollout',return_value=self.rollout),
                        patch.object(c,'thread_cwd',return_value=str(self.root))]
        for p in self.patches: p.start()

    def tearDown(self):
        for p in reversed(self.patches): p.stop()
        self.tmp.cleanup()

    def append(self, *records):
        with self.rollout.open('a',encoding='utf-8') as f:
            for record in records: f.write(json.dumps(record)+'\n')

    def enqueue(self, adoption=True, uncertain=False):
        with patch.object(c,'run_ipc',side_effect=RuntimeError('uncertain') if uncertain else None,
                          return_value={'result':{'ok':True}}):
            return q.enqueue(self.ctx,'thread','hello',adopt_empty_exclusive=adoption,acceptance_test=True)

    def mapping(self, item, turn='turn', thread='thread', message='user-item'):
        return event('item_completed',thread_id=thread,turn_id=turn,
                     item={'type':'UserMessage','id':message,'client_id':item['id']})

    def finish(self, record, kind='task_complete', turn='turn'):
        self.append(event('task_started',turn_id=turn), self.mapping(record['item'],turn), event(kind,turn_id=turn))

    def status(self, **kwargs):
        with patch.object(c,'run_ipc',side_effect=AssertionError('Local status must not use IPC')):
            return q.status(self.ctx,'thread',**kwargs)

    def test_two_cycles_archive_before_release_and_reuse_adoption(self):
        first=self.enqueue(); self.finish(first)
        status=self.status()
        self.assertEqual(status['state'],'completed'); self.assertFalse(status['slot_reserved'])
        receipt=Path(status['terminal_receipt']); original=receipt.read_bytes()
        self.assertEqual(json.loads(original)['evidence']['mapping']['payload']['item']['client_id'],first['item']['id'])
        self.assertEqual(self.status()['terminal_receipt'],str(receipt))
        second=self.enqueue(adoption=False); self.assertNotEqual(second['item']['id'],first['item']['id'])
        self.finish(second,turn='second-turn'); end=self.status()
        self.assertFalse(end['slot_reserved']); self.assertEqual(receipt.read_bytes(),original)
        self.assertNotEqual(end['terminal_receipt'],str(receipt))

    def test_running_then_each_terminal_status(self):
        for kind, state in [('task_complete','completed'),('task_failed','failed'),('turn_aborted','interrupted'),('turn_interrupted','interrupted')]:
            record=self.enqueue(adoption=True)
            self.append(event('task_started',turn_id=kind), self.mapping(record['item'],kind))
            self.assertEqual(self.status()['state'],'running')
            self.append(event(kind,turn_id=kind))
            status=self.status(); self.assertEqual(status['state'],state); self.assertFalse(status['slot_reserved'])

    def test_uncertain_submission_resolved_only_by_exact_evidence(self):
        record=self.enqueue(uncertain=True)
        self.assertTrue(self.status()['slot_reserved'])
        self.finish(record); self.assertEqual(self.status()['state'],'completed')

    def test_prompt_time_and_old_mapping_do_not_correlate(self):
        self.append(event('task_started',turn_id='old'),self.mapping({'id':'old-id'},'old'),event('task_complete',turn_id='old'))
        build=q.build_item
        with patch.object(q,'build_item',side_effect=lambda item,prompt,cwd:build('old-id',prompt,cwd)):
            record=self.enqueue()
        self.append(event('task_started',turn_id='new'),event('task_complete',turn_id='new',last_agent_message='hello'))
        status=self.status(); self.assertTrue(status['slot_reserved']); self.assertIsNone(status['turn_id'])
        self.assertGreater(record['rollout_baseline']['offset'],0)

    def test_wrong_thread_duplicate_mapping_and_out_of_order_terminal(self):
        record=self.enqueue()
        base=self.rollout.read_bytes()
        cases=[(event('task_started',turn_id='turn'),self.mapping(record['item'],thread='other'),event('task_complete',turn_id='turn')),
               (event('task_started',turn_id='turn'),self.mapping(record['item']),self.mapping(record['item'],'other-turn'),event('task_complete',turn_id='turn')),
               (event('task_complete',turn_id='turn'),event('task_started',turn_id='turn'),self.mapping(record['item'])),
               (event('task_started',turn_id='turn'),self.mapping(record['item']),event('task_complete',turn_id='turn',error='real error'))]
        for records in cases:
            self.rollout.write_bytes(base); self.append(*records)
            status=self.status(); self.assertEqual(status['state'],'unknown'); self.assertTrue(status['slot_reserved'])

    def test_malformed_partial_rewritten_and_truncated_rollout(self):
        record=self.enqueue(); base=self.rollout.read_bytes()
        for tail in (b'{bad}\n',b'{"partial":',b'[]\n'):
            self.rollout.write_bytes(base+tail)
            self.assertTrue(self.status()['slot_reserved'])
        self.rollout.write_bytes(base)
        self.append(event('task_started',turn_id='turn'),self.mapping(record['item']))
        self.assertEqual(self.status()['state'],'running')
        self.rollout.write_bytes(base)
        self.assertEqual(self.status()['state'],'unknown')
        self.rollout.write_bytes(base.replace(b'thread',b'others'))
        self.assertEqual(self.status()['state'],'unknown')

    def test_session_and_database_identity_validation(self):
        self.enqueue()
        with patch.object(c,'find_rollout',return_value=self.root/'different'):
            self.assertTrue(self.status()['slot_reserved'])
        self.rollout.write_text(json.dumps({'type':'session_meta','payload':{'id':'wrong'}})+'\n',encoding='utf-8')
        self.assertEqual(self.status()['state'],'unknown')

    def test_archive_failure_keeps_slot_and_crash_recovery_is_idempotent(self):
        record=self.enqueue(); self.finish(record)
        with patch.object(q,'archive_terminal',side_effect=OSError('disk full')):
            self.assertTrue(self.status()['slot_reserved'])
        real=q.persist
        def fail_release(path,value):
            if value.get('slot_reserved') is False: raise OSError('crash after archive')
            return real(path,value)
        with patch.object(q,'persist',side_effect=fail_release):
            with self.assertRaises(OSError): self.status()
        status=self.status(); self.assertFalse(status['slot_reserved'])
        data=Path(status['terminal_receipt']).read_bytes()
        self.status(); self.assertEqual(Path(status['terminal_receipt']).read_bytes(),data)

    def test_owner_change_does_not_replace_exact_persisted_mapping(self):
        record=self.enqueue(); self.finish(record)
        with patch.object(c,'run_ipc',return_value={'ownerClientId':'new-owner','queueObservation':{'kind':'unknown'}}) as ipc:
            status=q.status(self.ctx,'thread',observe=True)
            self.assertEqual(status['state'],'completed'); self.assertEqual(ipc.call_args.args[1]['operation'],'queue-observe')

    def test_unmanaged_conflict_sticky_blocks_reuse(self):
        record=self.enqueue()
        with patch.object(c,'run_ipc',return_value={'queueObservation':{'kind':'present','messages':[{'id':'other'}]}}):
            q.status(self.ctx,'thread',observe=True)
        self.finish(record); self.status()
        with self.assertRaisesRegex(RuntimeError,'provenance'):
            self.enqueue(adoption=True)

    def test_legacy_baseline_import_is_explicit_and_validated(self):
        legacy={'schema':1,'identity':list(q.identity(self.ctx,'thread')),'item':q.build_item('legacy','hello',str(self.root)),
                'slot_reserved':True,'state':'unknown','adopted_empty_exclusive':True,'build':q.BUILD,'asar_sha256':q.ASAR_SHA256}
        q.persist(q.slot_path(self.ctx,'thread'),legacy)
        offset=self.rollout.stat().st_size
        self.finish(legacy)
        self.assertTrue(self.status()['slot_reserved'])
        evidence=self.root/'baseline.json'
        evidence.write_text(json.dumps({'thread':'wrong','rollout_bytes':offset,'settings':{'rollout_path':str(self.rollout)}}))
        self.assertTrue(self.status(baseline_evidence=evidence)['slot_reserved'])
        evidence.write_text(json.dumps({'thread':'thread','rollout_bytes':offset,'settings':{'rollout_path':str(self.rollout)}}))
        self.assertEqual(self.status(baseline_evidence=evidence)['state'],'completed')

    def test_archive_release_is_locked_across_profiles_and_processes(self):
        record=self.enqueue(); self.finish(record)
        spawn=mp.get_context('spawn'); ready,release=spawn.Event(),spawn.Event()
        process=spawn.Process(target=archive_holder,args=(str(self.root),ready,release)); process.start()
        try:
            self.assertTrue(ready.wait(10))
            other=SimpleNamespace(desktop_home=self.root/'codex'/'..'/'codex',runtime=self.root/'other-profile')
            with patch.object(c,'run_ipc') as ipc:
                with self.assertRaisesRegex(RuntimeError,'already running'):
                    q.enqueue(other,'thread','competing',acceptance_test=True)
                ipc.assert_not_called()
            release.set(); process.join(10); self.assertEqual(process.exitcode,0)
            self.assertFalse(self.status()['slot_reserved'])
        finally:
            if process.is_alive(): process.terminate()
            process.join(10)

    def test_changed_archive_cannot_authorize_reuse(self):
        record=self.enqueue(); self.finish(record); status=self.status()
        Path(status['terminal_receipt']).write_text('{}')
        with patch.object(c,'run_ipc') as ipc:
            with self.assertRaisesRegex(RuntimeError,'receipt'):
                self.enqueue(adoption=False)
            ipc.assert_not_called()


if __name__=='__main__': unittest.main(verbosity=2)
