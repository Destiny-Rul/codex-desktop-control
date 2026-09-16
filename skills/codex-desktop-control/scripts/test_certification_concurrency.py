"""Real spawned-process contention and crash-release regression tests."""
import multiprocessing as mp
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import desktop_controller as c


def holder(runtime, home, thread, phase, ready, release):
    ctx = SimpleNamespace(runtime=Path(runtime), desktop_home=Path(home))
    def pause(*args, **kwargs):
        ready.set()
        if not release.wait(15):
            raise RuntimeError('test synchronization timed out')
        return {'overall_ok': True}
    with patch.object(c, 'certification_thread_info', return_value={}), patch.object(c, 'set_thread_settings'), patch.object(c, '_certify_build_e2e', side_effect=RuntimeError('failure') if phase == 'cleanup' else lambda *a: {'overall_ok': True}), patch.object(c, 'restore_thread_settings', side_effect=pause if phase == 'restore' else None), patch.object(c, 'abort_active_certification_turn', side_effect=pause if phase == 'cleanup' else None), patch.object(c, '_atomic_json', side_effect=pause if phase == 'receipt' else None):
        try:
            c.certify_build(ctx, thread, 10, 'model', 'low')
        except RuntimeError:
            pass


class ConcurrencyTests(unittest.TestCase):
    def test_process_contention_and_crash_release(self):
        spawn = mp.get_context('spawn')
        with tempfile.TemporaryDirectory() as root:
            for phase in ('restore', 'cleanup', 'receipt'):
                ready, release = spawn.Event(), spawn.Event()
                runtime, home = str(Path(root)/'profile'), str(Path(root)/'home')
                proc = spawn.Process(target=holder, args=(runtime, home, 'thread', phase, ready, release))
                proc.start()
                try:
                    self.assertTrue(ready.wait(10), phase)
                    for profile, target, codex in ((runtime, 'other', home), (str(Path(root)/'other-profile'), 'thread', str(Path(home)/'..'/'home'))):
                        with patch.object(c, 'certification_thread_info') as eligibility, patch.object(c, 'set_thread_settings') as settings, patch.object(Path, 'unlink') as deletion:
                            with self.assertRaisesRegex(RuntimeError, 'already running'):
                                c.certify_build(SimpleNamespace(runtime=Path(profile), desktop_home=Path(codex)), target, 10, 'model', 'low')
                            eligibility.assert_not_called()
                            settings.assert_not_called()
                            deletion.assert_not_called()
                    proc.terminate()
                    proc.join(10)
                    with c.certification_locks(SimpleNamespace(runtime=Path(runtime), desktop_home=Path(home)), 'thread'):
                        pass
                finally:
                    if proc.is_alive():
                        proc.terminate()
                    proc.join(10)

    def test_cleanup_never_interrupts_unowned_turn(self):
        with patch.object(c, 'find_rollout', return_value=Path('unused')), patch.object(c, 'find_active_turn', return_value='unrelated'), patch.object(c, 'run_ipc') as ipc:
            c.abort_active_certification_turn(None, 'thread', {'owned'})
            ipc.assert_not_called()

    def test_fixture_is_bounded(self):
        import subprocess, sys
        start = time.monotonic()
        subprocess.run([sys.executable, '-c', c.certification_fixture_command()], check=True, timeout=8)
        elapsed = time.monotonic()-start
        self.assertLess(elapsed, 8)
        self.assertGreaterEqual(elapsed, 5)
        print(f'fixture measured: {elapsed:.3f}s; previous sleep budgets: 30s/120s')

    def test_cleanup_exact_owned_turn(self):
        with patch.object(c, 'find_rollout', return_value=Path('unused')), patch.object(c, 'find_active_turn', return_value='owned'), patch.object(c, 'run_ipc', return_value={'result': {'interruptedTurnId': 'owned'}}) as ipc:
            self.assertTrue(c.abort_active_certification_turn(None, 'thread', {'owned'})['interrupted'])
            self.assertEqual(ipc.call_args.args[1]['params']['expectedTurnId'], 'owned')

    def test_error_rejects_completion(self):
        self.assertFalse(c._certification_result({'status': 'completed', 'final_response': 'OK', 'error': 'renderer error'}, status='completed', response='OK')['ok'])

    def test_normal_interruption_markers(self):
        for marker in ('turn_aborted', 'turn_interrupted'):
            event = c.normalize_event({'type': 'event_msg', 'payload': {'type': marker, 'turn_id': 'owned'}})
            summary = {'status': 'interrupted', 'turn_id': 'owned', 'error': event['error']}
            self.assertTrue(c._certification_result(summary, status='interrupted')['ok'])
            self.assertFalse(c._certification_result(dict(summary, status='completed'), status='completed')['ok'])
        for error in ('renderer error', 'prefix turn_aborted', {'error': 'turn_aborted'}):
            self.assertFalse(c._certification_result({'status': 'interrupted', 'error': error}, status='interrupted')['ok'])

    def test_ack_tracking_before_running_or_summary_failure(self):
        with tempfile.TemporaryDirectory() as root:
            rollout = Path(root)/'rollout'
            rollout.touch()
            for ack, fail_summary in ((True, False), (True, True), (False, False)):
                owned = set()
                result = {'result': {'turn': {'id': 'owned'}}} if ack else {'result': {}}
                with patch.object(c, 'find_rollout', return_value=rollout), patch.object(c, 'save_job'), patch.object(c, 'run_ipc', return_value=result), patch.object(c, 'summarize_job', side_effect=RuntimeError('summary failed') if fail_summary else None, return_value={'status': 'accepted', 'turn_id': None}):
                    try:
                        c.submit_turn(None, thread_id='thread', prompt='test', model=None, effort=None, accepted_turns=owned)
                    except RuntimeError:
                        self.assertTrue(fail_summary or not ack)
                self.assertEqual(owned, {'owned'} if ack else set())

    def test_identity_invalidates_previous_certification(self):
        ctx = SimpleNamespace(lock={'skill_version': 'test'})
        build = dict(version='test', desktop_executable_sha256='a', desktop_protocol_payload_sha256='b', protocol_fingerprint_sha256='c')
        with patch.object(c, 'protocol_contract_sha256', return_value='contract'):
            identity = c.compatibility_identity(ctx, {'ok': True, 'build': build}, {'ok': True, 'migration_count': 1, 'migration_sha256': 'm'})
        self.assertEqual(identity['certification_revision'], 2)


if __name__ == '__main__':
    unittest.main(verbosity=2)
