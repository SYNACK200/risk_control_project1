"""Offline flow and safety regression tests; all database calls are in-memory."""
import contextlib
import io
import json
import pathlib
import struct
import sys
import unittest
from unittest import mock
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import provision_core as core
from fake_provision_db import FakeDriver, Cursor, is_write


def framed(value):
    data = json.dumps({'value': value}, ensure_ascii=False).encode('utf-8')
    return struct.pack('<I', len(data)) + data


class ProvisionTests(unittest.TestCase):
    def ask(self, account, phase, minimum=1):
        self.assertFalse(any(is_write(q) for q in self.db.queries))
        return 'Synthetic-' + account + '-42!'

    def setUp(self): self.db = FakeDriver()

    def test_initialization_complete(self):
        result = core.run('Initialize', apply=True, driver=self.db, ask=self.ask, confirm=lambda: None)
        self.assertTrue(result['ok'])
        self.assertEqual(len(self.db.users), 3)
        self.assertEqual(len(self.db.roles), 3)
        self.assertEqual(sum(q.startswith('CREATE USER') for q in self.db.queries), 3)

    def test_existing_accounts_never_reset(self):
        self.db = FakeDriver(populated=True)
        core.run('Initialize', apply=True, driver=self.db, ask=self.ask, confirm=lambda: None)
        self.assertFalse(any(q.startswith(('CREATE USER', 'ALTER USER')) for q in self.db.queries))

    def test_all_read_modes_no_writes(self):
        for mode in ['InspectObjects', 'InspectDown', 'VerifyAdmin', 'VerifyRuntime']:
            with self.subTest(mode=mode):
                self.db = FakeDriver(populated=True)
                result = core.run(mode, driver=self.db, ask=self.ask)
                self.assertTrue(result['ok'])
                self.assertFalse(any(is_write(q) for q in self.db.queries))

    def test_reader_cancel_before_any_write(self):
        def cancel(account, phase, minimum=1):
            if account == 'rc_demo_reader': raise KeyboardInterrupt()
            return self.ask(account, phase, minimum)
        with self.assertRaises(KeyboardInterrupt):
            core.run('Initialize', apply=True, driver=self.db, ask=cancel, confirm=lambda: None)
        self.assertFalse(core.state['writes_started'])
        self.assertFalse(any(is_write(q) for q in self.db.queries))

    def test_confirmation_mismatch_no_write(self):
        def bad(account, phase, minimum=1): return ('Synthetic-new-42!' if phase != 'confirm' else 'Synthetic-other-42!')
        with self.assertRaisesRegex(core.SafeFailure, '^CONFIRMATION_MISMATCH$'):
            core.run('Initialize', apply=True, driver=self.db, ask=bad, confirm=lambda: None)
        self.assertFalse(any(is_write(q) for q in self.db.queries))

    def test_cross_account_reuse_no_write(self):
        with self.assertRaisesRegex(core.SafeFailure, '^REUSED_CREDENTIAL$'):
            core.run('Initialize', apply=True, driver=self.db, ask=lambda *a: 'Synthetic-reused-42!', confirm=lambda: None)
        self.assertFalse(any(is_write(q) for q in self.db.queries))

    def test_bad_confirmation_no_write(self):
        def denied(): raise core.SafeFailure('CONFIRMATION_REQUIRED')
        with self.assertRaises(core.SafeFailure):
            core.run('Initialize', apply=True, driver=self.db, ask=self.ask, confirm=denied)
        self.assertFalse(any(is_write(q) for q in self.db.queries))

    def test_apply_gate(self):
        for mode, apply in [('Initialize', False), ('InspectObjects', True)]:
            with self.assertRaises(core.SafeFailure): core.run(mode, apply=apply, driver=self.db, ask=self.ask)
        self.assertEqual(self.db.login_users, [])

    def test_wrong_target_no_write(self):
        self.db.port = 3306
        with self.assertRaises(RuntimeError):
            core.run('Initialize', apply=True, driver=self.db, ask=self.ask, confirm=lambda: None)
        self.assertFalse(any(is_write(q) for q in self.db.queries))

    def test_query_logging_blocks_collection(self):
        self.db.logs = True
        with self.assertRaisesRegex(core.SafeFailure, '^QUERY_LOGGING_ENABLED$'):
            core.run('Initialize', apply=True, driver=self.db, ask=self.ask, confirm=lambda: None)
        self.assertFalse(any(is_write(q) for q in self.db.queries))

    def test_secret_validation(self):
        for value, reason in [('', 'EMPTY_INPUT'), ('x\x16y', 'CONTROL_CHARACTER'),
                              ('x\x85y', 'CONTROL_CHARACTER'), ('short', 'TOO_SHORT')]:
            with contextlib.redirect_stdout(io.StringIO()), self.assertRaisesRegex(core.SafeFailure, '^' + reason + '$'):
                core.request_secret('rc_demo_app', 'new', 16, lambda stream: value)
        for value in ['Synthetic-漢字-😀-42!', '  Synthetic!"\\$`42  ']:
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(core.request_secret('rc_demo_app', 'new', 16, lambda stream: value), value)

    def test_sequential_frames_and_eof(self):
        stream = io.BytesIO(framed('合成😀') + framed('  spaces  '))
        self.assertEqual(core.read_response(stream), '合成😀')
        self.assertEqual(core.read_response(stream), '  spaces  ')
        with self.assertRaises(core.SafeFailure): core.read_response(stream)

    def test_safe_error_protocol(self):
        original_run, original_argv = core.run, sys.argv
        def fail(*args, **kwargs): raise RuntimeError(1045, 'DO-NOT-RENDER-SYNTHETIC')
        core.run = fail
        try:
            sys.argv = ['test', 'InspectObjects', 'root']
            output = io.StringIO()
            with contextlib.redirect_stdout(output): self.assertEqual(core.main(), 1)
            self.assertNotIn('DO-NOT-RENDER', output.getvalue())
            self.assertEqual(json.loads(output.getvalue())['code'], 1045)
            self.assertEqual(json.loads(output.getvalue())['category'], 'AUTHENTICATION_REJECTED')
        finally: core.run, sys.argv = original_run, original_argv

    def test_public_entry_preserves_gates_and_no_legacy_input(self):
        bootstrap = pathlib.Path(__file__).resolve().parents[1]
        source = (bootstrap / '02_provision_users.ps1').read_text(encoding='utf-8')
        self.assertLess(source.index('preflight.ps1'), source.index('Invoke-ProvisionDialogue'))
        self.assertLess(source.index('dependencies();'), source.index('Invoke-ProvisionDialogue'))
        self.assertIn("($Mode -eq 'Initialize') -ne [bool]$Apply", source)
        self.assertIn('IsInputRedirected', source)
        for name in ['02_provision_users.ps1', 'provision_core.py', 'credential_pipe.ps1']:
            text = (bootstrap / name).read_text(encoding='utf-8')
            self.assertNotIn('getpass', text)
            self.assertNotIn('windows_console', text)
        self.assertIn('Read-Host', (bootstrap / 'credential_pipe.ps1').read_text(encoding='utf-8'))

    def test_creation_passwords_are_bound_to_correct_accounts(self):
        original = Cursor.execute
        seen = set()
        def inspect(cursor, sql, args=None):
            if sql.startswith('CREATE USER'):
                self.assertEqual(args[1], 'Synthetic-' + args[0] + '-42!')
                self.assertIsInstance(args[1], str)
                seen.add(args[0])
            return original(cursor, sql, args)
        with mock.patch.object(Cursor, 'execute', inspect):
            core.run('Initialize', apply=True, driver=self.db, ask=self.ask, confirm=lambda: None)
        self.assertEqual(seen, {u for u, r in core.pairs})

    def test_single_runtime_auth_is_read_only_and_selects_one_account(self):
        self.db = FakeDriver(populated=True)
        result = core.run('AuthenticateRuntime', admin='rc_demo_app', driver=self.db, ask=self.ask)
        self.assertTrue(result['ok'])
        self.assertEqual(self.db.login_users, ['rc_demo_app'])
        self.assertFalse(any(is_write(q) for q in self.db.queries))

    def test_runtime_metadata_selects_no_password_hash(self):
        self.db = FakeDriver(populated=True)
        result = core.run('InspectObjects', driver=self.db, ask=self.ask)
        self.assertEqual(len(result['runtime_accounts']), 3)
        self.assertTrue(all(row[2:4] == ('N', 'caching_sha2_password') for row in result['runtime_accounts']))
        self.assertFalse(any('authentication_string' in q.lower() for q in self.db.queries))

    def test_single_auth_separates_role_failure(self):
        self.db = FakeDriver(populated=True)
        self.db.bindings.clear()
        self.assertTrue(core.run('AuthenticateRuntime', admin='rc_demo_app', driver=self.db, ask=self.ask)['ok'])
        with self.assertRaisesRegex(core.SafeFailure, '^ROLE_MISMATCH$'):
            core.run('VerifyRuntime', driver=self.db, ask=self.ask)
        self.assertFalse(any(is_write(q) for q in self.db.queries))

    def test_unified_acceptance_read_only_and_four_logins(self):
        self.db = FakeDriver(populated=True)
        result = core.run('AcceptDA01', driver=self.db, ask=self.ask)
        self.assertTrue(result['ok'])
        self.assertEqual(len(result['checks']), 5)
        self.assertEqual(self.db.login_users, ['root'] + [u for u, r in core.pairs])
        self.assertFalse(any(is_write(q) for q in self.db.queries))

    def test_unified_acceptance_continues_after_1045(self):
        self.db = FakeDriver(populated=True)
        original = self.db.connect
        def selective(**kwargs):
            if kwargs['user'] == 'rc_demo_app': raise RuntimeError(1045, 'NEVER-RENDER')
            return original(**kwargs)
        self.db.connect = selective
        result = core.run('AcceptDA01', driver=self.db, ask=self.ask)
        self.assertFalse(result['ok'])
        self.assertEqual(result['checks'][2]['code'], 1045)
        self.assertEqual(result['checks'][2]['category'], 'AUTHENTICATION_REJECTED')
        self.assertTrue(result['checks'][3]['ok'] and result['checks'][4]['ok'])
        self.assertNotIn('NEVER-RENDER', str(result))
        self.assertFalse(any(is_write(q) for q in self.db.queries))


if __name__ == '__main__': unittest.main()
