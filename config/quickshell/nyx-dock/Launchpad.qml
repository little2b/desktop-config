import QtQuick
import QtQuick.Effects
import Quickshell
import Quickshell.Io
import Quickshell.Wayland
import "Grouping.js" as Grouping

PanelWindow {
    id: pad
    required property var controller
    property bool opened: false
    property int page: 0
    property var selectedApp: null
    property real menuX: 0
    property real menuY: 0
    property string activeFolderId: ""
    property var dragApp: null
    property string dragOriginFolder: ""
    property real dragX: 0
    property real dragY: 0
    property var dropTarget: null
    property string notice: ""
    property alias stageItem: stage
    property var storedFolders: []
    property bool foldersReady: false
    readonly property var folders: Grouping.clean(storedFolders)
    readonly property var activeFolder: folders.find(f => f.id === activeFolderId) || null
    readonly property var folderApps: activeFolder ? activeFolder.apps.map(id => applications.find(a => a.id === id)).filter(a => a) : []
    readonly property int folderColumns: Math.max(2, Math.min(5, Math.floor((width - 120) / 138)))
    property string wallpaperPath: ""
    readonly property int wallpaperStatus: wallpaperImage.status
    readonly property int columns: Math.max(3, Math.min(7, Math.floor((width - 100) / 145)))
    readonly property int rows: Math.max(2, Math.min(4, Math.floor((height - 280) / 145)))
    readonly property int pageSize: columns * rows
    readonly property var applications: DesktopEntries.applications.values.filter(app => !app.noDisplay)
        .slice().sort((a, b) => a.name.localeCompare(b.name))
    readonly property var filtered: {
        const query = search.text.trim().toLocaleLowerCase();
        return applications.filter(app => !query || [app.name, app.genericName, app.id,
            (app.keywords || []).join(" ")].join(" ").toLocaleLowerCase().indexOf(query) !== -1);
    }
    readonly property var mainItems: {
        if (search.text.trim()) return filtered.map(appItem);
        const used = {};
        const result = [];
        folders.forEach(f => {
            const apps = f.apps.map(id => applications.find(a => a.id === id)).filter(a => a);
            if (!apps.length) return;
            apps.forEach(a => { used[a.id] = true; });
            result.push({kind: "folder", id: f.id, name: f.name, apps: apps});
        });
        return result.concat(applications.filter(a => !used[a.id]).map(appItem));
    }
    readonly property int pageCount: Math.max(1, Math.ceil(mainItems.length / pageSize))
    readonly property var pageApps: mainItems.slice(page * pageSize, (page + 1) * pageSize)
    onFilteredChanged: { page = 0; selectedApp = null; }
    onPageSizeChanged: page = Math.max(0, Math.min(page, pageCount - 1))
    onPageChanged: selectedApp = null
    onPageCountChanged: page = Math.max(0, Math.min(page, pageCount - 1))
    onActiveFolderChanged: {
        if (!activeFolder) {
            activeFolderId = "";
            if (opened) Qt.callLater(() => search.forceActiveFocus());
        }
    }
    onOpenedChanged: {
        if (opened) {
            search.text = "";
            page = 0;
            selectedApp = null;
            activeFolderId = "";
            cancelDrag();
            Qt.callLater(() => search.forceActiveFocus());
        } else { selectedApp = null; activeFolderId = ""; cancelDrag(); }
    }

    FileView {
        id: folderFile
        path: Qt.resolvedUrl("folders.json")
        preload: true
        blockLoading: true
        atomicWrites: true
        watchChanges: true
        onFileChanged: reload()
        onLoaded: {
            try {
                const data = JSON.parse(text());
                if (data.version !== 1 || !Array.isArray(data.folders)) throw new Error("Invalid folder format");
                pad.storedFolders = Grouping.clean(data.folders);
                pad.foldersReady = true;
            } catch (e) {
                pad.foldersReady = false;
                console.warn("Cannot read Launchpad folders:", e);
                pad.tell("分组配置读取失败，原文件已保留");
            }
        }
        onLoadFailed: { pad.foldersReady = false; pad.tell("无法读取分组配置"); }
        onSaveFailed: pad.tell("分组保存失败，请检查配置文件权限")
    }
    function appItem(app) { return {kind: "app", id: app.id, name: app.name, app: app}; }
    function saveFolders(next) {
        if (!foldersReady) { tell("分组配置尚未就绪"); return; }
        if (JSON.stringify(storedFolders) === JSON.stringify(next)) return;
        storedFolders = next;
        folderFile.setText(JSON.stringify({version: 1, folders: next}, null, 2) + "\n");
    }
    function tell(message) { notice = message; noticeTimer.restart(); }
    function openFolder(id) {
        selectedApp = null;
        activeFolderId = id;
        folderScroll.contentY = 0;
        Qt.callLater(() => folderPanel.forceActiveFocus());
    }
    function closeFolder() {
        if (activeFolder) saveFolders(Grouping.rename(folders, activeFolderId, folderTitle.text));
        activeFolderId = "";
        selectedApp = null;
        search.forceActiveFocus();
    }
    function handleEscape() {
        if (dragApp) cancelDrag();
        else if (activeFolder) closeFolder();
        else dismiss();
    }
    function removeFromFolder(id) {
        saveFolders(Grouping.remove(folders, id));
        selectedApp = null;
        tell("已移出分组");
    }
    function beginDrag(app) {
        selectedApp = null;
        dragApp = app;
        dragOriginFolder = activeFolderId;
    }
    function atGrid(grid, items, cols, cellWidth, x, y) {
        const p = grid.mapFromItem(stage, x, y);
        const col = Math.floor(p.x / cellWidth), row = Math.floor(p.y / 145);
        if (col < 0 || col >= cols || row < 0 || p.x % cellWidth < 10 || p.x % cellWidth > cellWidth - 10 || p.y % 145 > 126) return null;
        return items[row * cols + col] || null;
    }
    function targetAt(x, y) {
        if (activeFolder) {
            const p = folderScroll.mapFromItem(stage, x, y);
            if (p.x < 0 || p.y < 0 || p.x > folderScroll.width || p.y > folderScroll.height) return null;
            return atGrid(folderGrid, folderApps.map(appItem), folderColumns, 138, x, y);
        }
        return atGrid(appGrid, pageApps, columns, content.width / columns, x, y);
    }
    function inRemoveZone(x, y) {
        const p = removeZone.mapFromItem(stage, x, y);
        return dragOriginFolder !== "" && p.x >= 0 && p.y >= 0 && p.x < removeZone.width && p.y < removeZone.height;
    }
    function moveDrag(x, y) {
        dragX = x; dragY = y;
        const target = targetAt(x, y);
        const member = target ? (target.kind === "folder" ? target.id : (Grouping.containing(folders, target.id) || {}).id) : "";
        const origin = dragApp ? Grouping.containing(folders, dragApp.id) : null;
        dropTarget = target && dragApp && target.id !== dragApp.id && (!origin || member !== origin.id) ? target : null;
    }
    function cancelDrag() { dragApp = null; dropTarget = null; dragOriginFolder = ""; }
    function finishDrag(x, y) {
        if (!dragApp) return;
        moveDrag(x, y);
        const sourceId = dragApp.id, target = dropTarget, remove = inRemoveZone(x, y);
        cancelDrag();
        // Let the grabbed MouseArea release before changing the model.
        Qt.callLater(() => {
            if (remove) { removeFromFolder(sourceId); return; }
            if (!target) return;
            const existing = target.kind === "folder" ? folders.find(f => f.id === target.id) : Grouping.containing(folders, target.id);
            const newId = "folder-" + Date.now().toString(36) + "-" + Math.random().toString(36).slice(2, 7);
            saveFolders(Grouping.group(folders, sourceId, target, newId));
            if (!existing) {
                search.text = "";
                openFolder(newId);
                Qt.callLater(() => { folderTitle.forceActiveFocus(); folderTitle.selectAll(); });
            } else tell("已加入「" + existing.name + "」");
        });
    }

    function dismiss() { opened = false; }
    function showMenu(app, x, y) {
        selectedApp = app;
        menuX = Math.max(16, Math.min(x, width - appMenu.width - 16));
        menuY = Math.max(16, Math.min(y, height - appMenu.height - 16));
    }
    function launch(app) {
        if (!app) return;
        dismiss();
        controller.activate(controller.canonical(app.id), false);
    }

    visible: opened || revealAnimation.running
    anchors { top: true; bottom: true; left: true; right: true }
    color: "transparent"
    exclusiveZone: 0
    WlrLayershell.namespace: "nyx-launchpad"
    WlrLayershell.layer: WlrLayer.Overlay
    WlrLayershell.keyboardFocus: opened ? WlrKeyboardFocus.Exclusive : WlrKeyboardFocus.None

    FileView {
        path: Quickshell.env("HOME") + "/.config/clavis/config.json"
        preload: true
        watchChanges: true
        onFileChanged: reload()
        onLoaded: {
            try { pad.wallpaperPath = JSON.parse(text()).wallpaper.path || ""; }
            catch (e) { pad.wallpaperPath = ""; }
        }
    }

    Item {
        id: stage
        property var launcher: pad
        focus: true
        anchors.fill: parent
        opacity: pad.opened ? 1 : 0
        Behavior on opacity { NumberAnimation { id: revealAnimation; duration: 180; easing.type: Easing.OutCubic } }
        Keys.onEscapePressed: pad.handleEscape()
        Image {
            id: wallpaperImage
            anchors.fill: parent
            source: pad.wallpaperPath ? "file://" + pad.wallpaperPath : ""
            fillMode: Image.PreserveAspectCrop
            sourceSize.width: pad.width
            sourceSize.height: pad.height
            visible: true
        }
        MultiEffect {
            anchors.fill: parent
            source: wallpaperImage
            blurEnabled: true
            blurMax: 64
            blur: 1
            saturation: -0.4
        }
        Rectangle {
            anchors.fill: parent
            gradient: Gradient {
                GradientStop { position: 0; color: "#942a253a" }
                GradientStop { position: 0.55; color: "#a025273d" }
                GradientStop { position: 1; color: "#d9161823" }
            }
        }
        MouseArea {
            anchors.fill: parent
            acceptedButtons: Qt.LeftButton | Qt.RightButton
            onClicked: pad.dismiss()
            onWheel: event => {
                if (pageScroll.running) return;
                const delta = event.angleDelta.y || event.angleDelta.x;
                if (delta !== 0) {
                    pad.page = Math.max(0, Math.min(pad.pageCount - 1, pad.page + (delta < 0 ? 1 : -1)));
                    pageScroll.restart();
                }
            }
        }
        Timer { id: pageScroll; interval: 220 }

        Item {
            id: content
            width: Math.min(parent.width - 64, pad.columns * 150)
            height: Math.min(parent.height - 64, 210 + pad.rows * 145)
            anchors.centerIn: parent
            scale: pad.opened ? 1 : 0.95
            Behavior on scale { NumberAnimation { duration: 220; easing.type: Easing.OutCubic } }
            Text {
                anchors.horizontalCenter: parent.horizontalCenter
                y: 0
                text: "应用程序"
                color: "#faf4ff"
                font.pixelSize: 28
                font.weight: Font.Medium
                font.letterSpacing: 2
            }
            Rectangle {
                id: searchBox
                y: 56
                anchors.horizontalCenter: parent.horizontalCenter
                width: Math.min(360, parent.width - 32)
                height: 44; radius: 14
                color: "#24ffffff"
                border.width: 1
                border.color: search.activeFocus ? "#80e4cbec" : "#35ffffff"
                MouseArea { anchors.fill: parent; onClicked: search.forceActiveFocus() }
                Text { x: 15; anchors.verticalCenter: parent.verticalCenter; text: "⌕"; font.pixelSize: 27; color: "#e9ddec" }
                TextInput {
                    id: search
                    objectName: "launchpadSearch"
                    anchors { left: parent.left; right: parent.right; verticalCenter: parent.verticalCenter; leftMargin: 45; rightMargin: 14 }
                    font.pixelSize: 15
                    color: "white"
                    selectionColor: "#805d738e"
                    clip: true
                    selectByMouse: true
                    activeFocusOnTab: true
                    Keys.onEscapePressed: pad.handleEscape()
                    Keys.onReturnPressed: pad.launch(pad.selectedApp || pad.filtered[0])
                    Keys.onEnterPressed: pad.launch(pad.selectedApp || pad.filtered[0])
                    Keys.onDownPressed: pad.page = Math.min(pad.pageCount - 1, pad.page + 1)
                    Keys.onUpPressed: pad.page = Math.max(0, pad.page - 1)
                    Text { anchors.fill: parent; visible: !search.text; text: "搜索应用"; color: "#bce5ddeb"; font: search.font }
                }
            }
            Grid {
                id: appGrid
                y: 134
                width: parent.width
                columns: pad.columns
                columnSpacing: 0
                rowSpacing: 0
                Repeater {
                    model: pad.pageSize
                    LaunchpadTile {
                        required property int index
                        pad: stage.launcher
                        entry: pad.pageApps[index] || null
                        width: content.width / pad.columns
                    }
                }
            }

            Text {
                anchors.centerIn: parent
                visible: pad.filtered.length === 0
                text: "没有找到应用"; color: "#d9ccdF"; font.pixelSize: 18
            }
            Row {
                anchors.horizontalCenter: parent.horizontalCenter
                anchors.bottom: parent.bottom
                spacing: 14
                Repeater {
                    model: pad.pageCount
                    Rectangle {
                        required property int index
                        width: 9; height: 9; radius: 5
                        color: pad.page === index ? "#f9e4f2" : "#50ffffff"
                        MouseArea {
                            anchors.fill: parent; anchors.margins: -6
                            cursorShape: Qt.PointingHandCursor
                            onClicked: pad.page = parent.index
                        }
                    }
                }
            }
        }
        Rectangle {
            z: 10
            anchors.fill: parent
            visible: pad.activeFolder !== null
            color: "#800c0a13"
            MouseArea { anchors.fill: parent; onClicked: pad.closeFolder() }
        }
        Rectangle {
            id: folderPanel
            z: 11
            anchors.centerIn: parent
            width: pad.folderColumns * 138 + 52
            height: Math.min(pad.height - 220, 124 + Math.ceil(pad.folderApps.length / pad.folderColumns) * 145)
            visible: pad.activeFolder !== null
            radius: 30
            color: "#f0373044"
            border.width: 1; border.color: "#80a98cb7"
            focus: visible
            Keys.onEscapePressed: pad.handleEscape()
            MouseArea { anchors.fill: parent; onClicked: folderPanel.forceActiveFocus() }
            TextInput {
                id: folderTitle
                x: 26; y: 24; width: parent.width - 126
                text: pad.activeFolder ? pad.activeFolder.name : ""
                font.pixelSize: 23; font.weight: Font.Medium; color: "#fff2ff"
                maximumLength: 48
                selectByMouse: true
                selectionColor: "#8c685876"
                clip: true
                onEditingFinished: if (pad.activeFolder) pad.saveFolders(Grouping.rename(pad.folders, pad.activeFolderId, text))
                onAccepted: folderPanel.forceActiveFocus()
                Keys.onEscapePressed: pad.handleEscape()
            }
            Text { x: 26; y: 57; text: "点击名称可重命名"; font.pixelSize: 11; color: "#bea9c7" }
            Rectangle {
                anchors.right: parent.right; anchors.rightMargin: 22
                y: 25; width: 66; height: 32; radius: 11
                color: closeMouse.containsMouse ? "#506e567a" : "#306e567a"
                Text { anchors.centerIn: parent; text: "完成"; color: "#fbeafa"; font.pixelSize: 13 }
                MouseArea { id: closeMouse; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: pad.closeFolder() }
            }
            Flickable {
                id: folderScroll
                x: 26; y: 88; width: parent.width - 52; height: parent.height - 105
                contentWidth: width
                contentHeight: folderGrid.height
                clip: true
                interactive: !pad.dragApp
                boundsBehavior: Flickable.StopAtBounds
                Grid {
                    id: folderGrid
                    columns: pad.folderColumns
                    Repeater {
                        model: pad.folderApps
                        LaunchpadTile {
                            required property var modelData
                            pad: stage.launcher
                            entry: pad.appItem(modelData)
                            width: 138
                        }
                    }
                }
            }
        }
        Rectangle {
            id: removeZone
            z: 15
            anchors.horizontalCenter: parent.horizontalCenter
            y: Math.min(parent.height - 90, folderPanel.y + folderPanel.height + 16)
            width: Math.min(parent.width - 32, 380); height: 58; radius: 18
            visible: pad.dragApp !== null && pad.dragOriginFolder !== ""
            color: pad.inRemoveZone(pad.dragX, pad.dragY) ? "#cc9d4c77" : "#aa42384f"
            border.width: 1; border.color: "#d5b0cf"
            Text { anchors.centerIn: parent; text: "拖到这里，移出分组"; color: "#fff1fb"; font.pixelSize: 15 }
        }
        Repeater {
            model: [-1, 1]
            Rectangle {
                required property int modelData
                z: 15
                x: modelData < 0 ? 0 : stage.width - width
                anchors.verticalCenter: parent.verticalCenter
                width: 70; height: 120; radius: 24
                visible: pad.dragApp !== null && !pad.activeFolder && (modelData < 0 ? pad.page > 0 : pad.page < pad.pageCount - 1)
                color: "#456e567a"
                Text { anchors.centerIn: parent; text: parent.modelData < 0 ? "‹" : "›"; color: "#f4ddf2"; font.pixelSize: 38 }
            }
        }
        Timer {
            interval: 750; repeat: true
            running: pad.dragApp !== null && !pad.activeFolder && (pad.dragX < 80 || pad.dragX > pad.width - 80)
            onTriggered: {
                pad.page = Math.max(0, Math.min(pad.pageCount - 1, pad.page + (pad.dragX < 80 ? -1 : 1)));
                pad.moveDrag(pad.dragX, pad.dragY);
            }
        }
        Item {
            z: 100
            x: pad.dragX - 36; y: pad.dragY - 42
            width: 72; height: 72
            visible: pad.dragApp !== null
            Image { anchors.fill: parent; source: pad.dragApp ? pad.controller.iconSource(pad.dragApp) : ""; sourceSize: Qt.size(144, 144) }
            Rectangle {
                anchors.horizontalCenter: parent.horizontalCenter
                y: 82; width: hint.implicitWidth + 24; height: 30; radius: 10
                color: "#f046354e"
                Text {
                    id: hint
                    anchors.centerIn: parent
                    text: pad.inRemoveZone(pad.dragX, pad.dragY) ? "松开以移出分组" : pad.dropTarget ? (pad.dropTarget.kind === "folder" ? "松开以加入分组" : "松开以分组") : "拖到应用或分组上"
                    color: "#fff0fc"; font.pixelSize: 12
                }
            }
        }
        Timer { id: noticeTimer; interval: 2400; onTriggered: pad.notice = "" }
        Rectangle {
            z: 40
            anchors.horizontalCenter: parent.horizontalCenter
            anchors.bottom: parent.bottom; anchors.bottomMargin: 54
            width: noticeText.implicitWidth + 30; height: 36; radius: 12
            visible: pad.notice !== ""
            color: "#f044354e"
            Text { id: noticeText; anchors.centerIn: parent; text: pad.notice; color: "#fff0fa"; font.pixelSize: 13 }
        }
        Text {
            anchors.horizontalCenter: parent.horizontalCenter
            anchors.bottom: parent.bottom; anchors.bottomMargin: 30
            text: "拖到另一个应用上创建分组  ·  拖到屏幕边缘翻页  ·  左键选择操作  ·  Esc 返回"
            color: "#9cddd0e4"; font.pixelSize: 12
        }
        Rectangle {
            id: appMenu
            z: 30
            objectName: "launchpadAppMenu"
            x: pad.menuX; y: pad.menuY
            visible: pad.selectedApp !== null
            width: 246; height: pad.selectedApp && Grouping.containing(pad.folders, pad.selectedApp.id) ? 193 : 147; radius: 17
            color: "#fa35303e"
            border.width: 1; border.color: "#706e607c"
            MouseArea { anchors.fill: parent; acceptedButtons: Qt.AllButtons }
            Text {
                x: 16; y: 14; width: parent.width - 32
                text: pad.selectedApp ? pad.selectedApp.name : ""
                elide: Text.ElideRight
                font.pixelSize: 13; font.weight: Font.Medium; color: "#cdbcd5"
            }
            Column {
                x: 7; y: 42; width: parent.width - 14; spacing: 3
                Repeater {
                    model: pad.selectedApp && Grouping.containing(pad.folders, pad.selectedApp.id) ? ["打开应用", "pin", "remove"] : ["打开应用", "pin"]
                    Rectangle {
                        required property string modelData
                        width: parent.width; height: 43; radius: 10
                        color: actionMouse.containsMouse ? "#35e1b1d4" : "transparent"
                        readonly property bool pinned: pad.selectedApp !== null && pad.controller.isPinned(pad.selectedApp.id)
                        Text {
                            x: 12; anchors.verticalCenter: parent.verticalCenter
                            text: parent.modelData === "remove" ? "移出分组" : parent.modelData === "pin" ? (parent.pinned ? "从 Dock 取消固定" : "将此应用固定到 Dock") : "打开应用"
                            font.pixelSize: 14; color: "#fff4ff"
                        }
                        MouseArea {
                            id: actionMouse
                            anchors.fill: parent; hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: {
                                if (parent.modelData === "pin") {
                                    pad.controller.togglePin(pad.controller.canonical(pad.selectedApp.id));
                                    pad.selectedApp = null;
                                } else if (parent.modelData === "remove") pad.removeFromFolder(pad.selectedApp.id);
                                else pad.launch(pad.selectedApp);
                            }
                        }
                    }
                }
            }
        }
    }
}
