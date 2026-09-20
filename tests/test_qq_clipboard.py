import importlib.util
from pathlib import Path
import subprocess
import sys
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('qq_screenshot', ROOT / 'libexec/qq-native-screenshot.py')
qq = importlib.util.module_from_spec(spec)
spec.loader.exec_module(qq)


class ClipboardPublishTests(unittest.TestCase):
    def run_publisher(self, program, timeout=2):
        run = subprocess.run

        def substitute(command, **kwargs):
            self.assertEqual(command, ['/usr/bin/wl-copy', '--type', 'image/png'])
            kwargs['timeout'] = timeout
            return run([sys.executable, '-c', program], **kwargs)

        with mock.patch.object(qq.subprocess, 'run', side_effect=substitute):
            qq.ClipboardBridge.publish(b'\x89PNG\r\n\x1a\nfixture')

    def test_background_owner_stderr_does_not_delay_success(self):
        # Model wl-copy's successful parent and longer-lived clipboard owner.
        # No real clipboard is read or replaced by this test.
        self.run_publisher('''import os, sys, time
data = sys.stdin.buffer.read()
assert data == b'\\x89PNG\\r\\n\\x1a\\nfixture'
if os.fork() == 0:
    time.sleep(0.7)
    os._exit(0)
''', timeout=0.3)

    def test_failure_still_reports_exit_code_and_diagnostics(self):
        with self.assertRaises(subprocess.CalledProcessError) as caught:
            self.run_publisher("import sys; sys.stdin.buffer.read(); sys.stderr.write('clipboard unavailable'); sys.exit(3)")
        self.assertEqual(caught.exception.returncode, 3)
        self.assertEqual(caught.exception.stderr, b'clipboard unavailable')

    def test_stalled_parent_still_times_out(self):
        with self.assertRaises(subprocess.TimeoutExpired):
            self.run_publisher('import sys, time; sys.stdin.buffer.read(); time.sleep(5)', timeout=0.3)


if __name__ == '__main__':
    unittest.main()
