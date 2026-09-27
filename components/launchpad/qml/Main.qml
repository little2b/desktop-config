import QtQuick
import QtQuick.Effects

Window {
    id: root
    flags: Qt.FramelessWindowHint
    color: "transparent"
    // 初始不显示；全屏显示由 C++ 端 showFullScreen() 控制
    // (避免 visible 与 visibility 属性冲突)

    // ---------- 网格 ----------
    readonly property int cols: 7
    readonly property int rows: 5
    readonly property int perPage: cols * rows

    // ---------- 状态 ----------
    property string phase: "hidden"
    property real openProgress: 0
    property int preparationFrames: 0
    property int imageRevision: 0
    readonly property bool contentReady: {
        const revision = imageRevision
        if (!WallpaperBackend.prepared) return false
        if (bgImage.status === Image.Loading) return false
        for (let i = 0; i < appRepeater.count; ++i) {
            const tile = appRepeater.itemAt(i)
            if (!tile || !tile.iconReady) return false
        }
        return true
    }
    property string filterText: ""
    readonly property bool searching: filterText !== ""
    property string wpUrl: ""
    property int currentPage: 0
    property int pageCount: Math.max(1, Math.ceil(AppListModel.count / perPage))

    // 抖动编辑态 / 拖动会话
    property bool editMode: false      // macOS 抖动编辑态
    property bool dragActive: false
    property string dragId: ""         // 正被拖动的 desktopId（用 id 而非行号，
                                       // 模型重排后判定依然准确）
    property var dragOrder: []         // 槽位 → desktopId；空数组表示未重排
    property var slotIndex: ({})       // desktopId → 槽位
    property point dragPoint: Qt.point(0, 0)
    property bool pageDragging: false  // 空白处横向拖动翻页

    // ---------- 文件夹 ----------
    property string folderOpen: ""       // 当前展开的文件夹 id
    property string mergeCandidate: ""   // 拖动悬停中的合并目标 id
    property var dragOriginOrder: []     // 拖动开始时的"槽位→id"快照（不受让位影响）

    readonly property real cellW: pagesArea.width / cols
    readonly property real cellH: pagesArea.height / rows
    readonly property real iconSize: Math.max(64, Math.min(112, Math.min(cellW, cellH) * 0.54))

    // ---------- 行号 ⇄ 槽位 ----------
    // 静止时行号即槽位；拖动期间由 dragOrder/slotIndex 决定。
    // 因为映射基于 desktopId，commitOrder 重排模型后行号变了、槽位不变，
    // 松手前后图标位置完全连续。
    function slotOfRow(row) {
        if (dragOrder.length === 0) return row
        const s = slotIndex[AppListModel.idAt(row)]
        return s === undefined ? -1 : s
    }

    // root 坐标 → 全局槽位（落在网格外返回 -1）
    function slotAtPoint(px, py) {
        if (AppListModel.count <= 0) return -1
        const localX = px - pagesArea.x
        const localY = py - pagesArea.y
        if (localX < 0 || localX > pagesArea.width) return -1
        if (localY < 0 || localY > pagesArea.height) return -1
        const col = Math.max(0, Math.min(cols - 1, Math.floor(localX / cellW)))
        const r = Math.max(0, Math.min(rows - 1, Math.floor(localY / cellH)))
        const slot = currentPage * perPage + r * cols + col
        return Math.max(0, Math.min(slot, AppListModel.count - 1))
    }

    function closeWindow() {
        if (!visible || phase === "closing") return
        opening.stop()
        phase = "closing"
        closing.from = openProgress
        closing.start()
    }
    function reopen() {
        if (phase !== "closing") return
        closing.stop()
        phase = "opening"
        opening.from = openProgress
        opening.start()
    }

    // 点击空白：抖动态先退出编辑态，否则关闭窗口
    function blankClick() {
        if (root.editMode) root.exitEditMode()
        else root.closeWindow()
    }

    // 壁纸异步就绪后加载
    Connections {
        target: WallpaperBackend
        function onReady() {
            root.wpUrl = WallpaperBackend.url()
            root.imageRevision++
        }
    }

    // ---------- 拖动会话 ----------
    // 进入拖动：把当前顺序记录成 id 序列，之后只动这个序列，不碰模型
    // 注意：参数不能叫 id —— QML 里 id 是保留标识符，会让整次调用的实参转换失败
    function beginDrag(appId, icon, name, pt) {
        const ids = []
        for (let i = 0; i < AppListModel.count; ++i) ids.push(AppListModel.idAt(i))
        root.dragOrder = ids
        root.dragOriginOrder = ids.slice()
        root.reindexSlots()
        root.dragActive = true
        root.dragId = appId
        ghost.iconSource = icon
        ghost.labelText = name
        ghost.visible = true
        root.moveGhost(pt)
        ghostPop.restart()
    }

    // 是否真的换了位置：没换就不提交，省掉一次模型 reset（图标会重建）。
    // 拖动期间模型没动，所以 idAt(i) 仍是未拖动时的原始顺序。
    function isOrderChanged() {
        for (let i = 0; i < root.dragOrder.length; ++i) {
            if (root.dragOrder[i] !== AppListModel.idAt(i)) return true
        }
        return false
    }

    // ---------- 翻页手势（网格空白处与图标上通用） ----------
    // 网格被图标铺满，拖动多半落在图标上，所以手势必须由 IconDelegate 的
    // MouseArea 也能触发，不能只在空白处做。
    property point pageDragOrigin: Qt.point(0, 0)

    function pageDragBegin(pt) {
        root.pageDragging = true
        root.pageDragOrigin = pt
        pager.dragOffset = 0
    }

    function pageDragMove(pt) {
        if (!root.pageDragging) return
        let off = pt.x - root.pageDragOrigin.x
        // 首尾页反向拖动做阻尼
        if ((root.currentPage === 0 && off > 0) ||
            (root.currentPage >= root.pageCount - 1 && off < 0)) off *= 0.35
        pager.dragOffset = off
    }

    function pageDragEnd() {
        if (!root.pageDragging) return
        const threshold = root.width * 0.12
        let target = root.currentPage
        if (pager.dragOffset < -threshold && root.currentPage < root.pageCount - 1) target++
        else if (pager.dragOffset > threshold && root.currentPage > 0) target--
        root.pageDragging = false
        pager.dragOffset = 0
        root.currentPage = target
    }

    function reindexSlots() {
        const m = {}
        for (let i = 0; i < root.dragOrder.length; ++i) m[root.dragOrder[i]] = i
        root.slotIndex = m
    }

    function moveGhost(pt) {
        ghost.x = pt.x - ghost.width / 2
        ghost.y = pt.y - ghost.height / 2
    }

    // 把被拖图标插到 slot 上，其余图标依次让位（这就是自动避让）
    function setDragSlot(slot) {
        const from = root.dragOrder.indexOf(root.dragId)
        if (from < 0 || from === slot) return
        const order = root.dragOrder.slice()
        order.splice(from, 1)
        order.splice(slot, 0, root.dragId)
        root.dragOrder = order
        root.reindexSlots()
    }

    // 让位死区：只有指针越过"被拖项当前所在格"的边界才重新排列。
    // 之前是"指针进哪个格就让位到哪"，格线附近轻微抖动就反复重排，
    // 图标一直躲闪、根本停不住，也就没法悬停形成文件夹。
    function shouldDisplace(slot) {
        // 指针下是文件夹时不让位：要让它留在原地等着接收图标。
        // macOS 也是这样——拖到文件夹上只有高亮，文件夹不会被挤走，
        // 否则"让位"会和"形成文件夹"直接冲突（文件夹老躲，永远合不上）。
        const hovered = root.dragOriginOrder[slot]
        if (hovered && AppListModel.isFolder(hovered)) return false
        const my = root.slotIndex[root.dragId]
        if (my === undefined || my < 0) return true
        // 被拖项不在当前页（拖到边缘翻过页）时直接允许让位
        if (Math.floor(my / root.perPage) !== root.currentPage) return true
        const inPage = my % root.perPage
        const myCol = inPage % root.cols
        const myRow = Math.floor(inPage / root.cols)
        const relCol = (root.dragPoint.x - pagesArea.x) / root.cellW - (myCol + 0.5)
        const relRow = (root.dragPoint.y - pagesArea.y) / root.cellH - (myRow + 0.5)
        // 越过约 0.7 格才重排（0.5 = 恰好压格线，太灵敏，图标会一直躲）
        return Math.abs(relCol) > 0.7 || Math.abs(relRow) > 0.7
    }

    function dragMove(pt) {
        root.dragPoint = pt
        root.moveGhost(pt)

        const slot = root.slotAtPoint(pt.x, pt.y)
        if (slot >= 0) {
            // 合并判定要在让位之前做：让位后这个槽位就成了被拖项自己。
            // 用拖动开始时的快照，悬停目标才不会随着让位来回跳。
            const hovered = root.dragOriginOrder[slot]
            if (hovered && hovered !== root.dragId) {
                if (root.mergeCandidate !== hovered) {
                    root.mergeCandidate = hovered
                    mergeTimer.restart()
                }
            } else if (root.mergeCandidate !== "") {
                root.mergeCandidate = ""
                mergeTimer.stop()
            }
            if (root.shouldDisplace(slot)) root.setDragSlot(slot)
        }

        // 贴左右边缘 → 连续翻页；ghost 用 root 坐标，翻页不会打断拖拽
        const m = 74
        if (pt.x < pagesArea.x + m && root.currentPage > 0) {
            if (edgeTimer.dir !== -1) { edgeTimer.dir = -1; edgeTimer.restart() }
        } else if (pt.x > pagesArea.x + pagesArea.width - m && root.currentPage < root.pageCount - 1) {
            if (edgeTimer.dir !== 1) { edgeTimer.dir = 1; edgeTimer.restart() }
        } else if (edgeTimer.dir !== 0) {
            edgeTimer.dir = 0
            edgeTimer.stop()
        }
    }

    function endDrag() {
        ghost.visible = false
        edgeTimer.dir = 0
        edgeTimer.stop()
        // 松手才提交：模型重排发生在拖动结束后，不会打断 delegate
        if (root.dragOrder.length > 0 && root.isOrderChanged())
            AppListModel.commitLayout(root.dragOrder)
        root.cancelDrag()
    }

    // 中断拖动（窗口隐藏等），不提交
    function cancelDrag() {
        root.dragActive = false
        root.dragId = ""
        root.mergeCandidate = ""
        root.dragOriginOrder = []
        root.dragOrder = []
        root.slotIndex = ({})
        ghost.visible = false
        edgeTimer.dir = 0
        edgeTimer.stop()
    }

    // ---------- 文件夹 ----------
    function openFolder(folderId) {
        if (!folderId || AppListModel.folderName(folderId) === "") return
        root.editMode = false
        folderModel.clear()
        const members = AppListModel.folderMembers(folderId)
        for (let i = 0; i < members.length; ++i) folderModel.append(members[i])
        root.folderOpen = folderId
        folderNameInput.text = AppListModel.folderName(folderId)
        // live:false 的抓取源需要显式重抓
        panelGlassSource.scheduleUpdate()
        wpBlurSource.scheduleUpdate()
    }

    function closeFolder() {
        if (root.folderOpen === "") return
        if (folderNameInput.activeFocus)
            AppListModel.renameFolder(root.folderOpen, folderNameInput.text)
        root.folderOpen = ""
        folderModel.clear()
    }

    // 面板内重排：把 fromSlot 上的成员挪到"相对偏移若干格"的位置
    function dragMemberTo(fromSlot, dCol, dRow) {
        // 面板是 3x3 一屏（flow: TopToBottom → 索引先列后行），重排限制在本页内
        const perPage = 9
        const pageFirst = Math.floor(fromSlot / perPage) * perPage
        const inPage = fromSlot % perPage
        const colFrom = Math.floor(inPage / 3)
        const rowFrom = inPage % 3
        const col = Math.max(0, Math.min(2, colFrom + dCol))
        const row = Math.max(0, Math.min(2, rowFrom + dRow))
        const to = pageFirst + col * 3 + row
        if (to === fromSlot) return fromSlot
        if (to < 0 || to >= folderModel.count) return fromSlot
        // ListModel.move 是 move(from, to, n)，n 没有默认值，必须显式给
        folderModel.move(fromSlot, to, 1)
        return to
    }

    // 面板内重排结束后提交成员顺序
    function commitMemberOrder() {
        if (root.folderOpen === "") return
        const ids = []
        for (let i = 0; i < folderModel.count; ++i) ids.push(folderModel.get(i).appId)
        AppListModel.reorderFolder(root.folderOpen, ids)
    }

    // 面板上的滚轮翻页。返回 true 表示这次滚轮被面板吃掉了。
    // 用 MouseArea 的 onWheel 而不是 WheelHandler —— 后者在这个带 layer 的面板里收不到事件。
    function wheelPagePanel(delta) {
        if (root.folderOpen === "") return false
        memberGrid.snapToPage(memberGrid.page + (delta < 0 ? 1 : -1))
        return true
    }

    // 成员被拖出后重新载入；文件夹若已被搬空并自动消失，就直接收起面板
    function refreshFolder() {
        if (root.folderOpen === "") return
        if (AppListModel.folderName(root.folderOpen) === "") { root.closeFolder(); return }
        const members = AppListModel.folderMembers(root.folderOpen)
        folderModel.clear()
        for (let i = 0; i < members.length; ++i) folderModel.append(members[i])
    }

    function exitEditMode() {
        if (root.dragActive) root.endDrag()
        root.editMode = false
    }

    onVisibleChanged: {
        if (visible) {
            AppListModel.ensureLoaded()
            AppListModel.setUiActive(true)
            wpUrl = WallpaperBackend.url()
            searchInput.text = ""
            filterText = ""
            AppListModel.filter = ""
            closeFolder()
            exitEditMode()
            currentPage = 0
            opening.stop()
            closing.stop()
            openProgress = 0
            preparationFrames = 0
            phase = "preparing"
            searchInput.forceActiveFocus()
        } else {
            opening.stop()
            closing.stop()
            openProgress = 0
            phase = "hidden"
            AppListModel.setUiActive(false)
            root.editMode = false
            root.closeFolder()
            root.cancelDrag()
            root.pageDragging = false
            pager.dragOffset = 0
        }
    }

    onFilterTextChanged: {
        currentPage = 0
        // 过滤会 reset 模型，拖动中的顺序映射会失效：就地放弃这次拖动，不提交
        if (root.dragActive) root.cancelDrag()
    }

    FrameAnimation {
        running: root.visible && root.phase === "preparing"
        onTriggered: {
            if (root.contentReady && ++root.preparationFrames >= 2) {
                root.phase = "opening"
                opening.from = root.openProgress
                opening.start()
            }
        }
    }
    NumberAnimation {
        id: opening
        target: root; property: "openProgress"; to: 1
        duration: 260; easing.type: Easing.OutCubic
        onFinished: root.phase = "open"
    }
    NumberAnimation {
        id: closing
        target: root; property: "openProgress"; to: 0
        duration: 180; easing.type: Easing.InCubic
        onFinished: root.visible = false
    }
    Item {
        id: scene
        anchors.fill: parent
        opacity: root.phase === "preparing" ? 0.001 : root.openProgress
        enabled: root.phase === "open"
        Rectangle { anchors.fill: parent; color: "#161a24" }
    // ---------- 背景：模糊壁纸 + 压暗 ----------
    Image {
        id: bgImage
        anchors.fill: parent
        source: root.wpUrl
        fillMode: Image.PreserveAspectCrop
        smooth: true
        onStatusChanged: root.imageRevision++
    }
    // 顶部/底部轻微渐变，突出中间内容
    Rectangle {
        anchors.fill: parent
        color: "transparent"
        gradient: Gradient {
            GradientStop { position: 0.0; color: Qt.rgba(0,0,0,0.28) }
            GradientStop { position: 0.35; color: "transparent" }
            GradientStop { position: 1.0; color: Qt.rgba(0,0,0,0.32) }
        }
    }

    // 最底层空白点击（页眉/页脚区域）
    MouseArea {
        anchors.fill: parent
        z: -1
        onClicked: if (!root.dragActive) root.blankClick()
    }

    // ---------- 搜索框 ----------
    Rectangle {
        id: searchBox
        width: 236; height: 34; radius: 17
        color: Qt.rgba(0, 0, 0, 0.30)
        anchors.top: parent.top
        anchors.topMargin: 26
        anchors.horizontalCenter: parent.horizontalCenter
        // 拖动时淡出，进入专注编辑态
        opacity: root.dragActive ? 0 : 1
        Behavior on opacity { NumberAnimation { duration: 180 } }

        // 放大镜
        Item {
            x: 12; y: 10; width: 14; height: 14
            Rectangle { width: 10; height: 10; radius: 5; color: "transparent"; border.color: "#c8c8c8"; border.width: 1.4 }
            Rectangle { x: 8; y: 8; width: 6; height: 1.6; radius: 1; color: "#c8c8c8"; rotation: 45 }
        }
        TextInput {
            id: searchInput
            anchors.left: parent.left; anchors.leftMargin: 34
            anchors.right: parent.right; anchors.rightMargin: 12
            anchors.verticalCenter: parent.verticalCenter
            color: "white"
            font.pixelSize: 14
            clip: true
            selectByMouse: true
            Text {
                anchors.fill: parent
                verticalAlignment: Text.AlignVCenter
                text: "搜索"
                color: Qt.rgba(1, 1, 1, 0.55)
                font.pixelSize: 14
                visible: searchInput.text === "" && !searchInput.activeFocus
            }
            onTextChanged: { root.filterText = text; AppListModel.filter = text }
            onAccepted: {
                if (AppListModel.count > 0) {
                    if (AppListModel.launch(AppListModel.idAt(0))) root.closeWindow()
                }
            }
        }
    }

    // ---------- 内容区 ----------
    Item {
        id: pagesArea
        scale: 0.97 + 0.03 * root.openProgress
        anchors.top: parent.top
        anchors.topMargin: 86
        anchors.bottom: parent.bottom
        anchors.bottomMargin: 64
        anchors.left: parent.left
        anchors.leftMargin: 60
        anchors.right: parent.right
        anchors.rightMargin: 60

        // 空白处：拖动翻页 / 点击关闭（位于图标层之下）
        MouseArea {
            anchors.fill: parent
            property real px; property real py; property bool moved
            onPressed: (m) => { px = m.x; py = m.y; moved = false }
            onPositionChanged: (m) => {
                if (root.pageDragging) {
                    root.pageDragMove(mapToItem(root.contentItem, m.x, m.y))
                    return
                }
                if (!root.dragActive && root.pageCount > 1 &&
                    (Math.abs(m.x - px) > 12 || Math.abs(m.y - py) > 12)) {
                    moved = true
                    root.pageDragBegin(mapToItem(root.contentItem, px, py))
                    root.pageDragMove(mapToItem(root.contentItem, m.x, m.y))
                }
            }
            onReleased: (m) => {
                if (root.pageDragging) root.pageDragEnd()
                else if (!moved && !root.dragActive) root.blankClick()
            }
            onCanceled: {
                moved = true
                if (root.pageDragging) { root.pageDragging = false; pager.dragOffset = 0 }
            }
        }

        // 裁剪窗口：必须是一个"自己不位移"的容器。
        // clip 裁的是相对自身几何的内容；如果让 clip 落在会平移的 pager 上，
        // 裁剪窗口就会跟着内容一起跑掉，第 2 页起的内容被自己的裁剪框裁掉
        // —— 坐标全对，却一个像素都不画（只有正好对齐的第 1 页正常）。
        Item {
            id: pagerViewport
            objectName: "pagerViewport"
            width: pagesArea.width
            height: pagesArea.height
            clip: true

            // 页容器：只负责整体平移翻页。所有图标由同一个 Repeater 渲染，
            // 位置完全由"槽位"决定，因此拖动中的图标不会被销毁（鼠标抓取不丢）。
            Item {
                id: pager
                objectName: "pager"
                width: pagesArea.width
                height: pagesArea.height
                property real dragOffset: 0
                x: -root.currentPage * width + dragOffset
                Behavior on x {
                    enabled: !root.pageDragging
                    NumberAnimation { duration: 420; easing.type: Easing.OutCubic }
                }

                Repeater {
                    id: appRepeater
                    model: AppListModel
                    onItemAdded: root.imageRevision++
                    onItemRemoved: root.imageRevision++
                    delegate: IconDelegate {}
                }
            }
        }

        // 鼠标滚轮 / 触控板滑动翻页（不拦截点击）
        MouseArea {
            anchors.fill: parent
            acceptedButtons: Qt.NoButton
            property double lastFlip: 0
            onWheel: (w) => {
                // 文件夹面板打开时，翻页属于面板，不能落到启动台上
                if (root.folderOpen !== "") return
                if (root.searching || root.dragActive || root.pageDragging) return
                const now = Date.now()
                if (now - lastFlip < 240) return
                const dx = w.angleDelta.x, dy = w.angleDelta.y
                let dir = 0
                if (Math.abs(dx) >= Math.abs(dy)) dir = dx > 0 ? -1 : 1
                else dir = dy > 0 ? -1 : 1
                if (dir < 0 && root.currentPage > 0) {
                    root.currentPage--
                    lastFlip = now
                } else if (dir > 0 && root.currentPage < root.pageCount - 1) {
                    root.currentPage++
                    lastFlip = now
                }
            }
        }

        Text {
            anchors.centerIn: parent
            visible: root.searching && AppListModel.count === 0
            text: "无结果"
            color: Qt.rgba(1, 1, 1, 0.7)
            font.pixelSize: 22
        }
    }

    // ---------- 底部圆点 ----------
    Row {
        visible: pageCount > 1
        opacity: root.dragActive ? 0 : 1
        Behavior on opacity { NumberAnimation { duration: 180 } }
        anchors.bottom: parent.bottom
        anchors.bottomMargin: 26
        anchors.horizontalCenter: parent.horizontalCenter
        spacing: 11

        Repeater {
            model: root.pageCount
            Rectangle {
                width: 8; height: 8; radius: 4
                color: "white"
                opacity: index === root.currentPage ? 0.95 : 0.32
                Behavior on opacity { NumberAnimation { duration: 220 } }
                MouseArea {
                    anchors.fill: parent
                    anchors.margins: -7
                    onClicked: root.currentPage = index
                }
            }
        }
    }

    // ---------- 拖拽跟随的"幽灵"图标 ----------
    Item {
        id: ghost
        visible: false
        width: root.cellW
        height: root.cellH
        z: 100
        opacity: 0.92
        scale: 1.12
        property string iconSource
        property string labelText

        Column {
            anchors.centerIn: parent
            spacing: 7
            Item {
                width: root.iconSize + 6; height: root.iconSize + 6
                anchors.horizontalCenter: parent.horizontalCenter
                Image {
                    anchors.fill: parent
                    source: ghost.iconSource ? "image://appicon/" + encodeURIComponent(ghost.iconSource) : ""
                    sourceSize: Qt.size(128, 128)
                    fillMode: Image.PreserveAspectFit
                    mipmap: true
                }
            }
            Text {
                text: ghost.labelText
                color: "white"
                font.pixelSize: 13
                width: root.cellW * 0.92
                horizontalAlignment: Text.AlignHCenter
                elide: Text.ElideRight
            }
        }
    }
    // 抓起时轻微放大，给一点"拿起来了"的反馈
    NumberAnimation {
        id: ghostPop
        target: ghost
        property: "scale"
        from: 1.3; to: 1.12
        duration: 220
        easing.type: Easing.OutCubic
    }

    // 边缘自动翻页计时器：按住不放就连续翻
    Timer {
        id: edgeTimer
        interval: 420
        repeat: true
        property int dir: 0
        onTriggered: {
            if (dir < 0 && root.currentPage > 0) root.currentPage--
            else if (dir > 0 && root.currentPage < root.pageCount - 1) root.currentPage++
            else { dir = 0; return }
            // 翻页后指针落在新页的槽位上，重算插入位置
            if (root.dragActive) {
                const s = root.slotAtPoint(root.dragPoint.x, root.dragPoint.y)
                if (s >= 0) root.setDragSlot(s)
            }
        }
    }

    // Esc：抖动态先退出编辑态，有搜索先清空，否则关闭
    Shortcut {
        sequence: "Escape"
        onActivated: {
            if (root.folderOpen !== "") root.closeFolder()
            else if (root.editMode) root.exitEditMode()
            else if (root.filterText !== "") searchInput.text = ""
            else root.closeWindow()
        }
    }

    // ---------- 文件夹展开面板 ----------
    ListModel { id: folderModel }

    Item {
        id: folderPopup
        anchors.fill: parent
        z: 200
        visible: root.folderOpen !== ""

        // 抓一份主网格图标的渲染，作为面板毛玻璃的来源
        ShaderEffectSource {
            id: panelGlassSource
            sourceItem: pagesArea
            live: false                 // 面板弹出时抓一次即可
            recursive: false
            hideSource: false
            visible: false
        }

        // 遮罩：点外部收起
        Rectangle {
            anchors.fill: parent
            color: Qt.rgba(0, 0, 0, 0.32)
            MouseArea {
                anchors.fill: parent
                onClicked: root.closeFolder()
            }
        }

        // 文件夹名在卡片上方（macOS 的样式）
        TextInput {
            id: folderNameInput
            objectName: "folderNameInput"
            anchors.bottom: folderPanel.top
            anchors.bottomMargin: 16
            anchors.horizontalCenter: folderPanel.horizontalCenter
            width: Math.min(folderPanel.width * 0.7, 380)
            horizontalAlignment: Text.AlignHCenter
            color: "white"
            font.pixelSize: 22
            font.bold: true
            selectByMouse: true
            selectionColor: Qt.rgba(0.3, 0.55, 1.0, 0.6)

            Rectangle {
                anchors.fill: parent
                anchors.margins: -8
                radius: 8
                color: Qt.rgba(1, 1, 1, 0.16)
                visible: folderNameInput.activeFocus
                z: -1
            }

            onEditingFinished: AppListModel.renameFolder(root.folderOpen, text)
            Keys.onEscapePressed: (e) => {
                text = AppListModel.folderName(root.folderOpen)
                folderNameInput.focus = false
                e.accepted = true
            }
        }

        Item {
            id: folderPanel
            anchors.centerIn: parent
            width: Math.min(root.width * 0.66, 760)
            height: Math.min(root.height * 0.66, 600)

            // Item 的 clip 只按矩形，做不出圆角；用 layer + mask 把整块面板裁圆
            layer.enabled: true
            layer.effect: MultiEffect {
                maskEnabled: true
                maskSource: panelMask
            }

            // 卡片底 = 背后那块桌面（壁纸 + 图标）重度高斯模糊后压暗，就是磨砂玻璃
            ShaderEffectSource {
                id: wpBlurSource
                sourceItem: bgImage
                live: false
                recursive: false
                hideSource: false
                visible: false
            }
            MultiEffect {
                x: -folderPanel.x
                y: -folderPanel.y
                width: root.width
                height: root.height
                source: wpBlurSource
                blurEnabled: true
                blur: 1.0
                blurMax: 64
                autoPaddingEnabled: false
            }
            MultiEffect {
                x: pagesArea.x - folderPanel.x
                y: pagesArea.y - folderPanel.y
                width: pagesArea.width
                height: pagesArea.height
                source: panelGlassSource
                blurEnabled: true
                blur: 1.0
                blurMax: 64
                autoPaddingEnabled: false
            }
            Rectangle {
                anchors.fill: parent
                color: Qt.rgba(0, 0, 0, 0.42)          // 压暗
            }
            Rectangle {
                anchors.fill: parent
                radius: 28
                color: "transparent"
                border.color: Qt.rgba(1, 1, 1, 0.35)
                border.width: 1
            }

            // 吃掉点击，别穿透到遮罩
            MouseArea { anchors.fill: parent }

            GridView {
                id: memberGrid
                objectName: "memberGrid"
                anchors.top: parent.top
                anchors.topMargin: 30
                anchors.left: parent.left
                anchors.leftMargin: 28
                anchors.right: parent.right
                anchors.rightMargin: 28
                anchors.bottom: memberDots.top
                anchors.bottomMargin: 10

                // macOS 文件夹的标准形态：一屏 3x3，超出的部分左右翻页
                flow: GridView.TopToBottom        // 先竖着填满一列，再往右下一列
                // 3x3 正好铺满视口（用宽/高各除以 3，避免因取小值而在右侧留白）
                cellWidth: Math.floor(width / 3)
                cellHeight: Math.floor(height / 3)
                model: folderModel
                clip: true
                boundsBehavior: Flickable.StopAtBounds
                flickableDirection: Flickable.HorizontalFlick
                maximumFlickVelocity: 2000

                readonly property real pageWidth: cellWidth * 3
                readonly property int pageCount:
                    pageWidth > 0 ? Math.max(1, Math.ceil(count / 9)) : 1
                // 内容宽度只由项数决定（每列 3 个），最后一页往往不满一屏，
                // 所以"滚到底"必须算作最后一页，否则永远停在 0。
                readonly property int page: {
                    if (pageWidth <= 0) return 0
                    const maxS = Math.max(0, contentWidth - width)
                    if (maxS <= 1) return 0
                    if (contentX >= maxS - 1) return pageCount - 1
                    return Math.max(0, Math.min(pageCount - 1,
                                   Math.round(contentX / pageWidth)))
                }

                // 松手后吸附到整屏（GridView 没有"一屏"粒度的 snapMode）
                function snapToPage(p) {
                    const maxX = Math.max(0, contentWidth - width)
                    const target = Math.max(0, Math.min(maxX, p * pageWidth))
                    if (Math.abs(contentX - target) < 1) return
                    snapAnim.to = target
                    snapAnim.restart()
                }
                onMovementStarted: snapAnim.stop()
                onMovementEnded: snapToPage(page)
                // 成员换位时的让位动画
                move: Transition {
                    NumberAnimation { properties: "x,y"; duration: 200; easing.type: Easing.OutCubic }
                }
                moveDisplaced: Transition {
                    NumberAnimation { properties: "x,y"; duration: 200; easing.type: Easing.OutCubic }
                }

                delegate: Item {
                    width: memberGrid.cellWidth
                    height: memberGrid.cellHeight

                    Column {
                        anchors.centerIn: parent
                        spacing: 6
                        opacity: memberMA.reordering ? 0.5 : 1
                        Behavior on opacity { NumberAnimation { duration: 120 } }
                        Item {
                            width: Math.min(root.iconSize * 0.86, memberGrid.cellWidth * 0.6)
                            height: width
                            anchors.horizontalCenter: parent.horizontalCenter
                            Image {
                                anchors.fill: parent
                                source: "image://appicon/" + encodeURIComponent(model.appIcon)
                                sourceSize: Qt.size(192, 192)
                                fillMode: Image.PreserveAspectFit
                                mipmap: true
                                smooth: true
                                asynchronous: false
                                onStatusChanged: root.imageRevision++
                            }
                        }
                        Text {
                            text: model.appName
                            color: "white"
                            font.pixelSize: 12
                            width: memberGrid.cellWidth * 0.86
                            horizontalAlignment: Text.AlignHCenter
                            elide: Text.ElideRight
                            maximumLineCount: 2
                            wrapMode: Text.WordWrap
                            style: Text.Outline
                            styleColor: Qt.rgba(0, 0, 0, 0.55)
                        }
                    }

                    // 面板内拖动 = 重排；拖到面板外松手 = 从文件夹里移出
                    MouseArea {
                        id: memberMA
                        anchors.fill: parent
                        acceptedButtons: Qt.LeftButton
                        // 长按后才阻止 GridView 抢事件；短按的水平滑动留给翻页
                        pressAndHoldInterval: 200
                        preventStealing: memberMA.reordering
                        property bool out: false          // 指针在面板外
                        property bool pressMoved: false
                        property bool canReorder: false   // 长按过
                        property bool reordering: false
                        property real px; property real py
                        property int dragFrom: index

                        function panelContains(pt) {
                            const tl = folderPanel.mapToItem(root.contentItem, 0, 0)
                            return pt.x >= tl.x && pt.x <= tl.x + folderPanel.width &&
                                   pt.y >= tl.y && pt.y <= tl.y + folderPanel.height
                        }
                        onPressed: (m) => {
                            px = m.x; py = m.y
                            out = false; pressMoved = false
                            canReorder = false; reordering = false
                            dragFrom = index
                        }
                        onPressAndHold: (m) => { canReorder = true }
                        onPositionChanged: (m) => {
                            if (Math.abs(m.x - px) > 8 || Math.abs(m.y - py) > 8) pressMoved = true
                            const p = mapToItem(root.contentItem, m.x, m.y)
                            out = !panelContains(p)
                            if (canReorder && pressMoved && !out) reordering = true
                            if (reordering && !out) {
                                // m.x/m.y 是相对本格的偏移，直接折算成"偏了几格"。
                                // 不做任何跨对象坐标映射，也不用在嵌套作用域里碰 ListModel。
                                const dCol = Math.floor(m.x / memberGrid.cellWidth)
                                const dRow = Math.floor(m.y / memberGrid.cellHeight)
                                dragFrom = root.dragMemberTo(dragFrom, dCol, dRow)
                            }
                        }
                        onReleased: {
                            if (out && canReorder) {          // 只有长按拖动才算"移出文件夹"
                                AppListModel.takeFromFolder(root.folderOpen, model.appId)
                                root.refreshFolder()
                            } else if (reordering) {
                                root.commitMemberOrder()
                            } else if (!pressMoved) {
                                if (AppListModel.launch(model.appId)) root.closeWindow()
                            }
                        }
                        onCanceled: { out = false; reordering = false; canReorder = false }
                    }
                }
            }

            PropertyAnimation {
                id: snapAnim
                target: memberGrid
                property: "contentX"
                duration: 280
                easing.type: Easing.OutCubic
            }

            Row {
                id: memberDots
                visible: memberGrid.pageCount > 1
                anchors.bottom: parent.bottom
                anchors.bottomMargin: 16
                anchors.horizontalCenter: parent.horizontalCenter
                spacing: 10
                Repeater {
                    model: memberGrid.pageCount
                    Rectangle {
                        width: 7; height: 7; radius: 3.5
                        color: "white"
                        opacity: index === memberGrid.page ? 0.95 : 0.3
                        Behavior on opacity { NumberAnimation { duration: 200 } }
                        MouseArea {
                            anchors.fill: parent
                            anchors.margins: -6
                            onClicked: memberGrid.snapToPage(index)
                        }
                    }
                }
            }

            Text {
                anchors.centerIn: parent
                visible: folderModel.count === 0
                text: "空文件夹"
                color: Qt.rgba(1, 1, 1, 0.55)
                font.pixelSize: 16
            }
        }

        // 面板打开时，任何位置的滚轮都翻文件夹的页（不吃鼠标按键，只吃滚轮）
        MouseArea {
            anchors.fill: parent
            acceptedButtons: Qt.NoButton
            onWheel: (w) => {
                const d = Math.abs(w.angleDelta.x) > Math.abs(w.angleDelta.y)
                          ? w.angleDelta.x : w.angleDelta.y
                root.wheelPagePanel(d)
            }
        }

        // 面板的圆角遮罩（仅供 folderPanel 的 layer.effect 使用）
        Item {
            id: panelMask
            anchors.fill: folderPanel
            visible: false
            layer.enabled: true
            Rectangle {
                anchors.fill: parent
                radius: 28
                color: "white"
            }
        }
    }

    // 悬停在别的图标上一段时间 → 合并成文件夹 / 加入已有文件夹
    Timer {
        id: mergeTimer
        interval: 820
        onTriggered: {
            if (!root.dragActive || root.mergeCandidate === "" || root.dragId === "") return
            const dragged = root.dragId
            const target = root.mergeCandidate
            root.cancelDrag()                 // 先收尾：合并会让模型整体 reset
            AppListModel.mergeInto(dragged, target)
        }
    }

    // ---------- 图标组件 ----------
    component IconDelegate: Item {
        id: iconRoot
        width: root.cellW
        height: root.cellH

        readonly property int appRow: index
        readonly property int slot: root.slotOfRow(appRow)
        readonly property bool dragged: root.dragActive && model.appId === root.dragId
        readonly property int slotPage: slot < 0 ? -1 : Math.floor(slot / root.perPage)
        // 在 delegate 顶层就把文件夹相关角色取出来：
        // 嵌套 Repeater 会遮蔽 `model`，在那里面再写 model.folderIcons 会取到 undefined
        readonly property bool isFolder: model.isFolder
        readonly property var folderIconList: model.isFolder ? model.folderIcons : []
        readonly property bool iconReady: {
            const revision = root.imageRevision
            if (!isFolder) return appImage.status === Image.Ready || appImage.status === Image.Error
            for (let i = 0; i < folderIconRepeater.count; ++i) {
                const image = folderIconRepeater.itemAt(i)
                if (!image || image.status === Image.Loading) return false
            }
            return true
        }

        // 位置全由槽位决定；跨页的部分靠 pager 的 clip 裁掉。
        // 不要再引入"按页裁剪 visible / Image.source"这类绑定：
        // 它们要重复读 slot 派生属性，会被 QML 的循环检测静默禁用，
        // 结果就是翻过去的页面整片空白。所有 delegate 一律常驻可见，
        // 被拖的那个也不会因为 visible 翻转而丢掉鼠标抓取。
        // 槽位无效（模型在拖动中被换掉）时挪到裁剪区外，而不是堆在左上角。
        x: slot < 0 ? -pager.width : (slot % root.cols) * root.cellW + slotPage * pager.width
        y: slot < 0 ? 0 : Math.floor((slot % root.perPage) / root.cols) * root.cellH
        // 被拖的图标由 ghost 代表，原位留空（但不隐藏、不销毁，保住事件抓取）
        opacity: dragged ? 0 : 1

        // 让位 / 归位动画
        Behavior on x {
            enabled: !iconRoot.dragged && !root.searching
            NumberAnimation { duration: 260; easing.type: Easing.OutCubic }
        }
        Behavior on y {
            enabled: !iconRoot.dragged && !root.searching
            NumberAnimation { duration: 260; easing.type: Easing.OutCubic }
        }
        Behavior on opacity { NumberAnimation { duration: 150 } }
        // 悬停成为合并目标时轻微放大，给一个"要合进去了"的反馈
        scale: (root.dragActive && model.appId === root.mergeCandidate) ? 1.14 : 1
        Behavior on scale { NumberAnimation { duration: 160; easing.type: Easing.OutCubic } }

        Column {
            id: content
            anchors.centerIn: parent
            spacing: 7
            rotation: 0
            transformOrigin: Item.Center

            Item {
                width: root.iconSize
                height: root.iconSize
                anchors.horizontalCenter: parent.horizontalCenter

                // 普通应用
                Image {
                    id: appImage
                    anchors.fill: parent
                    visible: !iconRoot.isFolder
                    // 全量加载（105 个应用约 4MB 纹理）；不要按页懒加载，
                    // 理由见上面 IconDelegate 的注释
                    source: !iconRoot.isFolder
                            ? "image://appicon/" + encodeURIComponent(model.appIcon) : ""
                    sourceSize: Qt.size(192, 192)
                    fillMode: Image.PreserveAspectFit
                    mipmap: true
                    smooth: true
                    asynchronous: false
                                onStatusChanged: root.imageRevision++
                }

                // 文件夹：圆角背板 + 最多 3x3 的成员缩略图
                Item {
                    anchors.fill: parent
                    visible: iconRoot.isFolder

                    Rectangle {
                        anchors.fill: parent
                        radius: width * 0.26
                        // 浅色毛玻璃背板：比之前的 18% 白更亮更实，
                        // 否则在深色壁纸上会糊成一块灰
                        color: Qt.rgba(0.93, 0.93, 0.96, 0.52)
                        border.color: Qt.rgba(1, 1, 1, 0.45)
                        border.width: 1
                    }
                    Grid {
                        id: folderIconGrid
                        anchors.fill: parent
                        anchors.margins: Math.round(parent.width * 0.10)
                        columns: 3
                        spacing: Math.round(parent.width * 0.032)
                        readonly property real cellSize: (width - 2 * spacing) / 3
                        Repeater {
                            id: folderIconRepeater
                            model: iconRoot.folderIconList
                            Image {
                                width: folderIconGrid.cellSize
                                height: folderIconGrid.cellSize
                                source: "image://appicon/" + encodeURIComponent(modelData)
                                sourceSize: Qt.size(64, 64)
                                fillMode: Image.PreserveAspectFit
                                smooth: true
                                asynchronous: false
                                onStatusChanged: root.imageRevision++
                            }
                        }
                    }
                }
            }
            Text {
                text: model.appName
                color: "white"
                font.pixelSize: 13
                width: root.cellW * 0.94
                horizontalAlignment: Text.AlignHCenter
                elide: Text.ElideRight
                wrapMode: Text.WordWrap
                maximumLineCount: 2
                style: Text.Outline
                styleColor: Qt.rgba(0, 0, 0, 0.55)
            }
        }

        // 抖动（macOS 编辑态）。
        // 注意：running 不能引用任何由 slot 派生的属性（onStage/slotPage 等）——
        // 动画启停会引发 polish 重入，被 QML 判为 slot 的绑定循环并禁用该绑定。
        SequentialAnimation {
            running: root.editMode && !dragged && !root.searching
            loops: Animation.Infinite
            NumberAnimation { target: content; property: "rotation"; to: -1.2; duration: 130; easing.type: Easing.InOutSine }
            NumberAnimation { target: content; property: "rotation"; to: 1.2; duration: 260; easing.type: Easing.InOutSine }
            NumberAnimation { target: content; property: "rotation"; to: 0; duration: 130; easing.type: Easing.InOutSine }
            PauseAnimation { duration: 420 + (iconRoot.appRow % 7) * 130 }
        }
        Connections {
            target: root
            function onEditModeChanged() {
                if (!root.editMode) content.rotation = 0
            }
        }

        MouseArea {
            id: iconMA
            anchors.fill: parent
            acceptedButtons: Qt.LeftButton
            hoverEnabled: false
            pressAndHoldInterval: 200
            preventStealing: iconMA.held   // 按住进入拖拽后，阻止翻页手势抢夺事件

            property bool held: false
            property bool moved: false
            property real pressX; property real pressY

            onPressed: (m) => {
                pressX = m.x; pressY = m.y; moved = false
                if (root.dragActive) return
            }
            onPositionChanged: (m) => {
                const pt = mapToItem(root.contentItem, m.x, m.y)
                if (held) {                       // 已经在拖图标
                    root.dragMove(pt)
                    return
                }
                if (root.pageDragging) {           // 已经在翻页
                    root.pageDragMove(pt)
                    return
                }
                const dx = m.x - pressX, dy = m.y - pressY
                if (!moved && (Math.abs(dx) > 6 || Math.abs(dy) > 6)) moved = true
                // 在图标上横向滑动 = 翻页（不必去找空白处）
                if (!root.dragActive && !root.searching && root.pageCount > 1 &&
                    Math.abs(dx) > 12 && Math.abs(dx) > Math.abs(dy) * 1.2) {
                    root.pageDragBegin(mapToItem(root.contentItem, pressX, pressY))
                    root.pageDragMove(pt)
                }
            }
            onPressAndHold: (m) => {
                if (root.dragActive || root.searching) return
                held = true
                root.editMode = true
                root.beginDrag(model.appId, model.appIcon, model.appName,
                               mapToItem(root.contentItem, m.x, m.y))
            }
            onReleased: {
                if (held) {
                    held = false
                    root.endDrag()
                } else if (root.pageDragging) {
                    root.pageDragEnd()
                } else if (!moved && !root.dragActive) {
                    if (model.isFolder) {
                        root.openFolder(model.appId)
                    } else {
                        if (AppListModel.launch(model.appId)) root.closeWindow()
                    }
                }
            }
            onCanceled: {
                if (held) { held = false; root.endDrag() }
                else if (root.pageDragging) { root.pageDragging = false; pager.dragOffset = 0 }
            }
        }
    }
    }
}
