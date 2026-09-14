import QtQuick
import Quickshell
import Quickshell.Wayland

PanelWindow {
    id: menu
    required property var controller
    required property var theme
    property bool opened: false
    property string appId: ""
    property real anchorX: 0
    property int bottomOffset: 72
    property int currentIndex: -1
    readonly property var app: appId ? controller.entry(appId) : null
    readonly property var wins: appId ? controller.appWindows(appId).slice().sort((a, b) => a.id - b.id) : []
    readonly property var options: controller.settingsSnapshot()
    readonly property var entries: {
        let rows = [];
        if (appId) {
            rows.push({key: "open", label: wins.length ? "切换到应用" : "打开应用", enabled: !!app || wins.length > 0});
            rows.push({key: "new", label: "新开窗口", enabled: !!app});
            rows.push({key: "pin", label: controller.isPinned(appId) ? "从 Dock 取消固定" : "固定到 Dock", enabled: !!app});
            const pins = options.pinned.map(controller.canonical);
            const index = pins.indexOf(appId);
            if (index !== -1) {
                rows.push({key: "left", label: "向左移动", enabled: index > 0});
                rows.push({key: "right", label: "向右移动", enabled: index < pins.length - 1});
            }
            if (wins.length) {
                rows.push({key: "heading", label: "已打开的窗口", heading: true});
                wins.forEach(w => rows.push({key: "window", windowId: w.id,
                    label: (w.is_focused ? "●  " : "") + (w.title || "无标题窗口"), enabled: true}));
                rows.push({key: "close", label: wins.length === 1 ? "关闭窗口" : "关闭全部窗口（" + wins.length + "）", enabled: true});
            }
        } else {
            rows.push({key: "launcher", label: "所有应用", enabled: true});
            rows.push({key: "heading", label: "显示方式", heading: true});
            [{mode: "always", label: "始终显示"}, {mode: "smart", label: "智能隐藏"}, {mode: "auto", label: "自动隐藏"}].forEach(mode =>
                rows.push({key: "mode", mode: mode.mode, label: mode.label, checked: options.hideMode === mode.mode, enabled: true}));
            rows.push({key: "running", label: "显示运行中的应用", checked: options.showRunning, enabled: true});
        }
        rows.push({key: "separator", separator: true});
        rows.push({key: "settings", label: "Dock 设置…", enabled: true});
        return rows;
    }

    function present(id, output, x, offset) {
        appId = id;
        screen = output;
        anchorX = x;
        bottomOffset = offset;
        currentIndex = -1;
        list.contentY = 0;
        opened = true;
        Qt.callLater(() => keyboard.forceActiveFocus());
    }
    function dismiss() { opened = false; }
    function step(direction) {
        let next = currentIndex < 0 ? (direction > 0 ? -1 : 0) : currentIndex;
        for (let count = 0; count < entries.length; count++) {
            next = (next + direction + entries.length) % entries.length;
            if (entries[next].enabled) {
                currentIndex = next;
                const row = rows.itemAt(next);
                if (row) list.contentY = Math.max(0, Math.min(list.contentHeight - list.height, row.y - list.height / 2));
                return;
            }
        }
    }
    function invoke(item) {
        if (!item || !item.enabled) return;
        const id = appId;
        const openWindows = wins.slice();
        const output = screen;
        dismiss();
        Qt.callLater(() => {
            switch (item.key) {
            case "open": controller.activate(id, false); break;
            case "new": controller.activate(id, true); break;
            case "pin": controller.togglePin(id); break;
            case "left": controller.movePinned(id, -1); break;
            case "right": controller.movePinned(id, 1); break;
            case "window": Quickshell.execDetached(["niri", "msg", "action", "focus-window", "--id", String(item.windowId)]); break;
            case "close": openWindows.forEach(w => Quickshell.execDetached(["niri", "msg", "action", "close-window", "--id", String(w.id)])); break;
            case "launcher": controller.openLauncher(output); break;
            case "mode": controller.configure(JSON.stringify({hideMode: item.mode})); break;
            case "running": controller.configure(JSON.stringify({showRunning: !options.showRunning})); break;
            case "settings": Quickshell.execDetached(["/usr/bin/qs", "ipc", "-c", "clavis", "call", "control-center", "open", "dock"]); break;
            }
        });
    }
    function snapshot() {
        return {opened: opened, appId: appId, output: screen ? screen.name : "",
            x: popup.x, y: popup.y, width: popup.width, height: popup.height,
            entries: entries.map((entry, i) => {
                const row = rows.itemAt(i);
                return {key: entry.key, label: entry.label, enabled: !!entry.enabled,
                    checked: !!entry.checked, x: popup.x + 14, y: popup.y + list.y + (row ? row.y : 0) - list.contentY,
                    height: row ? row.height : 0};
            })};
    }

    visible: opened
    color: "transparent"
    anchors { top: true; bottom: true; left: true; right: true }
    exclusionMode: ExclusionMode.Ignore
    exclusiveZone: 0
    WlrLayershell.namespace: "nyx-dock-context-menu"
    WlrLayershell.layer: WlrLayer.Overlay
    WlrLayershell.keyboardFocus: opened ? WlrKeyboardFocus.Exclusive : WlrKeyboardFocus.None

    Item {
        id: keyboard
        anchors.fill: parent
        focus: true
        Keys.onEscapePressed: menu.dismiss()
        Keys.onDownPressed: menu.step(1)
        Keys.onUpPressed: menu.step(-1)
        Keys.onReturnPressed: menu.invoke(menu.entries[menu.currentIndex])
        Keys.onEnterPressed: menu.invoke(menu.entries[menu.currentIndex])
        MouseArea {
            anchors.fill: parent
            acceptedButtons: Qt.AllButtons
            onClicked: menu.dismiss()
        }
        Rectangle {
            id: popup
            x: Math.max(12, Math.min(menu.width - width - 12, menu.anchorX - width / 2))
            y: Math.max(12, menu.height - menu.bottomOffset - height - 10)
            width: Math.min(300, menu.width - 24)
            height: Math.min(menu.height - menu.bottomOffset - 24, body.implicitHeight + 62)
            radius: 16
            color: menu.theme.background
            border.width: 1
            border.color: menu.theme.outline
            MouseArea { anchors.fill: parent; acceptedButtons: Qt.AllButtons }
            Row {
                x: 14; y: 12; spacing: 9
                Image {
                    visible: !!menu.app
                    width: visible ? 24 : 0; height: 24
                    source: menu.app ? menu.controller.iconSource(menu.app) : ""
                    sourceSize: Qt.size(48, 48)
                }
                Text {
                    width: popup.width - 40 - (menu.app ? 33 : 0)
                    height: 24
                    verticalAlignment: Text.AlignVCenter
                    text: menu.app ? menu.app.name : menu.appId || "Dock"
                    elide: Text.ElideRight
                    color: menu.theme.foreground
                    font.pixelSize: 14; font.weight: Font.DemiBold
                }
            }
            Flickable {
                id: list
                x: 7; y: 46; width: parent.width - 14; height: parent.height - 54
                contentHeight: body.implicitHeight
                clip: true
                boundsBehavior: Flickable.StopAtBounds
                Column {
                    id: body
                    width: list.width
                    spacing: 2
                    Repeater {
                        id: rows
                        model: menu.entries
                        Rectangle {
                            id: row
                            required property var modelData
                            required property int index
                            width: body.width
                            height: modelData.separator ? 9 : modelData.heading ? 26 : 35
                            radius: 8
                            color: modelData.enabled && (area.containsMouse || menu.currentIndex === index) ? menu.theme.hover : "transparent"
                            Rectangle {
                                anchors.centerIn: parent
                                width: parent.width - 16; height: 1
                                visible: !!row.modelData.separator
                                color: menu.theme.outline
                            }
                            Text {
                                x: row.modelData.heading ? 11 : 28
                                width: parent.width - x - 12
                                anchors.verticalCenter: parent.verticalCenter
                                visible: !row.modelData.separator
                                text: row.modelData.label || ""
                                elide: Text.ElideRight
                                font.pixelSize: row.modelData.heading ? 11 : 13
                                color: row.modelData.enabled ? menu.theme.foreground : menu.theme.muted
                                opacity: row.modelData.heading || row.modelData.enabled ? 1 : 0.6
                            }
                            Text {
                                x: 9; anchors.verticalCenter: parent.verticalCenter
                                visible: !!row.modelData.checked
                                text: "✓"; color: menu.theme.primary; font.pixelSize: 13
                            }
                            MouseArea {
                                id: area
                                anchors.fill: parent
                                enabled: !!row.modelData.enabled
                                hoverEnabled: true
                                cursorShape: Qt.PointingHandCursor
                                onEntered: menu.currentIndex = row.index
                                onClicked: menu.invoke(row.modelData)
                            }
                        }
                    }
                }
            }
        }
    }
}
