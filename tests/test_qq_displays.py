import copy
import importlib.util
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'libexec/qq-native-screenshot.py'
spec = importlib.util.spec_from_file_location('qq_displays', SCRIPT)
qq = importlib.util.module_from_spec(spec)
spec.loader.exec_module(qq)


class DisplayRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.address = str(self.base / 'niri.sock')
        self.env = mock.patch.dict(os.environ, {'NIRI_SOCKET': self.address,
            'XDG_RUNTIME_DIR': str(self.base), 'CLAVIS_CONFIG_HOME': str(self.base / 'config')})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.outputs = {}
        self.geometry = {}
        for index, name in enumerate(['eDP-1', 'DP-2', 'HDMI-A-1']):
            self.geometry[name] = dict(x=index * 1920, y=index * 120, width=1920, height=1080, scale=2)
            self.outputs[name] = dict(name=name, make='Test', model=name, serial=name,
                current_mode=0 if index < 2 else None,
                logical=copy.deepcopy(self.geometry[name]) if index < 2 else None)
        self.workspaces = [dict(id=1, idx=1, output='eDP-1', is_focused=True),
                           dict(id=2, idx=2, output='DP-2', is_focused=False)]
        self.original = copy.deepcopy(self.outputs)
        self.actions = []
        self.fail_off = False
        self.server = socket.socket(socket.AF_UNIX)
        self.server.bind(self.address)
        self.server.listen()
        self.server.settimeout(0.05)
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self.serve, daemon=True)
        self.thread.start()
        self.addCleanup(self.close_server)

    def close_server(self):
        self.stop.set()
        self.thread.join(timeout=1)
        self.server.close()

    def serve(self):
        while not self.stop.is_set():
            try:
                connection, _ = self.server.accept()
            except socket.timeout:
                continue
            with connection:
                request = json.loads(connection.makefile('rb').readline())
                error = None
                if request == 'Outputs':
                    response = {'Outputs': copy.deepcopy(self.outputs)}
                elif request == 'Workspaces':
                    response = {'Workspaces': copy.deepcopy(self.workspaces)}
                else:
                    self.actions.append(request)
                    response = 'Handled'
                    if 'Output' in request:
                        command = request['Output']
                        name, action = command['output'], command['action']
                        if action == 'Off':
                            self.outputs[name].update(current_mode=None, logical=None)
                            for workspace in self.workspaces:
                                if workspace['output'] == name:
                                    workspace['output'] = 'eDP-1'
                            if self.fail_off:
                                error = 'Simulated failure after switching off'
                        elif action == 'On':
                            self.outputs[name].update(current_mode=0, logical=copy.deepcopy(self.geometry[name]))
                        elif 'Position' in action:
                            self.outputs[name]['logical'].update(action['Position']['position']['Specific'])
                    elif 'MoveWorkspaceToMonitor' in request['Action']:
                        action = request['Action']['MoveWorkspaceToMonitor']
                        for workspace in self.workspaces:
                            if workspace['id'] == action['reference']['Id']:
                                workspace['output'] = action['output']
                connection.sendall(json.dumps({'Err': error} if error else {'Ok': response}).encode() + b'\n')

    def test_success_and_cancel_restore_only_originally_active_displays(self):
        for cancel in [False, True]:
            with self.subTest(cancel=cancel), tempfile.TemporaryFile() as lock:
                try:
                    with qq.SingleOutputCapture(lock.fileno()) as capture:
                        self.assertEqual(set(qq.active_outputs(self.outputs)), {'eDP-1'})
                        capture.wait_ready(mock.Mock(monitor_count=lambda: 1))
                        if cancel:
                            raise KeyboardInterrupt
                except KeyboardInterrupt:
                    pass
                self.assertEqual(self.outputs, self.original)
                self.assertEqual(self.workspaces[1]['output'], 'DP-2')
                self.assertFalse(any(a.get('Output', {}).get('output') == 'HDMI-A-1' for a in self.actions))

    def test_uncertain_disable_failure_still_recovers(self):
        self.fail_off = True
        with tempfile.TemporaryFile() as lock:
            with self.assertRaisesRegex(RuntimeError, 'Simulated failure'):
                with qq.SingleOutputCapture(lock.fileno()):
                    self.fail('must not capture after failed setup')
        self.assertEqual(self.outputs, self.original)

    def test_unplugged_or_replaced_monitor_is_not_enabled(self):
        for unplug in [False, True]:
            with self.subTest(unplug=unplug), tempfile.TemporaryFile() as lock:
                self.outputs = copy.deepcopy(self.original)
                self.workspaces[1]['output'] = 'DP-2'
                self.actions = []
                with qq.SingleOutputCapture(lock.fileno()):
                    if unplug:
                        del self.outputs['DP-2']
                    else:
                        self.outputs['DP-2']['serial'] = 'replacement'
                self.assertFalse(any(a.get('Output', {}).get('action') == 'On' for a in self.actions))

    def test_already_single_display_does_not_toggle_outputs(self):
        self.outputs['DP-2'].update(current_mode=None, logical=None)
        with tempfile.TemporaryFile() as lock:
            with qq.SingleOutputCapture(lock.fileno()):
                pass
        self.assertEqual(self.actions, [])

    def test_guard_restores_after_parent_is_killed(self):
        program = '''import importlib.util,sys,tempfile,time
spec=importlib.util.spec_from_file_location('qq',sys.argv[1])
qq=importlib.util.module_from_spec(spec);spec.loader.exec_module(qq)
lock=tempfile.TemporaryFile()
capture=qq.SingleOutputCapture(lock.fileno());capture.__enter__()
print('ready',flush=True)
time.sleep(30)
'''
        parent = subprocess.Popen([sys.executable, '-c', program, str(SCRIPT)],
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            self.assertEqual(parent.stdout.readline().strip(), 'ready')
            self.assertIsNone(self.outputs['DP-2']['current_mode'])
            parent.kill()
            parent.communicate(timeout=3)
            deadline = time.monotonic() + 4
            while time.monotonic() < deadline and (self.outputs != self.original or self.workspaces[1]['output'] != 'DP-2'):
                time.sleep(0.05)
            self.assertEqual(self.outputs, self.original)
            self.assertEqual(self.workspaces[1]['output'], 'DP-2')
        finally:
            if parent.poll() is None:
                parent.kill()
                parent.communicate(timeout=3)


if __name__ == '__main__':
    unittest.main()
