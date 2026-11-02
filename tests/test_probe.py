import hashlib
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import probe_windows as probe  # noqa: E402
import rtl  # noqa: E402

APP = Path('/Applications/Claude.app')
if (APP / 'Contents/Resources/app.asar').exists() and rtl.is_patched(APP) and rtl.BACKUP.exists():
    APP = rtl.BACKUP
FRAMEWORK = APP / 'Contents/Frameworks/Electron Framework.framework/Electron Framework'
needs_app = unittest.skipUnless(FRAMEWORK.exists(), 'Claude.app is not installed')

SENTINEL = b'dL7pKGdnNz796PbbjQWNKmHXBZaB9tsX'


class RedactTests(unittest.TestCase):
    def test_the_user_name_is_replaced_in_every_path_form(self):
        text = r'C:\Users\Dana\AppData\Local\x and /Users/Dana/y and c:\users\dana\z'
        out = probe.redact(text, 'Dana')
        self.assertNotIn('Dana', out)
        self.assertNotIn('dana', out.lower())
        self.assertIn(r'C:\Users\<user>\AppData', out)

    def test_a_short_user_name_only_changes_whole_path_parts(self):
        self.assertEqual(probe.redact('a banana C:\\Users\\a\\x', 'a'), 'a banana C:\\Users\\<user>\\x')

    def test_an_empty_user_name_changes_nothing(self):
        self.assertEqual(probe.redact('abc', ''), 'abc')


class HashSearchTests(unittest.TestCase):
    def test_it_finds_a_hash_stored_as_ascii_and_as_utf16(self):
        h = hashlib.sha256(b'x').hexdigest()
        data = b'aa' + h.encode() + b'bb' + h.encode('utf-16-le') + b'cc'
        self.assertEqual(probe.find_hash(data, h), {'ascii': 1, 'utf16': 1})

    def test_a_missing_hash_gives_zero_counts(self):
        self.assertEqual(probe.find_hash(b'nothing', 'a' * 64), {'ascii': 0, 'utf16': 0})


class FuseTests(unittest.TestCase):
    def test_it_reads_a_fuse_wire(self):
        data = b'xx' + SENTINEL + bytes([1, 6]) + b'010r10' + b'yy'
        f = probe.read_fuses(data)
        self.assertEqual(f['version'], 1)
        self.assertEqual(f['states']['RunAsNode'], 'disabled')
        self.assertEqual(f['states']['EnableCookieEncryption'], 'enabled')
        self.assertEqual(f['states']['EnableNodeCliInspectArguments'], 'removed')
        self.assertEqual(f['states']['EnableEmbeddedAsarIntegrityValidation'], 'enabled')

    def test_no_sentinel_gives_none(self):
        self.assertIsNone(probe.read_fuses(b'no fuses here'))

    @needs_app
    def test_the_real_electron_framework_has_integrity_validation_on(self):
        f = probe.read_fuses(FRAMEWORK.read_bytes())
        self.assertIsNotNone(f)
        self.assertEqual(f['states']['EnableEmbeddedAsarIntegrityValidation'], 'enabled')


class ReportTests(unittest.TestCase):
    def test_a_report_of_a_missing_folder_says_so_and_does_not_raise(self):
        text = probe.report_for_app(Path('/no/such/claude/app'))
        self.assertIn('not found', text)
