import QtQuick

Item {
    id: tile
    required property var pad
    property var entry: null
    readonly property bool folder: entry !== null && entry.kind === "folder"
    readonly property bool pinned: entry !== null && !folder && pad.controller.isPinned(entry.id)
    readonly property bool targetted: entry !== null && pad.dropTarget !== null && pad.dropTarget.id === entry.id
    height: 145

    Item {
        anchors.fill: parent
        visible: tile.entry !== null
        opacity: tile.entry && pad.dragApp && tile.entry.id === pad.dragApp.id ? 0.3 : 1
        Rectangle {
            x: 10; width: parent.width - 20; height: 126; radius: 21
            color: tile.targetted ? "#40eab6d0" : appMouse.containsMouse ? "#1cffffff" : "transparent"
            border.width: tile.targetted ? 2 : 0
            border.color: "#f2bfdc"
            Behavior on color { ColorAnimation { duration: 100 } }
        }
        Item {
            id: icon
            anchors.horizontalCenter: parent.horizontalCenter
            y: 11; width: 72; height: 72
            scale: tile.targetted ? 1.13 : appMouse.containsMouse && !pad.dragApp ? 1.08 : 1
            Behavior on scale { NumberAnimation { duration: 130; easing.type: Easing.OutCubic } }
            Image {
                anchors.fill: parent
                visible: !tile.folder
                source: tile.entry && !tile.folder ? pad.controller.iconSource(tile.entry.app) : ""
                sourceSize: Qt.size(144, 144)
                fillMode: Image.PreserveAspectFit
            }
            Rectangle {
                anchors.fill: parent
                visible: tile.folder
                radius: 18; color: "#607e728e"
                border.width: 1; border.color: "#75dfc5e5"
                Grid {
                    anchors.centerIn: parent
                    columns: 3; spacing: 4
                    Repeater {
                        model: tile.folder ? tile.entry.apps.slice(0, 9) : []
                        Image {
                            required property var modelData
                            width: 17; height: 17
                            sourceSize: Qt.size(34, 34)
                            fillMode: Image.PreserveAspectFit
                            source: pad.controller.iconSource(modelData)
                        }
                    }
                }
            }
        }
        Rectangle {
            visible: tile.pinned
            x: icon.x + 61; y: 67
            width: 16; height: 16; radius: 8
            color: "#eab6d0"; border.color: "#433343"; border.width: 2
            Text { anchors.centerIn: parent; text: "✓"; font.pixelSize: 10; color: "#322331" }
        }
        Text {
            x: 8; y: 95; width: parent.width - 16
            horizontalAlignment: Text.AlignHCenter
            text: tile.entry ? tile.entry.name : ""
            color: "#f9f3ff"; font.pixelSize: 13
            maximumLineCount: 2; wrapMode: Text.Wrap; elide: Text.ElideRight; lineHeight: 1.1
        }
    }
    // This MouseArea survives page changes, so the pointer grab is not lost
    // when the user holds an app at the edge to turn a page.
    MouseArea {
        id: appMouse
        x: 10; width: parent.width - 20; height: 126
        enabled: tile.entry !== null || pressed
        hoverEnabled: true
        acceptedButtons: Qt.LeftButton | Qt.RightButton
        preventStealing: true
        cursorShape: pad.dragApp ? Qt.ClosedHandCursor : Qt.PointingHandCursor
        property var pressedEntry: null
        property point start
        property bool moved: false
        onPressed: mouse => {
            pressedEntry = tile.entry;
            start = mapToItem(pad.stageItem, mouse.x, mouse.y);
            moved = false;
        }
        onPositionChanged: mouse => {
            if (!pressed || !(pressedButtons & Qt.LeftButton) || !pressedEntry || pressedEntry.kind !== "app") return;
            const p = mapToItem(pad.stageItem, mouse.x, mouse.y);
            if (!moved && Math.hypot(p.x - start.x, p.y - start.y) > 12) {
                moved = true;
                pad.beginDrag(pressedEntry.app);
            }
            if (moved) pad.moveDrag(p.x, p.y);
        }
        onReleased: mouse => {
            if (moved) {
                const p = mapToItem(pad.stageItem, mouse.x, mouse.y);
                pad.finishDrag(p.x, p.y);
            }
        }
        onCanceled: { pad.cancelDrag(); moved = true; }
        onClicked: mouse => {
            if (moved || !pressedEntry) return;
            if (pressedEntry.kind === "folder") pad.openFolder(pressedEntry.id);
            else {
                const p = mapToItem(pad.stageItem, mouse.x, mouse.y);
                pad.showMenu(pressedEntry.app, p.x + 8, p.y + 8);
            }
        }
    }
}
