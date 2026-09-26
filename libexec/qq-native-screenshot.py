#!/usr/bin/python
"""User-invoked Niri binding for QQ's native Ctrl+Alt+A screenshot action.

Deliver the accelerator to QQ's X server without focusing its chat window.
Use only the focused output during capture, then restore displays/workspaces.
Only a newly opened, untitled QQ capture overlay is relocated for the capture.
"""
import ctypes as C
import fcntl
import hashlib
import json
import os
from pathlib import Path
import socket
import select
import signal
import subprocess
import sys
import tempfile
import time


def qq_display():
    for proc in Path('/proc').iterdir():
        if not proc.name.isdecimal():
            continue
        try:
            if proc.stat().st_uid != os.getuid() or os.readlink(proc / 'exe') != '/opt/QQ/qq':
                continue
            args = (proc / 'cmdline').read_bytes().split(b'\0')
            if any(arg.startswith(b'--type=') for arg in args):
                continue
            for entry in (proc / 'environ').read_bytes().split(b'\0'):
                if entry.startswith(b'DISPLAY='):
                    value = entry.partition(b'=')[2].decode()
                    if value.startswith(':'):
                        return value
        except (OSError, UnicodeError):
            continue
    raise RuntimeError('请先启动并登录 QQ。')


class X11:
    def __init__(self, display):
        self.x = C.CDLL('libX11.so.6')
        self.xt = C.CDLL('libXtst.so.6')
        p, u = C.c_void_p, C.c_ulong
        for name, args, result in [
            ('XOpenDisplay', [C.c_char_p], p),
            ('XDefaultRootWindow', [p], u),
            ('XGetInputFocus', [p, C.POINTER(u), C.POINTER(C.c_int)], C.c_int),
            ('XSetInputFocus', [p, u, C.c_int, u], C.c_int),
            ('XStringToKeysym', [C.c_char_p], u),
            ('XKeysymToKeycode', [p, u], C.c_ubyte),
            ('XQueryKeymap', [p, C.POINTER(C.c_ubyte)], C.c_int),
            ('XSync', [p, C.c_int], C.c_int),
            ('XCloseDisplay', [p], C.c_int),
        ]:
            fn = getattr(self.x, name)
            fn.argtypes, fn.restype = args, result
        self.xt.XTestFakeKeyEvent.argtypes = [p, C.c_uint, C.c_int, u]
        self.xt.XTestFakeKeyEvent.restype = C.c_int
        self.d = self.x.XOpenDisplay(display.encode())
        if not self.d:
            raise RuntimeError('无法连接 QQ 的 XWayland 显示服务。')

    def focus(self):
        window, revert = C.c_ulong(), C.c_int()
        self.x.XGetInputFocus(self.d, C.byref(window), C.byref(revert))
        return window.value, revert.value

    def monitor_count(self):
        class ScreenInfo(C.Structure):
            _fields_ = [('number', C.c_int), ('x', C.c_short), ('y', C.c_short),
                        ('width', C.c_short), ('height', C.c_short)]
        library = C.CDLL('libXinerama.so.1')
        library.XineramaQueryScreens.argtypes = [C.c_void_p, C.POINTER(C.c_int)]
        library.XineramaQueryScreens.restype = C.POINTER(ScreenInfo)
        self.x.XFree.argtypes = [C.c_void_p]
        count = C.c_int()
        screens = library.XineramaQueryScreens(self.d, C.byref(count))
        try:
            return count.value
        finally:
            if screens:
                self.x.XFree(screens)

    def screenshot(self):
        root = self.x.XDefaultRootWindow(self.d)
        original_focus, original_revert = self.focus()
        held = (C.c_ubyte * 32)()
        self.x.XQueryKeymap(self.d, held)
        codes = [self.x.XKeysymToKeycode(self.d, self.x.XStringToKeysym(key))
                 for key in (b'Control_L', b'Alt_L', b'a')]
        if not all(codes):
            raise RuntimeError('无法解析 QQ 截图快捷键。')
        if held[codes[2] // 8] & (1 << (codes[2] % 8)):
            raise RuntimeError('请松开截图快捷键后重试。')
        pressed = []
        try:
            # Root focus allows the X11 passive global grab to activate even
            # while Niri is focused on an unrelated native Wayland client.
            self.x.XSetInputFocus(self.d, root, 0, 0)
            for code in codes:
                if not held[code // 8] & (1 << (code % 8)):
                    self.xt.XTestFakeKeyEvent(self.d, code, 1, 0)
                    pressed.append(code)
            self.x.XSync(self.d, 0)
        finally:
            for code in reversed(pressed):
                self.xt.XTestFakeKeyEvent(self.d, code, 0, 0)
            self.x.XSync(self.d, 0)
            if self.focus()[0] == root:
                self.x.XSetInputFocus(self.d, original_focus, original_revert, 0)
                self.x.XSync(self.d, 0)

    def close(self):
        self.x.XCloseDisplay(self.d)


class ClipboardBridge:
    """Observe only this capture's new QQ-owned PNG selection, in memory."""
    class ClientSpec(C.Structure):
        _fields_ = [('client', C.c_ulong), ('mask', C.c_uint)]

    class ClientValue(C.Structure):
        pass

    ClientValue._fields_ = [('spec', ClientSpec), ('length', C.c_long), ('value', C.c_void_p)]

    def __init__(self, display, x11, publisher=None, owner_allowed=None):
        os.environ['GDK_BACKEND'] = 'x11'
        os.environ['DISPLAY'] = display
        import gi
        gi.require_version('Gtk', '3.0')
        gi.require_version('Gdk', '3.0')
        from gi.repository import Gtk, Gdk, GLib
        Gdk.set_allowed_backends('x11')
        self.GLib = GLib
        self.display = Gdk.Display.open(display)
        if self.display is None:
            raise RuntimeError('无法连接 QQ 的图片剪贴板。')
        self.x11 = x11
        self.clipboard = Gtk.Clipboard.get_for_display(self.display, Gdk.SELECTION_CLIPBOARD)
        self.png = Gdk.Atom.intern('image/png', False)
        self.copied = False
        self.error = None
        self.armed = False
        self.generation = 0
        self.publisher = publisher or self.publish
        self.owner_allowed = owner_allowed or self.is_qq
        self.res = C.CDLL('libXRes.so.1')
        self.res.XResQueryClientIds.argtypes = [C.c_void_p, C.c_long, C.POINTER(self.ClientSpec),
            C.POINTER(C.c_long), C.POINTER(C.POINTER(self.ClientValue))]
        self.res.XResGetClientPid.argtypes = [C.POINTER(self.ClientValue)]
        self.res.XResGetClientPid.restype = C.c_int
        self.res.XResClientIdsDestroy.argtypes = [C.c_long, C.POINTER(self.ClientValue)]
        x11.x.XInternAtom.argtypes = [C.c_void_p, C.c_char_p, C.c_int]
        x11.x.XInternAtom.restype = C.c_ulong
        x11.x.XGetSelectionOwner.argtypes = [C.c_void_p, C.c_ulong]
        x11.x.XGetSelectionOwner.restype = C.c_ulong
        self.selection = x11.x.XInternAtom(x11.d, b'CLIPBOARD', 0)
        self.handler = self.clipboard.connect('owner-change', self.changed)

    def owner(self):
        return self.x11.x.XGetSelectionOwner(self.x11.d, self.selection)

    def owner_pid(self, owner):
        values = C.POINTER(self.ClientValue)()
        count = C.c_long()
        spec = self.ClientSpec(owner, 2)
        self.res.XResQueryClientIds(self.x11.d, 1, C.byref(spec), C.byref(count), C.byref(values))
        try:
            for index in range(count.value):
                pid = self.res.XResGetClientPid(C.byref(values[index]))
                if pid > 0:
                    return pid
        finally:
            if values:
                self.res.XResClientIdsDestroy(count, values)
        return None

    @staticmethod
    def is_qq(pid):
        try:
            proc = Path('/proc') / str(pid)
            return proc.stat().st_uid == os.getuid() and os.readlink(proc / 'exe') == '/opt/QQ/qq'
        except OSError:
            return False

    def arm(self):
        # Drain initial owner notifications before the capture begins, so an
        # older screenshot cannot be mistaken for the result of this capture.
        self.display.sync()
        self.pump()
        self.armed = True

    def pump(self):
        context = self.GLib.MainContext.default()
        while context.pending():
            context.iteration(False)

    def changed(self, clipboard, event):
        self.generation += 1
        if not self.armed or self.copied:
            return
        owner = self.owner()
        pid = self.owner_pid(owner) if owner else None
        if pid and self.owner_allowed(pid):
            clipboard.request_contents(self.png, self.received, (self.generation, owner))

    def received(self, clipboard, selection, request):
        generation, owner = request
        if not self.armed or self.copied or generation != self.generation or owner != self.owner():
            return
        length = selection.get_length()
        if not 8 < length <= 128 * 1024 * 1024:
            return
        data = selection.get_data()
        if data and data.startswith(b'\x89PNG\r\n\x1a\n'):
            try:
                self.publisher(bytes(data))
            except (OSError, subprocess.SubprocessError) as error:
                self.error = '截图完成，但同步系统剪贴板失败：' + str(error)
                return
            self.copied = True
            print('QQ screenshot copied to Wayland clipboard', flush=True)

    @staticmethod
    def publish(data):
        # wl-copy forks a clipboard owner which can inherit stderr. A PIPE
        # makes communicate() wait for that owner's EOF even after the parent
        # has successfully published the image and exited.
        with tempfile.TemporaryFile() as errors:
            try:
                subprocess.run(['/usr/bin/wl-copy', '--type', 'image/png'], input=data,
                    stdout=subprocess.DEVNULL, stderr=errors, check=True, timeout=5)
            except subprocess.CalledProcessError as error:
                errors.seek(0)
                error.stderr = errors.read()
                raise

    def close(self):
        self.armed = False
        self.clipboard.disconnect(self.handler)
        # Gtk owns per-display clipboard objects. Leave display teardown to
        # GTK/process exit, after pending selection callbacks and wrappers die.
        self.clipboard = None


def niri(request):
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.settimeout(3)
        connection.connect(os.environ['NIRI_SOCKET'])
        connection.sendall(json.dumps(request).encode() + b'\n')
        with connection.makefile('r') as response:
            result = json.loads(response.readline())
    if 'Err' in result:
        raise RuntimeError(str(result['Err']))
    return result['Ok']


def active_outputs(outputs):
    return {name: output for name, output in outputs.items()
            if output.get('current_mode') is not None and output.get('logical')}


def same_output(before, after):
    return after and all(before.get(key) == after.get(key) for key in ('make', 'model', 'serial'))


def output_action(name, action):
    niri({'Output': {'output': name, 'action': action}})


def wait_outputs(names, timeout=8):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        outputs = niri('Outputs')['Outputs']
        if names.issubset(active_outputs(outputs)):
            return outputs
        time.sleep(0.1)
    raise RuntimeError('显示器未能及时恢复。请在显示器设置中检查。')


def restore_displays(snapshot):
    errors = []
    outputs = niri('Outputs')['Outputs']
    restore_names = set()
    for name in snapshot['disabled']:
        saved = snapshot['outputs'][name]
        if not same_output(saved, outputs.get(name)):
            continue  # Unplugged or replaced displays must not be reconfigured.
        try:
            if name not in active_outputs(outputs):
                output_action(name, 'On')
            restore_names.add(name)
        except (OSError, RuntimeError) as error:
            errors.append(str(error))
    try:
        outputs = wait_outputs(restore_names)
    except (OSError, RuntimeError) as error:
        errors.append(str(error))
        outputs = niri('Outputs')['Outputs']
    available = active_outputs(outputs)
    for name, saved in snapshot['outputs'].items():
        if name not in available or not same_output(saved, available[name]):
            continue
        position = {key: saved['logical'][key] for key in ('x', 'y')}
        current = {key: available[name]['logical'][key] for key in ('x', 'y')}
        if current != position:
            try:
                output_action(name, {'Position': {'position': {'Specific': position}}})
            except (OSError, RuntimeError) as error:
                errors.append(str(error))
    current = {w['id']: w for w in niri('Workspaces')['Workspaces']}
    for workspace in sorted(snapshot['workspaces'], key=lambda w: w['idx']):
        name = workspace['output']
        if name not in restore_names or name not in available or workspace['id'] not in current:
            continue
        if current[workspace['id']]['output'] != name:
            try:
                niri({'Action': {'MoveWorkspaceToMonitor': {
                    'output': name, 'reference': {'Id': workspace['id']}}}})
            except (OSError, RuntimeError) as error:
                errors.append(str(error))
    focused = snapshot['focused']
    if focused in current:
        try:
            niri({'Action': {'FocusWorkspace': {'reference': {'Id': focused}}}})
        except (OSError, RuntimeError) as error:
            errors.append(str(error))
    if errors:
        raise RuntimeError('恢复显示器时出现错误：' + '; '.join(errors))


def recovery_guard(snapshot):
    # EOF means completion or parent death. The deadline also covers a hung
    # capture process. Inherited locks prevent competing captures/migrations.
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    select.select([sys.stdin], [], [], 210)
    try:
        restore_displays(snapshot)
        result = {'ok': True}
    except (OSError, RuntimeError, KeyError) as error:
        result = {'ok': False, 'error': str(error)}
        subprocess.run(['notify-send', '--app-name=QQ', 'QQ 显示器恢复提示', str(error)], check=False)
    try:
        print(json.dumps(result, ensure_ascii=False), flush=True)
    except BrokenPipeError:
        pass  # The parent may have died; restoration still succeeded.


class SingleOutputCapture:
    def __init__(self, capture_lock):
        self.capture_lock = capture_lock
        self.migration_lock = None
        self.guard = None
        self.snapshot = None

    def __enter__(self):
        # Clavis's existing cross-process lock keeps its preferred-display
        # watcher from interpreting this temporary disconnect as a hotplug.
        config = Path(os.environ.get('CLAVIS_CONFIG_HOME', Path.home() / '.config/clavis')) / 'primary-display.json'
        key = hashlib.sha256((str(config) + os.environ['NIRI_SOCKET']).encode()).hexdigest()[:20]
        path = Path(os.environ['XDG_RUNTIME_DIR']) / ('clavis-primary-' + key + '.lock')
        self.migration_lock = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            try:
                fcntl.flock(self.migration_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise RuntimeError('正在调整主显示器，请稍后重试截图。') from error
            outputs = active_outputs(niri('Outputs')['Outputs'])
            workspaces = niri('Workspaces')['Workspaces']
            workspace = next(w for w in workspaces if w['is_focused'])
            target = workspace['output']
            if target not in outputs:
                raise RuntimeError('当前屏幕不可用，请稍后重试截图。')
            self.workspace = workspace
            disabled = [name for name in outputs if name != target]
            self.snapshot = {
                'outputs': {name: {key: value.get(key) for key in ('make', 'model', 'serial', 'logical')}
                            for name, value in outputs.items()},
                'disabled': disabled,
                'workspaces': [{key: value[key] for key in ('id', 'idx', 'output')} for value in workspaces],
                'focused': workspace['id'],
            }
            if disabled:
                self.guard = subprocess.Popen([sys.executable, str(Path(__file__).resolve()),
                    '--restore-displays', json.dumps(self.snapshot)], stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, start_new_session=True,
                    pass_fds=(self.capture_lock, self.migration_lock))
                for name in disabled:
                    output_action(name, 'Off')
            else:
                os.close(self.migration_lock)
                self.migration_lock = None
            return self
        except BaseException:
            self.__exit__(*sys.exc_info())
            raise

    def wait_ready(self, x11):
        if not self.snapshot['disabled']:
            return
        deadline = time.monotonic() + 8
        stable = None
        while time.monotonic() < deadline:
            active = active_outputs(niri('Outputs')['Outputs'])
            if set(active) == {self.workspace['output']} and x11.monitor_count() == 1:
                if stable is None:
                    stable = time.monotonic()
                if time.monotonic() - stable >= 0.6:
                    niri({'Action': {'FocusWorkspace': {'reference': {'Id': self.workspace['id']}}}})
                    return
            else:
                stable = None
            time.sleep(0.1)
        raise RuntimeError('QQ 的单屏截图环境未能准备完成，已请求恢复显示器。')

    def __exit__(self, *exception):
        try:
            if self.guard:
                try:
                    output, _ = self.guard.communicate(timeout=35)
                    result = json.loads(output)
                except (subprocess.SubprocessError, ValueError) as error:
                    raise RuntimeError('未收到显示器恢复确认，请在显示器设置中检查。') from error
                if not result.get('ok'):
                    raise RuntimeError(result.get('error', '未能恢复显示器。'))
        finally:
            if self.migration_lock is not None:
                os.close(self.migration_lock)
                self.migration_lock = None


def main():
    if len(sys.argv) == 3 and sys.argv[1] == '--restore-displays':
        recovery_guard(json.loads(sys.argv[2]))
        return
    display = qq_display()
    if sys.argv[1:] == ['--check']:
        x = X11(display)
        x.close()
        print('QQ XWayland display available: ' + display)
        return
    if len(sys.argv) != 1:
        raise RuntimeError('Usage: qq-native-screenshot.py [--check]')
    lock_path = Path(os.environ['XDG_RUNTIME_DIR']) / 'qq-native-screenshot.lock'
    with lock_path.open('w') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        with SingleOutputCapture(lock.fileno()) as capture:
            take_screenshot(display, capture)


def take_screenshot(display, capture):
    workspace = capture.workspace
    old_ids = {w['id'] for w in niri('Windows')['Windows']}
    x = X11(display)
    clipboard = None
    try:
        capture.wait_ready(x)
        clipboard = ClipboardBridge(display, x)
        clipboard.arm()
        x.screenshot()
        deadline = time.monotonic() + 4
        overlay = None
        while time.monotonic() < deadline:
            clipboard.pump()
            for window in niri('Windows')['Windows']:
                if window['id'] not in old_ids and window['app_id'] == 'QQ' and not window['title']:
                    overlay = window['id']
                    if window['workspace_id'] != workspace['id']:
                        niri({'Action': {'MoveWindowToWorkspace': {
                            'window_id': overlay, 'reference': {'Id': workspace['id']}, 'focus': True}}})
                        niri({'Action': {'FocusWindow': {'id': overlay}}})
                    break
            if overlay is not None:
                break
            time.sleep(0.08)
        if overlay is None:
            raise RuntimeError('QQ 未弹出截图界面。请确认 QQ 内的截图快捷键为 Ctrl+Alt+A。')
        # Keep the observer only for this capture. Cancellation does not
        # publish anything, and transfers from other applications are ignored.
        deadline = time.monotonic() + 180
        closed_at = None
        while time.monotonic() < deadline:
            clipboard.pump()
            if clipboard.error:
                raise RuntimeError(clipboard.error)
            if clipboard.copied:
                return
            if not any(w['id'] == overlay for w in niri('Windows')['Windows']):
                closed_at = closed_at or time.monotonic()
                if time.monotonic() - closed_at > 3:
                    return
            time.sleep(0.08)
    finally:
        if clipboard:
            clipboard.close()
        x.close()


if __name__ == '__main__':
    try:
        if '--restore-displays' not in sys.argv:
            def interrupted(signum, frame):
                raise KeyboardInterrupt
            signal.signal(signal.SIGTERM, interrupted)
        main()
    except KeyboardInterrupt:
        raise SystemExit(130)
    except (OSError, RuntimeError, KeyError, StopIteration) as error:
        print(str(error), file=sys.stderr)
        subprocess.run(['notify-send', '--app-name=QQ', 'QQ 截图提示', str(error)], check=False)
        raise SystemExit(1)
