//@ pragma UseQApplication
import QtQuick
import Quickshell
import Quickshell.Io
import Quickshell.Wayland

ShellRoot {
    id: root
    property var windows: []
    property var workspaces: []
    property var appIds: []
    property int desktopEntriesRevision: 0
    property bool preview: false
    property var iconFallbacks: ({})
    DockTheme { id: theme }
    readonly property var menuTheme: theme
    FileView {
        path: Qt.resolvedUrl("icon-fallbacks.json")
        preload: true
        onLoaded: {
            try { root.iconFallbacks = JSON.parse(text()); }
            catch (e) { console.warn("Cannot load icon fallbacks:", e); }
        }
    }
    Launchpad { id: launchpad; controller: root }
    DockMenu { id: contextMenu; controller: root; theme: root.menuTheme }

    function openLauncher(output) {
        contextMenu.dismiss();
        launchpad.screen = output;
        launchpad.opened = true;
    }
    function movePinned(id, direction) {
        const ids = settings.pinned.map(root.canonical);
        const index = ids.indexOf(id), target = index + direction;
        if (index < 0 || target < 0 || target >= ids.length) return;
        const other = ids[target]; ids[target] = ids[index]; ids[index] = other;
        root.configure(JSON.stringify({pinned: ids}));
    }

    FileView {
        id: configFile
        path: Qt.resolvedUrl("settings.json")
        preload: true
        blockLoading: true
        watchChanges: true
        onFileChanged: reload()
        JsonAdapter {
            id: settings
            property var pinned: ["google-chrome", "org.kde.dolphin", "org.kde.konsole", "chatgpt"]
            property bool autoHide: false
            property bool smartAutoHide: true
            property int iconSize: 44
            property bool enabled: true
            property string output: ""
            property bool showRunning: true
            property int spacing: 8
            property int bottomMargin: 10
            property int backgroundOpacity: 93
            property int cornerRadius: 20
            property int hideDelay: 650
            property bool hoverZoom: true
            property bool showTooltips: true
            property bool showIndicators: true
            property var ignoredApps: ["xwaylandvideobridge"]
        }
        onAdapterUpdated: root.rebuild()
    }

    function settingsSnapshot() {
        return {enabled: settings.enabled, output: settings.output,
            hideMode: settings.autoHide ? "auto" : settings.smartAutoHide ? "smart" : "always",
            showRunning: settings.showRunning, iconSize: settings.iconSize,
            spacing: settings.spacing, bottomMargin: settings.bottomMargin,
            backgroundOpacity: settings.backgroundOpacity, cornerRadius: settings.cornerRadius,
            hideDelay: settings.hideDelay, hoverZoom: settings.hoverZoom,
            showTooltips: settings.showTooltips, showIndicators: settings.showIndicators,
            pinned: settings.pinned, ignoredApps: settings.ignoredApps};
    }
    function configure(json) {
        try {
            const patch = JSON.parse(json);
            if (!patch || Array.isArray(patch) || typeof patch !== "object")
                throw new Error("设置必须是一个对象");
            const booleans = ["enabled", "showRunning", "hoverZoom", "showTooltips", "showIndicators"];
            const ranges = {iconSize: [28,64], spacing: [0,20], bottomMargin: [0,32],
                backgroundOpacity: [40,100], cornerRadius: [0,32], hideDelay: [100,2000]};
            const normalized = {};
            // Validate the complete patch before changing any live setting.
            for (const key of Object.keys(patch)) {
                const value = patch[key];
                if (booleans.indexOf(key) !== -1) {
                    if (typeof value !== "boolean") throw new Error("无效的开关值：" + key);
                    normalized[key] = value;
                } else if (ranges[key]) {
                    if (typeof value !== "number" || !Number.isFinite(value))
                        throw new Error("无效的数值：" + key);
                    normalized[key] = Math.max(ranges[key][0], Math.min(ranges[key][1], Math.round(value)));
                } else if (key === "hideMode") {
                    if (["always", "smart", "auto"].indexOf(value) === -1) throw new Error("无效的隐藏方式");
                    normalized.autoHide = value === "auto";
                    normalized.smartAutoHide = value === "smart";
                } else if (key === "output") {
                    if (typeof value !== "string" || value.length > 128) throw new Error("无效的屏幕名称");
                    normalized.output = value;
                } else if (key === "pinned" || key === "ignoredApps") {
                    if (!Array.isArray(value) || value.some(id => typeof id !== "string" || !id || id.length > 256))
                        throw new Error("无效的应用列表");
                    const ids = key === "pinned" ? value.map(root.canonical) : value;
                    normalized[key] = ids.filter((id, index) => ids.indexOf(id) === index);
                } else throw new Error("未知的设置：" + key);
            }
            for (const key of Object.keys(normalized)) settings[key] = normalized[key];
            configFile.writeAdapter();
            root.rebuild();
            return JSON.stringify({ok: true, settings: root.settingsSnapshot()});
        } catch (error) {
            return JSON.stringify({ok: false, error: String(error)});
        }
    }

    function entry(id) {
        // heuristicLookup() itself has no QML change notification. Desktop entry
        // reloads replace objects even when the list of application IDs is unchanged.
        const revision = root.desktopEntriesRevision;
        return DesktopEntries.heuristicLookup(id);
    }
    function iconSource(app) {
        const name = app ? app.icon : "application-x-executable";
        if (name.startsWith("/")) return "file://" + name;
        if (Quickshell.hasThemeIcon(name)) return Quickshell.iconPath(name);
        if (iconFallbacks[name]) return "file://" + iconFallbacks[name];
        if (name === "utilities-terminal") return Qt.resolvedUrl("terminal.svg");
        return Qt.resolvedUrl("application.svg");
    }
    function canonical(id) {
        const app = entry(id);
        return app ? app.id : id;
    }
    function appWindows(id) {
        return windows.filter(w => canonical(w.app_id || "") === id);
    }
    function isIgnored(id) {
        return settings.ignoredApps.some(ignored => canonical(ignored) === canonical(id));
    }
    function rebuild() {
        let ids = settings.pinned.map(canonical);
        if (settings.showRunning) windows.forEach(w => {
            if (!w.app_id || root.isIgnored(w.app_id)) return;
            const id = canonical(w.app_id);
            if (ids.indexOf(id) === -1) ids.push(id);
        });
        ids = ids.filter((id, i) => ids.indexOf(id) === i);
        if (JSON.stringify(ids) !== JSON.stringify(appIds)) appIds = ids;
    }
    function isPinned(id) { return settings.pinned.map(canonical).indexOf(id) !== -1; }
    function togglePin(id) {
        if (!entry(id)) return;
        if (isPinned(id)) settings.pinned = settings.pinned.filter(p => canonical(p) !== id);
        else settings.pinned = settings.pinned.concat([id]);
        configFile.writeAdapter();
        rebuild();
    }
    function activate(id, newWindow) {
        const wins = appWindows(id).slice().sort((a, b) => a.id - b.id);
        if (newWindow || wins.length === 0) {
            const app = entry(id);
            if (app) app.execute();
            return;
        }
        const current = wins.findIndex(w => w.is_focused);
        const next = wins[(current + 1) % wins.length];
        Quickshell.execDetached(["niri", "msg", "action", "focus-window", "--id", String(next.id)]);
    }
    function receive(line) {
        try {
            const event = JSON.parse(line);
            if (event.WindowsChanged) windows = event.WindowsChanged.windows;
            else if (event.WindowOpenedOrChanged) {
                const w = event.WindowOpenedOrChanged.window;
                let next = windows.filter(v => v.id !== w.id);
                if (w.is_focused) next = next.map(v => Object.assign({}, v, {is_focused: false}));
                windows = next.concat([w]);
            } else if (event.WindowClosed) windows = windows.filter(w => w.id !== event.WindowClosed.id);
            else if (event.WindowFocusChanged) {
                windows = windows.map(w => Object.assign({}, w, {is_focused: w.id === event.WindowFocusChanged.id}));
            } else if (event.WindowUrgencyChanged) {
                const u = event.WindowUrgencyChanged;
                windows = windows.map(w => w.id === u.id ? Object.assign({}, w, {is_urgent: u.urgent}) : w);
            } else if (event.WorkspacesChanged) workspaces = event.WorkspacesChanged.workspaces;
            else if (event.WorkspaceActivated) {
                const active = workspaces.find(w => w.id === event.WorkspaceActivated.id);
                if (active) workspaces = workspaces.map(w => w.output === active.output
                    ? Object.assign({}, w, {is_active: w.id === active.id}) : w);
            }
        } catch (e) { console.warn("Dock event:", e); }
    }
    onWindowsChanged: rebuild()
    Connections {
        target: DesktopEntries
        function onApplicationsChanged() {
            root.desktopEntriesRevision++;
            root.rebuild();
        }
    }
    Component.onCompleted: rebuild()

    Process {
        id: events
        command: ["niri", "msg", "-j", "event-stream"]
        running: true
        stdout: SplitParser { onRead: data => root.receive(data) }
        onExited: reconnect.restart()
    }
    Timer { id: reconnect; interval: 1500; onTriggered: events.running = true }
    IpcHandler {
        target: "dock"
        function themeStatus(): string {
            return JSON.stringify({loaded: theme.loaded, path: theme.colorsPath,
                background: String(theme.background), foreground: String(theme.foreground),
                primary: String(theme.primary), outline: String(theme.outline),
                hover: String(theme.hover), focused: String(theme.focused),
                tooltipBackground: String(theme.tooltipBackground), tooltipForeground: String(theme.tooltipForeground)});
        }
        function getSettings(): string { return JSON.stringify(root.settingsSnapshot()); }
        function contextMenuStatus(): string { return JSON.stringify(contextMenu.snapshot()); }
        function configure(json: string): string { return root.configure(json); }
        function reveal() { root.preview = true; previewTimeout.restart(); }
        function activate(appId: string) { root.activate(root.canonical(appId), false); }
        function togglePin(appId: string) { root.togglePin(root.canonical(appId)); }
        function forgetApplication(appId: string) {
            const pins = settings.pinned.filter(id => root.canonical(id) !== appId);
            if (pins.length !== settings.pinned.length) root.configure(JSON.stringify({pinned: pins}));
            launchpad.forgetApplication(appId);
        }
        function launcher() {
            launchpad.screen = Quickshell.screens[0];
            launchpad.opened = !launchpad.opened;
        }
        function launcherStatus(): string {
            return JSON.stringify({opened: launchpad.opened, count: launchpad.filtered.length,
                page: launchpad.page, pages: launchpad.pageCount,
                selected: launchpad.selectedApp ? launchpad.selectedApp.id : null,
                groups: launchpad.folders, activeFolder: launchpad.activeFolderId,
                dragging: launchpad.dragApp ? launchpad.dragApp.id : null,
                items: launchpad.pageApps.map(item => ({id: item.id, kind: item.kind, name: item.name})),
                wallpaper: launchpad.wallpaperPath, wallpaperStatus: launchpad.wallpaperStatus});
        }
        function status(): string {
            return JSON.stringify({apps: root.appIds, windows: root.windows.length,
                pinned: settings.pinned, autoHide: settings.autoHide, smartAutoHide: settings.smartAutoHide,
                screens: Quickshell.screens.map(s => s.name), settings: root.settingsSnapshot()});
        }
        function toggleAutoHide() {
            const enabled = settings.autoHide || settings.smartAutoHide;
            settings.autoHide = false;
            settings.smartAutoHide = !enabled;
            configFile.writeAdapter();
        }
    }
    Timer { id: previewTimeout; interval: 15000; onTriggered: root.preview = false }

    Variants {
        model: Quickshell.screens
        PanelWindow {
            id: dock
            required property var modelData
            screen: modelData
            visible: settings.enabled && (settings.output === "" || settings.output === screen.name
                || (!Quickshell.screens.some(s => s.name === settings.output) && screen === Quickshell.screens[0]))
            anchors.bottom: true
            implicitWidth: Math.min(screen.width - 24, row.implicitWidth + 32)
            implicitHeight: Math.max(132, dock.size + 24 + settings.bottomMargin + 42)
            color: "transparent"
            exclusiveZone: 0
            WlrLayershell.namespace: "nyx-inspired-dock"
            WlrLayershell.layer: WlrLayer.Top
            WlrLayershell.keyboardFocus: WlrKeyboardFocus.None

            readonly property int size: Math.max(28, Math.min(64, settings.iconSize))
            readonly property bool occupied: {
                const active = root.workspaces.find(w => w.output === screen.name && w.is_active);
                return active !== undefined && root.windows.some(w => w.workspace_id === active.id
                    && !root.isIgnored(w.app_id));
            }
            property bool held: false
            readonly property bool applicationHovered: {
                for (let i = 0; i < appRepeater.count; i++) {
                    const tile = appRepeater.itemAt(i);
                    if (tile && tile.pointerHovered) return true;
                }
                return false;
            }
            readonly property bool pointerInside: dockHover.hovered || launcherMouse.containsMouse || applicationHovered
            readonly property bool menuActive: contextMenu.opened && contextMenu.screen === dock.screen
            onMenuActiveChanged: {
                if (menuActive) { hideDelay.stop(); dock.held = true; }
                else if (!pointerInside) hideDelay.restart();
            }
            onVisibleChanged: if (!visible && menuActive) contextMenu.dismiss()
            onPointerInsideChanged: {
                if (pointerInside) { hideDelay.stop(); dock.held = true; }
                else hideDelay.restart();
            }
            readonly property bool expanded: root.preview || menuActive || pointerInside || held || !(settings.autoHide || (settings.smartAutoHide && occupied))
            function openMenu(id, item, x) {
                const point = item.mapToItem(dock.contentItem, x, 0);
                dock.tooltip = "";
                contextMenu.present(id, dock.screen, (dock.screen.width - dock.width) / 2 + point.x,
                    dock.size + 24 + settings.bottomMargin);
            }
            property string tooltip: ""
            mask: Region { item: hitArea }
            IpcHandler {
                target: "dock-" + dock.screen.name
                function status(): string {
                    return JSON.stringify({expanded: dock.expanded, occupied: dock.occupied,
                        pointerInside: dock.pointerInside, hidePending: hideDelay.running,
                        menuActive: dock.menuActive,
                        windowHovered: dockHover.hovered, launcherHovered: launcherMouse.containsMouse,
                        applicationHovered: dock.applicationHovered,
                        inputHeight: hitArea.height, width: dock.width, surfaceY: surface.y,
                        visible: dock.visible, iconSize: dock.size, spacing: row.spacing,
                        bottomMargin: settings.bottomMargin, backgroundOpacity: surface.color.a, backgroundColor: String(surface.color),
                        cornerRadius: surface.radius, hideDelay: hideDelay.interval,
                        hoverZoom: settings.hoverZoom, showTooltips: settings.showTooltips,
                        showIndicators: settings.showIndicators,
                        icons: Array.from({length: appRepeater.count}, (_, i) => {
                            const tile = appRepeater.itemAt(i);
                            const fresh = root.entry(tile.modelData);
                            return {id: tile.modelData, entryId: tile.app ? tile.app.id : null,
                                freshEntryId: fresh ? fresh.id : null,
                                source: tile.iconSourceUrl, imageStatus: tile.iconStatus};
                        })});
                }
            }

            Item {
                id: hitArea
                anchors.bottom: parent.bottom
                width: parent.width
                height: dock.expanded ? dock.size + 32 + settings.bottomMargin : 3
            }
            // Observe the common ancestor of icons and gaps. A handler on the
            // separate input-mask item loses hover when an icon takes the pointer.
            HoverHandler {
                id: dockHover
                parent: dock.contentItem
                blocking: false
            }
            Timer {
                id: hideDelay
                interval: settings.hideDelay
                onTriggered: {
                    if (dock.pointerInside || dock.menuActive) return;
                    dock.held = false;
                    dock.tooltip = "";
                }
            }

            Rectangle {
                anchors.horizontalCenter: parent.horizontalCenter
                anchors.bottom: parent.bottom
                width: 46; height: 2; radius: 1
                color: theme.alpha(theme.primary, 0.5)
                visible: !dock.expanded
            }
            Rectangle {
                id: surface
                x: 0
                y: dock.expanded ? dock.height - height - settings.bottomMargin : dock.height + 8
                width: dock.width
                height: dock.size + 24
                radius: settings.cornerRadius
                color: theme.alpha(theme.background, settings.backgroundOpacity/100)
                border.width: 1
                border.color: theme.outline
                Behavior on y { NumberAnimation { duration: 190; easing.type: Easing.OutCubic } }
                MouseArea {
                    id: backgroundMouse
                    anchors.fill: parent
                    acceptedButtons: Qt.RightButton
                    onClicked: event => dock.openMenu("", backgroundMouse, event.x)
                }

                Flickable {
                    anchors.fill: parent
                    anchors.leftMargin: 16
                    anchors.rightMargin: 16
                    contentWidth: row.implicitWidth
                    contentHeight: height
                    clip: true
                    flickableDirection: Flickable.HorizontalFlick
                    boundsBehavior: Flickable.StopAtBounds
                    Row {
                        id: row
                        height: parent.height
                        spacing: settings.spacing
                        Rectangle {
                            width: dock.size + 6; height: parent.height
                            radius: 12; color: launcherMouse.containsMouse ? theme.hover : "transparent"
                            Text { anchors.centerIn: parent; text: "⠿"; font.pixelSize: 36; color: theme.primary }
                            MouseArea {
                                id: launcherMouse
                                anchors.fill: parent
                                hoverEnabled: true
                                acceptedButtons: Qt.LeftButton | Qt.RightButton
                                cursorShape: Qt.PointingHandCursor
                                onEntered: dock.tooltip = "应用菜单"
                                onExited: dock.tooltip = ""
                                onClicked: event => {
                                    if (event.button === Qt.RightButton) dock.openMenu("", launcherMouse, event.x);
                                    else root.openLauncher(dock.screen);
                                }
                            }
                        }
                        Rectangle { width: 1; height: dock.size - 6; anchors.verticalCenter: parent.verticalCenter; color: theme.alpha(theme.muted, 0.25) }
                        Repeater {
                            id: appRepeater
                            model: root.appIds
                            Rectangle {
                                id: tile
                                required property string modelData
                                readonly property bool pointerHovered: mouse.containsMouse
                                readonly property var app: root.entry(modelData)
                                readonly property url iconSourceUrl: appIcon.source
                                readonly property int iconStatus: appIcon.status
                                readonly property var wins: root.appWindows(modelData)
                                readonly property bool focused: wins.some(w => w.is_focused)
                                readonly property bool urgent: wins.some(w => w.is_urgent)
                                readonly property bool pinned: root.isPinned(modelData)
                                width: dock.size + 6
                                height: row.height
                                radius: 12
                                color: mouse.containsMouse ? theme.hover : focused ? theme.focused : "transparent"
                                Image {
                                    anchors.horizontalCenter: parent.horizontalCenter
                                    y: 9
                                    width: dock.size; height: dock.size
                                    id: appIcon
                                    source: root.iconSource(tile.app)
                                    sourceSize.width: dock.size * dock.screen.devicePixelRatio
                                    sourceSize.height: dock.size * dock.screen.devicePixelRatio
                                    fillMode: Image.PreserveAspectFit
                                    scale: settings.hoverZoom && mouse.containsMouse ? 1.1 : 0.94
                                    Behavior on scale { NumberAnimation { duration: 120 } }
                                }
                                Rectangle {
                                    anchors.horizontalCenter: parent.horizontalCenter
                                    anchors.bottom: parent.bottom; anchors.bottomMargin: 5
                                    width: tile.focused ? 16 : 5; height: 3; radius: 2
                                    visible: settings.showIndicators && tile.wins.length > 0
                                    color: tile.urgent ? theme.urgent : tile.focused ? theme.primary : theme.muted
                                }
                                Text {
                                    anchors.right: parent.right; anchors.top: parent.top; anchors.margins: 3
                                    visible: settings.showIndicators && tile.wins.length > 1
                                    text: tile.wins.length; color: theme.foreground; font.pixelSize: 11
                                }
                                MouseArea {
                                    id: mouse
                                    anchors.fill: parent
                                    hoverEnabled: true
                                    acceptedButtons: Qt.LeftButton | Qt.MiddleButton | Qt.RightButton
                                    cursorShape: Qt.PointingHandCursor
                                    onEntered: dock.tooltip = (tile.app ? tile.app.name : tile.modelData) + " · 右键查看更多操作"
                                    onExited: dock.tooltip = ""
                                    onClicked: event => {
                                        if (event.button === Qt.RightButton) {
                                            dock.openMenu(tile.modelData, mouse, event.x);
                                        } else root.activate(tile.modelData, event.button === Qt.MiddleButton || (event.modifiers & Qt.ShiftModifier));
                                    }
                                }
                            }
                        }
                    }
                }
            }
            Rectangle {
                anchors.horizontalCenter: parent.horizontalCenter
                y: surface.y - height - 10
                width: Math.min(parent.width, tip.implicitWidth + 24)
                height: 28; radius: 9
                color: theme.tooltipBackground
                visible: settings.showTooltips && !dock.menuActive && dock.expanded && dock.tooltip !== ""
                Text {
                    id: tip
                    anchors.centerIn: parent
                    width: parent.width - 16
                    horizontalAlignment: Text.AlignHCenter
                    elide: Text.ElideRight
                    text: dock.tooltip
                    color: theme.tooltipForeground; font.pixelSize: 12
                }
            }
        }
    }
}
