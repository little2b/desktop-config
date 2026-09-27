#!/usr/bin/python3
"""Turn WeChat's blinking tray icon into one desktop notification per episode.

Only tray status and icon alpha values are inspected. No chat files, message
text, tooltip contents, or contacts are read or logged.
"""

import logging
import signal
import time

from gi.repository import Gio, GLib, GLibUnix

TRAY = "org.kde.StatusNotifierItem"
TRAY_PATH = "/StatusNotifierItem"
PROPERTIES = "org.freedesktop.DBus.Properties"
DBUS = "org.freedesktop.DBus"
DBUS_PATH = "/org/freedesktop/DBus"
NOTIFICATIONS = "org.freedesktop.Notifications"
NOTIFICATIONS_PATH = "/org/freedesktop/Notifications"


class BlinkDetector:
    """Recognize visible/transparent alternation, not arbitrary icon changes."""

    QUIET_SECONDS = 4.0
    MAX_EDGE_GAP = 1.5

    def __init__(self):
        self.previous_visible = None
        self.last_edge = None
        self.edges = 0
        self.latched = False
        self.attention = False

    def tick(self, now):
        if (not self.attention and self.last_edge is not None
                and now - self.last_edge > self.QUIET_SECONDS):
            self.latched = False
            self.edges = 0
            self.last_edge = None

    def update(self, now, visible, status):
        if self.attention and status != "NeedsAttention":
            self.latched = False
            self.edges = 0
            self.last_edge = None
        self.attention = status == "NeedsAttention"
        self.tick(now)
        if visible is not None:
            if self.previous_visible is not None and visible != self.previous_visible:
                if self.last_edge is not None and now - self.last_edge <= self.MAX_EDGE_GAP:
                    self.edges += 1
                else:
                    self.edges = 1
                self.last_edge = now
            self.previous_visible = visible
        if not self.latched and (self.attention or self.edges >= 2):
            self.latched = True
            return True
        return False


def icon_visible(pixmaps):
    """The tray's D-Bus pixmaps are ARGB32; inspect alpha only."""
    valid = False
    for width, height, raw in pixmaps:
        if width <= 0 or height <= 0 or len(raw) != width * height * 4:
            continue
        valid = True
        if any(raw[::4]):
            return True
    return False if valid else None


def icon_variant_visible(pixmaps):
    # Avoid unpacking every image byte through GVariant/Python twice a second.
    def images():
        for index in range(pixmaps.n_children()):
            item = pixmaps.get_child_value(index)
            yield (item.get_child_value(0).get_int32(),
                   item.get_child_value(1).get_int32(),
                   item.get_child_value(2).get_data_as_bytes().get_data())
    return icon_visible(images())


class Bridge:
    def __init__(self):
        self.bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        self.loop = GLib.MainLoop()
        self.service = None
        self.owner = None
        self.detector = BlinkDetector()
        self.notification_id = 0
        self.pending = False
        self.next_attempt = 0
        self.next_discovery = 0
        self.bus.signal_subscribe(
            DBUS, DBUS, "NameOwnerChanged", DBUS_PATH, None,
            Gio.DBusSignalFlags.NONE, self.name_changed, None)
        self.bus.signal_subscribe(
            None, TRAY, None, TRAY_PATH, None,
            Gio.DBusSignalFlags.NONE, self.tray_changed, None)
        self.bus.signal_subscribe(
            NOTIFICATIONS, NOTIFICATIONS, None, NOTIFICATIONS_PATH, None,
            Gio.DBusSignalFlags.NONE, self.notification_signal, None)
        GLib.timeout_add_seconds(1, self.tick)
        GLibUnix.signal_add(GLib.PRIORITY_DEFAULT, signal.SIGTERM, self.stop)
        GLibUnix.signal_add(GLib.PRIORITY_DEFAULT, signal.SIGINT, self.stop)

    def call(self, destination, path, interface, method, signature=None, args=()):
        parameters = GLib.Variant(signature, args) if signature else None
        return self.bus.call_sync(destination, path, interface, method, parameters,
                                  None, Gio.DBusCallFlags.NONE, 1500, None).unpack()

    def prop(self, name):
        return self.call(self.service, TRAY_PATH, PROPERTIES, "Get", "(ss)",
                         (TRAY, name))[0]

    def disconnect_tray(self):
        self.service = self.owner = None
        self.detector = BlinkDetector()
        self.pending = False

    def discover(self):
        self.next_discovery = time.monotonic() + 10
        if self.service:
            return False
        try:
            names = self.call(DBUS, DBUS_PATH, DBUS, "ListNames")[0]
            for name in names:
                if not name.startswith("org.kde.StatusNotifierItem-"):
                    continue
                try:
                    identity = self.call(name, TRAY_PATH, PROPERTIES, "Get", "(ss)",
                                         (TRAY, "Id"))[0]
                    if str(identity).lower() != "wechat":
                        continue
                    owner = self.call(DBUS, DBUS_PATH, DBUS, "GetNameOwner", "(s)", (name,))[0]
                except GLib.Error:
                    continue
                self.service, self.owner = name, owner
                self.detector = BlinkDetector()
                logging.info("Connected to WeChat tray")
                self.sample()
                break
        except GLib.Error:
            logging.warning("Tray discovery unavailable; will retry")
        return False

    def name_changed(self, connection, sender, path, iface, member, parameters, data):
        name, old_owner, new_owner = parameters.unpack()
        if name == NOTIFICATIONS:
            self.notification_id = 0
        if name == self.service and new_owner != self.owner:
            self.disconnect_tray()
        if name.startswith("org.kde.StatusNotifierItem-") and new_owner:
            GLib.idle_add(self.discover)

    def tray_changed(self, connection, sender, path, iface, member, parameters, data):
        if sender == self.owner and member in ("NewIcon", "NewStatus", "NewAttentionIcon"):
            self.sample()

    def sample(self):
        try:
            response = self.bus.call_sync(
                self.service, TRAY_PATH, PROPERTIES, "Get",
                GLib.Variant("(ss)", (TRAY, "IconPixmap")), None,
                Gio.DBusCallFlags.NONE, 1500, None)
            visible = icon_variant_visible(response.get_child_value(0).get_variant())
            status = self.prop("Status")
            if self.detector.update(time.monotonic(), visible, status):
                self.pending = True
                self.next_attempt = 0
            self.deliver()
        except GLib.Error:
            self.disconnect_tray()

    def deliver(self):
        now = time.monotonic()
        if not self.pending or now < self.next_attempt:
            return
        if not self.detector.latched:
            self.pending = False
            return
        self.next_attempt = now + 15
        try:
            hints = {"desktop-entry": GLib.Variant("s", "wechat"),
                     "urgency": GLib.Variant("y", 1)}
            self.notification_id = self.call(
                NOTIFICATIONS, NOTIFICATIONS_PATH, NOTIFICATIONS, "Notify",
                "(susssasa{sv}i)",
                ("微信", self.notification_id,
                 "/usr/share/icons/hicolor/256x256/apps/wechat.png",
                 "微信有新消息", "点击打开微信查看。",
                 ["default", "打开微信"], hints, 7000))[0]
            self.pending = False
            logging.info("Posted notification for a new tray attention episode")
        except GLib.Error:
            logging.warning("Desktop notification unavailable; will retry")

    def notification_signal(self, connection, sender, path, iface, member, parameters, data):
        args = parameters.unpack()
        if not args or not self.notification_id or args[0] != self.notification_id:
            return
        if member == "NotificationClosed":
            self.notification_id = 0
        elif member == "ActionInvoked" and args[1] == "default" and self.service:
            try:
                self.call(self.service, TRAY_PATH, TRAY, "Activate", "(ii)", (0, 0))
                logging.info("Activated WeChat from notification")
            except GLib.Error:
                logging.warning("WeChat tray activation unavailable")

    def tick(self):
        now = time.monotonic()
        self.detector.tick(now)
        if not self.service and now >= self.next_discovery:
            self.discover()
        self.deliver()
        return GLib.SOURCE_CONTINUE

    def stop(self):
        self.loop.quit()
        return GLib.SOURCE_REMOVE

    def run(self):
        self.discover()
        self.loop.run()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    Bridge().run()
