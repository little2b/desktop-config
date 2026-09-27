"""Exercise the actual daemon protocol with an isolated, offscreen session."""
import json
import os
from pathlib import Path
import select
import subprocess
import sys
import tempfile
import time
import unittest

BINARY = sys.argv.pop(1)


class IpcTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='launchpad-ipc-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        for name in ['runtime', 'config/clavis', 'cache', 'share/applications']:
            (self.root / name).mkdir(parents=True, mode=0o700)
        self.apps = self.root / 'share/applications'
        self.write_app('one')
        self.env = os.environ | {
            'QT_QPA_PLATFORM': 'offscreen', 'QT_QUICK_BACKEND': 'software',
            'XDG_RUNTIME_DIR': str(self.root / 'runtime'),
            'XDG_CONFIG_HOME': str(self.root / 'config'),
            'CLAVIS_CONFIG_HOME': str(self.root / 'config/clavis'),
            'XDG_CACHE_HOME': str(self.root / 'cache'),
            'XDG_DATA_HOME': str(self.root / 'share'),
            'XDG_DATA_DIRS': str(self.root / 'share'),
            'XDG_CURRENT_DESKTOP': 'niri',
        }
        self.log = (self.root / 'daemon.log').open('w+')
        self.addCleanup(self.log.close)
        self.server = subprocess.Popen([BINARY, '--background'], env=self.env, stdout=self.log, stderr=self.log)
        self.addCleanup(self.stop, self.server)
        self.until(lambda state: state['ready'] and state['entries'] == 1)

    @staticmethod
    def stop(process):
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=5)

    def write_app(self, name):
        (self.apps / f'{name}.desktop').write_text(
            f'[Desktop Entry]\nType=Application\nName={name}\nExec=/bin/true\nIcon=application-x-executable\n')

    def command(self, action):
        result = subprocess.run([BINARY, '--' + action], env=self.env, capture_output=True, text=True, timeout=5)
        if result.returncode:
            raise RuntimeError(result.stderr)
        return json.loads(result.stdout)

    def until(self, predicate):
        deadline = time.monotonic() + 5
        latest = None
        while time.monotonic() < deadline:
            try:
                latest = self.command('status')
                if predicate(latest):
                    return latest
            except (RuntimeError, json.JSONDecodeError):
                if self.server.poll() is not None:
                    break
            time.sleep(0.03)
        self.log.flush()
        self.fail(f'Unexpected daemon state {latest}: {(self.root / "daemon.log").read_text()}')

    def test_background_preparation_and_visibility_subscription(self):
        self.assertFalse(self.command('status')['visible'])
        watch = subprocess.Popen([BINARY, '--watch'], env=self.env, stdout=subprocess.PIPE)
        self.addCleanup(self.stop, watch)
        self.addCleanup(watch.stdout.close)
        self.assertTrue(select.select([watch.stdout], [], [], 3)[0])
        self.assertFalse(json.loads(watch.stdout.readline())['visible'])
        self.command('show')
        self.until(lambda state: state['phase'] == 'open')
        self.command('hide')
        self.until(lambda state: not state['visible'])
        events = []
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            if not select.select([watch.stdout], [], [], 0.2)[0]:
                continue
            event = json.loads(watch.stdout.readline())
            events.append(event)
            if not event['visible']:
                break
        self.assertTrue(any(event['visible'] for event in events))
        self.assertFalse(events[-1]['visible'])
        self.command('show')
        self.command('hide')
        self.command('show')
        self.until(lambda state: state['phase'] == 'open')
        self.command('hide')
        self.until(lambda state: not state['visible'])

    def test_app_install_and_removal_refresh_without_restart(self):
        self.write_app('two')
        self.until(lambda state: state['entries'] == 2)
        (self.apps / 'two.desktop').unlink()
        self.until(lambda state: state['entries'] == 1)


if __name__ == '__main__':
    unittest.main()
