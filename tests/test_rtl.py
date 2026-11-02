import hashlib
import json
import plistlib
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import rtl  # noqa: E402

HERE = Path(__file__).resolve().parent.parent
STATE = Path('/tmp/claude-rtl-test/state.json')
APP = Path('/Applications/Claude.app')
# After an in-place install the app in /Applications is the patched one. These tests
# need the unpatched original, which the install keeps.
if (APP / 'Contents/Resources/app.asar').exists() and rtl.is_patched(APP) and rtl.BACKUP.exists():
    APP = rtl.BACKUP
ASAR = APP / 'Contents/Resources/app.asar'
MAIN = '.vite/build/index.pre.js'
needs_app = unittest.skipUnless(ASAR.exists(), 'Claude.app is not installed')


def file_hashes(path):
    header, _, base = rtl.read_asar(path)
    out = {}
    with open(path, 'rb') as f:
        for name, node in rtl.nodes(header):
            f.seek(base + int(node['offset']))
            out[name] = hashlib.sha256(f.read(node['size'])).hexdigest()
    return out


@needs_app
class AsarTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.same = Path(cls.tmp.name) / 'same.asar'
        cls.patched = Path(cls.tmp.name) / 'patched.asar'
        rtl.write_asar(ASAR, cls.same, {})
        rtl.write_asar(ASAR, cls.patched, {MAIN: rtl.patched_main(rtl.read_file(ASAR, MAIN), rtl.make_snippet(HERE, STATE))})

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_header_hash_matches_the_app_own_integrity_value(self):
        want = plistlib.loads((APP / 'Contents/Info.plist').read_bytes())['ElectronAsarIntegrity']['Resources/app.asar']['hash']
        self.assertEqual(rtl.header_hash(ASAR), want)

    def test_unchanged_repack_has_the_same_header_hash(self):
        self.assertEqual(rtl.header_hash(self.same), rtl.header_hash(ASAR))

    def test_unchanged_repack_keeps_every_file(self):
        self.assertEqual(file_hashes(self.same), file_hashes(ASAR))

    def test_patch_changes_only_the_main_file(self):
        old, new = file_hashes(ASAR), file_hashes(self.patched)
        self.assertEqual(old.keys(), new.keys())
        self.assertEqual([k for k in old if old[k] != new[k]], [MAIN])

    def test_patch_changes_exactly_one_header_node(self):
        old, _, _ = rtl.read_asar(ASAR)
        new, _, _ = rtl.read_asar(self.patched)
        old_nodes, new_nodes = dict(rtl.nodes(old)), dict(rtl.nodes(new))
        self.assertEqual([k for k in old_nodes if old_nodes[k] != new_nodes[k]], [MAIN])

    def test_patched_asar_passes_the_integrity_check_the_app_runs(self):
        self.assertEqual(rtl.verify_asar(self.patched), [])
        self.assertNotEqual(rtl.header_hash(self.patched), rtl.header_hash(ASAR))

    def test_verify_catches_a_flipped_byte(self):
        bad = Path(self.tmp.name) / 'bad.asar'
        data = bytearray(self.patched.read_bytes())
        data[-5] ^= 1
        bad.write_bytes(bytes(data))
        self.assertNotEqual(rtl.verify_asar(bad), [])

    def test_patched_main_starts_with_the_directive_then_the_snippet(self):
        new = rtl.read_file(self.patched, MAIN)
        self.assertTrue(new.startswith(b'"use strict";;(() => {'))
        self.assertIn(b'claude-rtl-menu', new)
        self.assertEqual(new.count(b'__RTL_PAYLOAD__'), 0)


class SnippetTests(unittest.TestCase):
    def test_the_token_appears_once_and_is_replaced_once(self):
        self.assertEqual((HERE / 'main-snippet.js').read_text().count('__RTL_PAYLOAD__'), 1)
        self.assertNotIn('__RTL_PAYLOAD__', rtl.make_snippet(HERE, STATE))

    def test_the_built_snippet_is_valid_javascript(self):
        with tempfile.NamedTemporaryFile('w', suffix='.js') as f:
            f.write(rtl.make_snippet(HERE, STATE))
            f.flush()
            self.assertEqual(subprocess.run(['node', '--check', f.name]).returncode, 0)

    def test_no_network_eval_or_secret_apis_in_what_ships(self):
        text = rtl.make_snippet(HERE, STATE)
        # A deny list: none of these may appear in the shipped code. The test fails if one does.
        for bad in ['child_process', "require('http", 'require("http', 'require("net', "require('net", 'fetch(', 'XMLHttpRequest',
                    'WebSocket', 'sendBeacon', 'eval(', 'new Function', 'import(', 'document.cookie', 'localStorage',
                    'session.cookies', 'safeStorage']:
            self.assertNotIn(bad, text, bad)

    def test_patched_main_refuses_an_unexpected_file(self):
        with self.assertRaises(ValueError):
            rtl.patched_main(b'(function(){})()', 'x')

    def test_the_state_path_is_baked_in_as_one_quoted_string(self):
        self.assertEqual((HERE / 'main-snippet.js').read_text().count('__RTL_STATE__'), 1)
        odd = Path('/tmp/a "b"/state.json')
        text = rtl.make_snippet(HERE, odd)
        self.assertIn(json.dumps(str(odd)), text)
        self.assertNotIn('__RTL_STATE__', text)


class InstallTests(unittest.TestCase):
    def test_the_default_state_file_is_in_application_support(self):
        self.assertEqual(rtl.state_path(None), Path.home() / 'Library/Application Support/Claude-RTL/state.json')

    def test_a_given_state_file_is_expanded_and_absolute(self):
        self.assertEqual(rtl.state_path('~/x/state.json'), Path.home() / 'x/state.json')
        self.assertTrue(rtl.state_path('rel.json').is_absolute())

    def test_a_symlinked_state_file_keeps_the_link_not_the_target(self):
        d = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, d, True)
        target, link = d / 'dotfiles' / 'rtl.json', d / 'rtl.json'
        target.parent.mkdir()
        target.write_text('{}')
        link.symlink_to(target)
        self.assertEqual(rtl.state_path(str(link)), link)

    def test_problems_name_a_missing_app(self):
        self.assertTrue(any('not found' in p for p in rtl.problems(Path('/nonexistent/Claude.app'))))

    def test_problems_name_a_system_that_is_not_a_mac(self):
        with mock.patch.object(rtl.sys, 'platform', 'linux'):
            self.assertTrue(any('macOS' in p for p in rtl.problems(Path('/nonexistent'))))

    def test_problems_name_an_old_python(self):
        with mock.patch.object(rtl.sys, 'version_info', (3, 8, 0)):
            self.assertTrue(any('Python 3.9' in p for p in rtl.problems(Path('/nonexistent'))))

    @needs_app
    def test_a_real_install_of_claude_has_no_problems(self):
        self.assertEqual(rtl.problems(APP), [])

    def test_running_finds_only_processes_inside_the_copy(self):
        ps = ('  101 /Users/x/Applications/Claude-RTL.app/Contents/MacOS/Claude\n'
              '  102 /Users/x/Applications/Claude-RTL.app/Contents/Frameworks/Claude Helper.app/Contents/MacOS/Claude Helper --type=gpu\n'
              '  103 /Applications/Claude.app/Contents/MacOS/Claude\n'
              '  104 /Users/x/Applications/Claude-RTL.app.bak/Contents/MacOS/Claude\n')
        self.assertEqual(rtl.running(Path('/Users/x/Applications/Claude-RTL.app'), ps), [101, 102])

    def test_an_install_stops_when_the_copy_is_running(self):
        with mock.patch.object(rtl, 'problems', return_value=[]), mock.patch.object(rtl, 'running', return_value=[42]):
            with self.assertRaises(SystemExit) as cm:
                rtl.install(APP, Path.home() / 'Applications/Claude-RTL.app', STATE, force=True)
        self.assertIn('Quit', str(cm.exception))

    def test_an_install_stops_and_lists_every_problem(self):
        with mock.patch.object(rtl, 'problems', return_value=['one', 'two']):
            with self.assertRaises(SystemExit) as cm:
                rtl.install(APP, Path.home() / 'Applications/Claude-RTL.app', STATE)
        self.assertEqual(str(cm.exception), 'one\ntwo')


FRAMEWORK = APP / rtl.FRAMEWORK


class DigestTests(unittest.TestCase):
    """Electron checks the whole ElectronAsarIntegrity dictionary against a SHA-256
    digest stored inside the Electron Framework binary. A new app hash needs a new digest."""
    SENT = rtl.SENTINEL

    def slot(self, digest, used=1, version=1):
        return self.SENT + bytes([used, version]) + digest

    @needs_app
    def test_digest_reproduces_the_value_the_app_stores(self):
        integ = plistlib.loads((APP / 'Contents/Info.plist').read_bytes())['ElectronAsarIntegrity']
        found = {d for _, d in rtl.digest_slots(FRAMEWORK.read_bytes())}
        self.assertEqual(found, {rtl.integrity_digest(integ)})

    def test_digest_changes_with_the_app_hash_and_ignores_key_order(self):
        a = {'Resources/app.asar': {'algorithm': 'SHA256', 'hash': 'aa'}, 'Resources/b.asar': {'algorithm': 'SHA256', 'hash': 'bb'}}
        b = {'Resources/b.asar': a['Resources/b.asar'], 'Resources/app.asar': a['Resources/app.asar']}
        c = {**a, 'Resources/app.asar': {'algorithm': 'SHA256', 'hash': 'cc'}}
        self.assertEqual(rtl.integrity_digest(a), rtl.integrity_digest(b))
        self.assertNotEqual(rtl.integrity_digest(a), rtl.integrity_digest(c))

    def test_patch_replaces_every_matching_slot_and_nothing_else(self):
        old, new = b'o' * 32, b'n' * 32
        data = b'head' + self.slot(old) + b'mid' + self.slot(old) + b'tail'
        out = rtl.patch_digest(data, old, new)
        self.assertEqual(out, b'head' + self.slot(new) + b'mid' + self.slot(new) + b'tail')
        self.assertEqual(len(out), len(data))

    def test_patch_leaves_a_slot_with_another_digest_alone(self):
        old, new, other = b'o' * 32, b'n' * 32, b'x' * 32
        data = self.slot(old) + b'|' + self.slot(other)
        self.assertEqual(rtl.patch_digest(data, old, new), self.slot(new) + b'|' + self.slot(other))

    def test_patch_refuses_when_no_slot_matches(self):
        with self.assertRaises(ValueError):
            rtl.patch_digest(self.slot(b'x' * 32), b'o' * 32, b'n' * 32)

    def test_patch_refuses_an_unknown_slot_version(self):
        with self.assertRaises(ValueError):
            rtl.patch_digest(self.slot(b'o' * 32, version=2), b'o' * 32, b'n' * 32)


class SmokeTests(unittest.TestCase):
    """smoke() must call a run that dies on its own a failure, and a run the timer ends a success."""

    def fake_app(self, script):
        d = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, d, True)
        exe = d / 'Contents/MacOS/Claude'
        exe.parent.mkdir(parents=True)
        exe.write_text('#!/bin/sh\n' + script)
        exe.chmod(0o755)
        return d

    def test_a_run_that_prints_fatal_and_dies_fails(self):
        app = self.fake_app('echo "[1:FATAL:archive.cc:1] bad" >&2\nexit 133\n')
        ok, detail = rtl.smoke(app, seconds=3)
        self.assertFalse(ok)
        self.assertIn('FATAL', detail)

    def test_a_run_that_lives_until_the_timer_passes(self):
        app = self.fake_app('exec sleep 30\n')
        ok, detail = rtl.smoke(app, seconds=1)
        self.assertTrue(ok, detail)

    def test_a_run_that_exits_early_without_a_message_fails(self):
        app = self.fake_app('exit 0\n')
        self.assertFalse(rtl.smoke(app, seconds=3)[0])


class PlistTests(unittest.TestCase):
    def test_sets_only_the_app_asar_hash(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'Info.plist'
            p.write_bytes(plistlib.dumps({'CFBundleName': 'Claude', 'ElectronAsarIntegrity': {
                'Resources/app.asar': {'algorithm': 'SHA256', 'hash': 'old'},
                'Resources/ion-dist.asar': {'algorithm': 'SHA256', 'hash': 'keep'}}}))
            rtl.set_asar_hash(p, 'new')
            got = plistlib.loads(p.read_bytes())
            self.assertEqual(got['ElectronAsarIntegrity']['Resources/app.asar']['hash'], 'new')
            self.assertEqual(got['ElectronAsarIntegrity']['Resources/ion-dist.asar']['hash'], 'keep')
            self.assertEqual(got['CFBundleName'], 'Claude')


class SafetyTests(unittest.TestCase):
    def test_remove_refuses_any_path_that_is_not_the_rtl_copy(self):
        for bad in ['/Applications/Claude.app', str(Path.home()), '/', str(Path.home() / 'Applications/Other.app')]:
            with self.assertRaises(ValueError, msg=bad):
                rtl.remove(Path(bad))

    def test_build_refuses_to_write_over_the_original_app(self):
        with self.assertRaises(ValueError):
            rtl.build(APP, APP, STATE)


if __name__ == '__main__':
    unittest.main()


def fake_app(root, name, note):
    app = Path(root) / name
    (app / 'Contents').mkdir(parents=True)
    (app / 'Contents/note.txt').write_text(note)
    return app


class SwapTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.src = fake_app(self.tmp.name, 'Claude.app', 'original')
        self.staged = fake_app(self.tmp.name, 'Claude-RTL.app', 'patched')
        self.backup = Path(self.tmp.name) / 'keep' / 'Claude.original.app'

    def note(self, app):
        return (Path(app) / 'Contents/note.txt').read_text()

    def test_swap_in_puts_the_patch_in_place_and_keeps_the_original(self):
        rtl.swap_in(self.src, self.staged, self.backup)
        self.assertEqual(self.note(self.src), 'patched')
        self.assertEqual(self.note(self.backup), 'original')
        self.assertFalse(self.staged.exists())

    def test_swap_in_replaces_an_older_backup(self):
        fake_app(self.backup.parent, 'Claude.original.app', 'older')
        rtl.swap_in(self.src, self.staged, self.backup)
        self.assertEqual(self.note(self.backup), 'original')

    def test_swap_in_puts_the_original_back_when_the_patch_will_not_move(self):
        shutil.rmtree(self.staged)
        with self.assertRaises(OSError):
            rtl.swap_in(self.src, self.staged, self.backup)
        self.assertEqual(self.note(self.src), 'original')

    def test_swap_in_stops_while_the_app_runs(self):
        with mock.patch.object(rtl, 'running', side_effect=lambda app: [42] if Path(app) == self.src else []):
            with self.assertRaises(SystemExit):
                rtl.swap_in(self.src, self.staged, self.backup)
        self.assertEqual(self.note(self.src), 'original')

    def test_swap_out_restores_the_original(self):
        rtl.swap_in(self.src, self.staged, self.backup)
        rtl.swap_out(self.src, self.backup)
        self.assertEqual(self.note(self.src), 'original')
        self.assertFalse(self.backup.exists())

    def test_swap_out_without_a_backup_changes_nothing(self):
        with self.assertRaises(SystemExit):
            rtl.swap_out(self.src, self.backup)
        self.assertEqual(self.note(self.src), 'original')


@needs_app
class PatchedTests(unittest.TestCase):
    def test_is_patched_tells_the_original_from_the_patched_app(self):
        with tempfile.TemporaryDirectory() as tmp:
            plain = Path(tmp) / 'a.app'
            patched = Path(tmp) / 'b.app'
            for app in (plain, patched):
                (app / 'Contents/Resources').mkdir(parents=True)
            shutil.copy(ASAR, plain / 'Contents/Resources/app.asar')
            rtl.write_asar(ASAR, patched / 'Contents/Resources/app.asar',
                           {MAIN: rtl.patched_main(rtl.read_file(ASAR, MAIN), rtl.make_snippet(HERE, STATE))})
            self.assertFalse(rtl.is_patched(plain))
            self.assertTrue(rtl.is_patched(patched))


class AgentTests(unittest.TestCase):
    def test_the_agent_runs_repair_on_a_timer_and_at_login(self):
        plist = plistlib.loads(rtl.agent_plist(Path('/x/rtl.py'), Path('/s/state.json')))
        self.assertEqual(plist['Label'], 'com.danan000.claude-rtl')
        self.assertEqual(plist['ProgramArguments'][1:4], ['/x/rtl.py', 'repair', '--state-file'])
        self.assertTrue(plist['RunAtLoad'])
        self.assertEqual(plist['StartInterval'], 600)


class RepairTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.failed = Path(self.tmp.name) / 'failed-version'

    def run_repair(self, patched=False, pids=(), failed_with=None):
        if failed_with:
            self.failed.write_text(failed_with)
        with mock.patch.object(rtl, 'is_patched', return_value=patched), \
                mock.patch.object(rtl, 'running', return_value=list(pids)), \
                mock.patch.object(rtl, 'version', return_value='9.9'), \
                mock.patch.object(rtl, 'install_in_place') as put:
            note = rtl.repair('src', 'dest', 'state', failed=self.failed)
        return note, put

    def test_a_patched_app_is_left_alone(self):
        note, put = self.run_repair(patched=True)
        self.assertEqual(note, 'patched')
        put.assert_not_called()

    def test_an_update_is_repaired_when_claude_is_not_running(self):
        note, put = self.run_repair()
        self.assertEqual(note, 'repaired')
        put.assert_called_once()

    def test_a_running_claude_waits(self):
        note, put = self.run_repair(pids=[7])
        self.assertTrue(note.startswith('waiting'))
        put.assert_not_called()

    def test_a_version_that_failed_before_is_not_tried_again(self):
        note, put = self.run_repair(failed_with='9.9')
        self.assertTrue(note.startswith('skipped'))
        put.assert_not_called()

    def test_a_newer_version_is_tried_after_a_failure(self):
        note, put = self.run_repair(failed_with='9.8')
        self.assertEqual(note, 'repaired')

    def test_a_failed_repair_marks_the_version(self):
        with mock.patch.object(rtl, 'is_patched', return_value=False), \
                mock.patch.object(rtl, 'running', return_value=[]), \
                mock.patch.object(rtl, 'version', return_value='9.9'), \
                mock.patch.object(rtl, 'install_in_place', side_effect=SystemExit(1)):
            with self.assertRaises(SystemExit):
                rtl.repair('src', 'dest', 'state', failed=self.failed)
        self.assertEqual(self.failed.read_text(), '9.9')


class RelaunchTests(unittest.TestCase):
    def test_stage_tool_copies_what_repair_needs_to_a_stable_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            script = rtl.stage_tool(Path(tmp) / 'tool')
            self.assertEqual(script, Path(tmp) / 'tool' / 'rtl.py')
            for name in ('rtl.py', 'payload.js', 'main-snippet.js'):
                self.assertEqual((Path(tmp) / 'tool' / name).read_bytes(), (HERE / name).read_bytes())

    def test_the_relaunch_script_is_valid_bash_and_does_the_four_steps(self):
        text = rtl.relaunch_script(Path('/t/rtl.py'), Path('/my state/s.json'), Path('/l/log'), delay=3)
        with tempfile.NamedTemporaryFile('w', suffix='.sh', delete=False) as f:
            f.write(text)
        self.addCleanup(Path(f.name).unlink)
        self.assertEqual(subprocess.run(['bash', '-n', f.name]).returncode, 0)
        self.assertIn('kill -TERM', text)
        self.assertIn("install --in-place --state-file '/my state/s.json'", text)
        self.assertIn('open /Applications/Claude.app', text)
        self.assertIn('sleep 3', text)

    def test_the_relaunch_script_opens_claude_even_when_the_install_fails(self):
        text = rtl.relaunch_script(Path('/t/rtl.py'), Path('/s.json'), Path('/l/log'))
        self.assertLess(text.index('install --in-place'), text.index('open /Applications/Claude.app'))
        self.assertNotIn('set -e', text)


class StatusTests(unittest.TestCase):
    def test_after_an_update_status_names_the_update_and_the_repair(self):
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(rtl, 'is_patched', return_value=False), \
                mock.patch.object(rtl, 'version', return_value='9.9'), \
                mock.patch.object(rtl, 'BACKUP', Path(tmp)), \
                mock.patch('builtins.print') as out:
            code = rtl.status('src', Path(tmp) / 'no-copy')
        self.assertEqual(code, 1)
        line = out.call_args[0][0]
        self.assertIn('update', line)
        self.assertIn('repair', line)


class ReinstallTests(unittest.TestCase):
    def test_a_second_in_place_install_changes_nothing_and_keeps_the_original(self):
        with mock.patch.object(rtl, 'is_patched', return_value=True), \
                mock.patch.object(rtl, 'install') as build, \
                mock.patch.object(rtl, 'swap_in') as swap, \
                mock.patch('builtins.print'):
            rtl.install_in_place(Path('/Applications/Claude.app'), Path('/x/Claude-RTL.app'), Path('/s.json'))
        build.assert_not_called()
        swap.assert_not_called()

    def test_patched_main_refuses_a_file_that_is_already_patched(self):
        once = rtl.patched_main(b'"use strict";var a=1', 'SNIPPET claude-rtl-menu')
        with self.assertRaises(ValueError):
            rtl.patched_main(once, 'SNIPPET claude-rtl-menu')


class UninstallRelaunchTests(unittest.TestCase):
    def test_the_uninstall_job_runs_uninstall_and_opens_claude(self):
        text = rtl.relaunch_script(Path('/t/rtl.py'), Path('/s.json'), Path('/l/log'), action='uninstall')
        self.assertIn("/t/rtl.py uninstall", text)
        self.assertNotIn('install --in-place', text)
        self.assertLess(text.index('uninstall'), text.index('open /Applications/Claude.app'))
