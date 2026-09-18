#!/usr/bin/python
"""User-invoked Niri binding for QQ's native Ctrl+Alt+A screenshot action.

Deliver the accelerator to QQ's X server without focusing its chat window.
Only a newly opened, untitled QQ capture overlay may be moved afterwards.
"""
import ctypes as C
import fcntl
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
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
        subprocess.run(['/usr/bin/wl-copy', '--type', 'image/png'], input=data,
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=True, timeout=5)

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


def main():
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
        workspaces = niri('Workspaces')['Workspaces']
        workspace = next(w for w in workspaces if w['is_focused'])
        old_ids = {w['id'] for w in niri('Windows')['Windows']}
        x = X11(display)
        clipboard = None
        try:
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
        main()
    except (OSError, RuntimeError, KeyError, StopIteration) as error:
        print(str(error), file=sys.stderr)
        subprocess.run(['notify-send', '--app-name=QQ', 'QQ 截图提示', str(error)], check=False)
        raise SystemExit(1)
