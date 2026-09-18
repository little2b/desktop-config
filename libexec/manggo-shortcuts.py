#!/usr/bin/python
"""Niri key bindings -> the GlobalShortcuts portal, scoped to Manggo.

The compositor owns the four key combinations; this backend never captures
input or edits configuration. Other apps/keys require a separate user decision.
"""
import os
import sys
import time
from gi.repository import Gio, GLib

NAME = "org.freedesktop.impl.portal.desktop.manggo"
PATH = "/org/freedesktop/portal/desktop"
IFACE = "org.freedesktop.impl.portal.GlobalShortcuts"
CONTROL = "local.ManggoShortcuts"
APP_ID = "com.pylogmon.Manggo"
KEYS = {
    "selection-translation": "Alt+D",
    "input-translation": "Alt+G",
    "screenshot-recognition": "Alt+X",
    "screenshot-translation": "Alt+T",
}

XML = """<node>
<interface name="org.freedesktop.impl.portal.GlobalShortcuts">
 <method name="CreateSession"><arg type="o" direction="in"/><arg type="o" direction="in"/><arg type="s" direction="in"/><arg type="a{sv}" direction="in"/><arg type="u" direction="out"/><arg type="a{sv}" direction="out"/></method>
 <method name="BindShortcuts"><arg type="o" direction="in"/><arg type="o" direction="in"/><arg type="a(sa{sv})" direction="in"/><arg type="s" direction="in"/><arg type="a{sv}" direction="in"/><arg type="u" direction="out"/><arg type="a{sv}" direction="out"/></method>
 <method name="ListShortcuts"><arg type="o" direction="in"/><arg type="o" direction="in"/><arg type="u" direction="out"/><arg type="a{sv}" direction="out"/></method>
 <signal name="Activated"><arg type="o"/><arg type="s"/><arg type="t"/><arg type="a{sv}"/></signal>
 <signal name="Deactivated"><arg type="o"/><arg type="s"/><arg type="t"/><arg type="a{sv}"/></signal>
 <signal name="ShortcutsChanged"><arg type="o"/><arg type="a(sa{sv})"/></signal>
 <property name="version" type="u" access="read"/>
</interface>
<interface name="local.ManggoShortcuts">
 <method name="Trigger"><arg type="s" direction="in"/><arg type="s" direction="in"/><arg type="u" direction="out"/></method>
 <method name="ListBindings"><arg type="a(oss)" direction="out"/></method>
</interface>
</node>"""
SESSION_XML = """<node><interface name="org.freedesktop.impl.portal.Session">
 <method name="Close"/><signal name="Closed"/>
 <property name="version" type="u" access="read"/>
</interface></node>"""


def normalized(key):
    return key.replace("<", "").replace(">", "+").replace(" ", "").lower()


class Backend:
    def __init__(self, connection):
        self.bus = connection
        self.sessions = {}
        self.pending_releases = {}
        self.session_interface = Gio.DBusNodeInfo.new_for_xml(SESSION_XML).interfaces[0]
        self.node = Gio.DBusNodeInfo.new_for_xml(XML)
        for interface in self.node.interfaces:
            self.bus.register_object(PATH, interface, self.dispatch, self.get_property, None)
        self.bus.signal_subscribe(
            "org.freedesktop.DBus", "org.freedesktop.DBus", "NameOwnerChanged",
            "/org/freedesktop/DBus", None, Gio.DBusSignalFlags.NONE,
            self.owner_changed, None,
        )

    def get_property(self, connection, sender, path, interface, name):
        return GLib.Variant("u", 1) if name == "version" else None

    def bus_pid(self, name):
        return self.bus.call_sync(
            "org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus",
            "GetConnectionUnixProcessID", GLib.Variant("(s)", (name,)),
            GLib.VariantType.new("(u)"), Gio.DBusCallFlags.NONE, 2000, None,
        ).unpack()[0]

    def from_portal(self, sender):
        # Portal implementations may be called through a second bus connection
        # belonging to the same portal process, not the public name's connection.
        try:
            return self.bus_pid(sender) == self.bus_pid("org.freedesktop.portal.Desktop")
        except GLib.Error:
            return False

    def close(self, path):
        for key, source in list(self.pending_releases.items()):
            if key[0] == path:
                GLib.source_remove(source)
                self.pending_releases.pop(key)
        session = self.sessions.pop(path, None)
        if session:
            self.bus.unregister_object(session["registration"])
            print("Closed Manggo shortcut session", flush=True)

    def release(self, session_path, action):
        self.pending_releases.pop((session_path, action), None)
        if session_path in self.sessions and action in self.sessions[session_path]["bindings"]:
            self.bus.emit_signal(None, PATH, IFACE, "Deactivated", GLib.Variant(
                "(osta{sv})", (session_path, action, time.monotonic_ns() // 1_000_000, {})))
        return GLib.SOURCE_REMOVE

    def owner_changed(self, connection, sender, path, interface, signal, params, user_data):
        name, old, new = params.unpack()
        if old and not new:
            for session_path, session in list(self.sessions.items()):
                if name == session["owner"] or name == "org.freedesktop.portal.Desktop":
                    self.close(session_path)

    def results(self, path):
        return {"shortcuts": GLib.Variant("a(sa{sv})", [
            (action, {"description": GLib.Variant("s", description),
                      "trigger_description": GLib.Variant("s", KEYS[action])})
            for action, description in self.sessions[path]["bindings"].items()
        ])}

    def dispatch(self, connection, sender, path, interface, method, params, invocation):
        try:
            if interface == CONTROL:
                if method == "ListBindings":
                    rows = [(p, a, KEYS[a]) for p, s in self.sessions.items() for a in s["bindings"]]
                    invocation.return_value(GLib.Variant("(a(oss))", (rows,)))
                    return
                action, token = params.unpack()
                if action not in KEYS:
                    raise ValueError("Action is not configured")
                # Only the newest binding gets the event during app re-registration.
                matches = [(p, s) for p, s in self.sessions.items() if action in s["bindings"]]
                if matches:
                    session_path, _ = matches[-1]
                    key = (session_path, action)
                    if key in self.pending_releases:
                        GLib.source_remove(self.pending_releases[key])
                        self.release(session_path, action)
                    options = {"activation_token": GLib.Variant("s", token)} if token else {}
                    self.bus.emit_signal(None, PATH, IFACE, "Activated", GLib.Variant(
                        "(osta{sv})", (session_path, action, time.monotonic_ns() // 1_000_000, options)))
                    # Niri spawn bindings deliver discrete commands, not key-up
                    # notifications. Complete each command as a bounded stroke.
                    # Manggo defers selection/screenshot actions until release.
                    self.pending_releases[key] = GLib.timeout_add(150, self.release, session_path, action)
                    print(f"Triggered {action}", flush=True)
                invocation.return_value(GLib.Variant("(u)", (int(bool(matches)),)))
                return

            if not self.from_portal(sender):
                invocation.return_dbus_error("org.freedesktop.DBus.Error.AccessDenied", "Only the desktop portal may register sessions")
                return
            if interface == "org.freedesktop.impl.portal.Session":
                self.close(path)
                invocation.return_value(GLib.Variant("()", ()))
                return
            args = params.unpack()
            session_path = args[1]
            if method == "CreateSession":
                if args[2] != APP_ID or session_path in self.sessions:
                    print(f"Rejected session for app {args[2]!r}", flush=True)
                    invocation.return_value(GLib.Variant("(ua{sv})", (2, {})))
                    return
                registration = self.bus.register_object(session_path, self.session_interface, self.dispatch, self.get_property, None)
                self.sessions[session_path] = {"owner": sender, "registration": registration, "bindings": {}}
                print("Created Manggo shortcut session", flush=True)
                invocation.return_value(GLib.Variant("(ua{sv})", (0, {})))
                return
            if session_path not in self.sessions or self.sessions[session_path]["owner"] != sender:
                raise ValueError("Unknown shortcut session")
            if method == "BindShortcuts":
                bindings = {}
                for action, properties in args[2]:
                    trigger = properties.get("preferred_trigger", "")
                    if action not in KEYS or normalized(trigger) != normalized(KEYS[action]):
                        print(f"Rejected unconfigured binding: {action!r} {trigger!r}", flush=True)
                        invocation.return_value(GLib.Variant("(ua{sv})", (2, {})))
                        return
                    bindings[action] = properties.get("description", action)
                self.sessions[session_path]["bindings"] = bindings
                print("Bound: " + ", ".join(f"{KEYS[a]}={a}" for a in bindings), flush=True)
            invocation.return_value(GLib.Variant("(ua{sv})", (0, self.results(session_path))))
        except (GLib.Error, ValueError, TypeError) as error:
            invocation.return_dbus_error("org.freedesktop.DBus.Error.Failed", str(error))


def main():
    bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    if len(sys.argv) == 3 and sys.argv[1] == "--trigger":
        reply = bus.call_sync(NAME, PATH, CONTROL, "Trigger", GLib.Variant(
            "(ss)", (sys.argv[2], os.environ.get("XDG_ACTIVATION_TOKEN", ""))),
            GLib.VariantType.new("(u)"), Gio.DBusCallFlags.NONE, 3000, None)
        if reply.unpack()[0] == 0:
            print("Manggo has no active binding; open Manggo first.", file=sys.stderr)
            return 1
        return 0
    if len(sys.argv) != 1:
        raise SystemExit("Usage: manggo-shortcuts.py [--trigger ACTION]")
    backend = Backend(bus)
    owner = Gio.bus_own_name_on_connection(bus, NAME, Gio.BusNameOwnerFlags.NONE, None, None)
    loop = GLib.MainLoop()
    try:
        loop.run()
    finally:
        for path in list(backend.sessions):
            backend.close(path)
        Gio.bus_unown_name(owner)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
