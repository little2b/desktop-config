/*
 * 启动台回归测试（offscreen，无需显示器）
 *
 *   cmake -S . -B build -DBUILD_TESTING=ON && cmake --build build -j && ctest --test-dir build -V
 *
 * 用真实的 AppModel（src/appmodel.h）驱动真实的 qml/Main.qml，只把
 * AppListModel 换成真实模型、WallpaperBackend 换成极简桩。
 * 配置目录与应用目录都隔离到临时路径，不会碰用户真实数据。
 *
 * 覆盖：点击/拖拽重排/跨页拖动/手势翻页/翻页可见性/clip 容器/抖动编辑态，
 *       以及文件夹的合并、展开、重命名、拖出成员、搜索命中、持久化与旧 order 迁移。
 */
#include "appmodel.h"

#include <QtQuick>
#include <QQuickWindow>
#include <QTest>
#include <QDir>
#include <QEventLoop>
#include <QFile>
#include <QSettings>
#include <QTimer>
#include <QDebug>
#include <cmath>
#include <functional>
#include <unistd.h>

static const qreal pagesX = 60, pagesY = 86;   // Main.qml 里 pagesArea 的固定边距
static const int PER_PAGE = 35;
static const int APP_COUNT = 105;              // 3 页整

static QString g_tmpRoot;

static QString appId(int i) { return QString("app%1").arg(i, 3, 10, QChar('0')); }

static void writeFakeApps(const QString &dir, int n) {
    QDir().mkpath(dir);
    for (int i = 0; i < n; ++i) {
        QFile f(dir + "/" + appId(i) + ".desktop");
        if (!f.open(QIODevice::WriteOnly)) continue;
        f.write(QString("[Desktop Entry]\nType=Application\nName=App%1\n"
                        "Icon=icon%1\nExec=/bin/true\n")
                    .arg(i, 3, 10, QChar('0')).toUtf8());
    }
}

class WallpaperStub : public QObject {
    Q_OBJECT
    Q_PROPERTY(bool prepared READ prepared CONSTANT)
public:
    bool prepared() const { return true; }
    Q_INVOKABLE QString url() const { return QString(); }
signals:
    void ready();
};

class FlatIconProvider : public QQuickImageProvider {
public:
    FlatIconProvider() : QQuickImageProvider(QQuickImageProvider::Pixmap) {}
    QPixmap requestPixmap(const QString &, QSize *size, const QSize &req) override {
        const int px = req.isValid() ? req.width() : 64;
        QPixmap pm(px, px);
        pm.fill(Qt::darkYellow);
        if (size) *size = pm.size();
        return pm;
    }
};

class DragTest : public QObject {
    Q_OBJECT
public:
    QQmlEngine *engine = nullptr;
    AppModel *model = nullptr;
    QObject *main = nullptr;
    QQuickWindow *win = nullptr;
    qreal cellW = 0, cellH = 0;

    static void wait(int ms) {
        QEventLoop loop;
        QTimer::singleShot(ms, &loop, &QEventLoop::quit);
        loop.exec();
    }
    QPoint cellCenter(int slot) const {
        const int idx = slot % PER_PAGE;
        const qreal x = pagesX + ((idx % 7) + 0.5) * cellW;
        const qreal y = pagesY + (std::floor(idx / 7.0) + 0.5) * cellH;
        return QPoint(qRound(x), qRound(y));
    }
    void pressHold(const QPoint &p) {
        QTest::mousePress(win, Qt::LeftButton, Qt::NoModifier, p);
        // 等 pressAndHold 真正生效：固定睡眠在初始化繁忙时会漏掉长按
        for (int i = 0; i < 80 && !main->property("dragActive").toBool(); ++i)
            wait(20);
        wait(30);
    }
    void moveTo(const QPoint &p) { QTest::mouseMove(win, p); wait(60); }
    void drop(const QPoint &p) {
        QTest::mouseRelease(win, Qt::LeftButton, Qt::NoModifier, p);
        wait(280);
    }
    void click(const QPoint &p) {
        QTest::mousePress(win, Qt::LeftButton, Qt::NoModifier, p);
        QTest::mouseRelease(win, Qt::LeftButton, Qt::NoModifier, p);
        wait(300);
    }
    QStringList memberIds(const QString &fid) const {
        QStringList out;
        for (const QVariant &v : model->folderMembers(fid))
            out << v.toMap().value("appId").toString();
        return out;
    }

    bool folderAt(int row) const {
        return model->index(row, 0).data(AppModel::IsFolderRole).toBool();
    }
    int folderCount(int row) const {
        return model->index(row, 0).data(AppModel::FolderCountRole).toInt();
    }

private slots:
    void initTestCase() {
        QVERIFY2(launchpadConfigDir().startsWith(g_tmpRoot),
                 qPrintable("配置目录没有隔离到临时路径: " + launchpadConfigDir()));
        qInfo() << "隔离配置目录:" << launchpadConfigDir();
    }

    void init() {
        // 每个用例都从干净的布局开始（配置目录是隔离的，删掉即可）
        QFile::remove(launchpadConfigDir() + "/settings.conf");
        QFile::remove(launchpadConfigDir() + "/launchpad.json");
        engine = new QQmlEngine;
        model = new AppModel;
        model->setSearchDirs({g_tmpRoot + "/apps"});
        engine->addImageProvider("appicon", new FlatIconProvider);
        engine->rootContext()->setContextProperty("AppListModel", model);
        engine->rootContext()->setContextProperty("WallpaperBackend", new WallpaperStub);

        QQmlComponent comp(engine, QUrl::fromLocalFile(QMLPATH));
        main = comp.create();
        QVERIFY2(main, qPrintable(comp.errorString()));
        win = qobject_cast<QQuickWindow *>(main);
        QVERIFY(win);
        win->showFullScreen();
        wait(900);
        cellW = main->property("cellW").toReal();
        cellH = main->property("cellH").toReal();
        QVERIFY(cellW > 10 && cellH > 10);
        QCOMPARE(model->count(), APP_COUNT);
        QCOMPARE(main->property("pageCount").toInt(), 3);   // 105 / 35
    }

    void cleanup() {
        delete main;
        delete model;
        delete engine;
        main = nullptr; win = nullptr; model = nullptr; engine = nullptr;
    }

    // ---------------- 基础交互 ----------------

    void t01_clickLaunchesAndCloses() {
        QVERIFY(win->isVisible());
        click(cellCenter(0));               // 点应用图标 → 启动并关窗
        QVERIFY2(!win->isVisible(), "点击应用后窗口应关闭");
        win->showFullScreen();
        wait(400);
    }

    void t02_dragWithinPage() {
        pressHold(cellCenter(0));
        QVERIFY2(main->property("dragActive").toBool(), "长按未进入拖拽态");
        QVERIFY2(main->property("editMode").toBool(), "长按未进入抖动编辑态");
        moveTo(cellCenter(3));
        drop(cellCenter(3));
        QCOMPARE(model->idAt(0), appId(1));
        QCOMPARE(model->idAt(1), appId(2));
        QCOMPARE(model->idAt(2), appId(3));
        QCOMPARE(model->idAt(3), appId(0));   // 插到了槽位 3
        QCOMPARE(model->idAt(4), appId(4));
        QVERIFY(!main->property("dragActive").toBool());
    }

    void t03_dragAcrossPageViaEdge() {
        const qreal areaW = win->width() - 2 * pagesX;
        const QPoint edge(qRound(pagesX + areaW - 12), qRound(pagesY + cellH * 0.5));

        pressHold(cellCenter(0));
        QVERIFY(main->property("dragActive").toBool());
        moveTo(edge);
        QTRY_VERIFY_WITH_TIMEOUT(main->property("currentPage").toInt() == 1, 4000);
        QVERIFY2(main->property("dragActive").toBool(), "翻页把拖拽打断了");
        moveTo(edge);
        drop(edge);

        QCOMPARE(model->idAt(0), appId(1));
        QCOMPARE(model->idAt(PER_PAGE + 6), appId(0));   // 页 2 第 7 列
    }

    void t13_reorderFolderMembers() {
        model->ensureLoaded();
        QVERIFY(model->mergeInto(appId(0), appId(1)));     // [app000, app001]
        const QString fid = model->idAt(0);
        QCOMPARE(memberIds(fid), (QStringList{appId(0), appId(1)}));

        QVariantList rev;
        rev << appId(1) << appId(0);
        QVERIFY(model->reorderFolder(fid, rev));
        QCOMPARE(memberIds(fid), (QStringList{appId(1), appId(0)}));

        // 持久化：新实例读出来仍是新顺序
        AppModel reloaded;
        reloaded.setSearchDirs({g_tmpRoot + "/apps"});
        reloaded.ensureLoaded();
        QStringList after;
        for (const QVariant &v : reloaded.folderMembers(fid))
            after << v.toMap().value("appId").toString();
        QCOMPARE(after, (QStringList{appId(1), appId(0)}));

        // 成员对不上的输入必须被拒绝，不能写坏布局
        QVariantList bogus;
        bogus << appId(0) << appId(50);
        QVERIFY(!model->reorderFolder(fid, bogus));
        QCOMPARE(memberIds(fid), (QStringList{appId(1), appId(0)}));
        QVariantList shorter;
        shorter << appId(0);
        QVERIFY(!model->reorderFolder(fid, shorter));
        QCOMPARE(memberIds(fid), (QStringList{appId(1), appId(0)}));
    }

    void t14_dragReorderInPanel() {
        model->ensureLoaded();
        QVERIFY(model->mergeInto(appId(0), appId(1)));
        const QString fid = model->idAt(0);
        QVERIFY(model->mergeInto(appId(2), fid));
        QVERIFY(model->mergeInto(appId(3), fid));
        const QStringList before = memberIds(fid);
        QCOMPARE(before.size(), 4);

        click(cellCenter(0));                      // 点文件夹图标打开面板
        QCOMPARE(main->property("folderOpen").toString(), fid);

        QQuickItem *grid = win->findChild<QQuickItem *>("memberGrid");
        QVERIFY2(grid, "找不到 memberGrid");
        const qreal cw = grid->property("cellWidth").toReal();
        QVERIFY(cw > 10);
        // 面板刚打开、未滚动，所以视口坐标即内容坐标
        const QPoint p0 = grid->mapToScene(QPointF(cw * 0.5, cw * 0.5)).toPoint();
        const QPoint p1 = grid->mapToScene(QPointF(cw * 1.6, cw * 0.5)).toPoint();

        QTest::mousePress(win, Qt::LeftButton, Qt::NoModifier, p0);
        wait(300);                     // 长按：短按滑动是翻页，长按才是重排
        QTest::mouseMove(win, p1);
        wait(140);
        QTest::mouseRelease(win, Qt::LeftButton, Qt::NoModifier, p1);
        wait(450);

        const QStringList after = memberIds(fid);
        QCOMPARE(after.size(), before.size());
        QVERIFY2(after != before, "面板内拖动没有改变成员顺序");
        // 3x3 布局（flow: TopToBottom）下把首格拖到右边一列，
        // 首格成员落到索引 3（右列首格），原来的后三项各往前挪一格
        QCOMPARE(after.at(0), before.at(1));
        QCOMPARE(after.at(1), before.at(2));
        QCOMPARE(after.at(3), before.at(0));
    }

    void t15_folderPanelPaginates() {
        // 面板应是 3x3 一屏、超出翻页（macOS 文件夹的标准形态）
        model->ensureLoaded();
        QVERIFY(model->mergeInto(appId(0), appId(1)));
        const QString fid = model->idAt(0);
        for (int i = 2; i < 12; ++i)
            QVERIFY(model->mergeInto(appId(i), fid));
        QCOMPARE(model->folderMembers(fid).size(), 12);

        click(cellCenter(0));
        QCOMPARE(main->property("folderOpen").toString(), fid);

        QQuickItem *grid = win->findChild<QQuickItem *>("memberGrid");
        QVERIFY2(grid, "找不到 memberGrid");
        QCOMPARE(grid->property("pageCount").toInt(), 2);      // 12 个 → 每页 9 个
        QCOMPARE(grid->property("page").toInt(), 0);

        const qreal pageW = grid->property("pageWidth").toReal();
        QVERIFY(pageW > 10);
        grid->setProperty("contentX", pageW);                  // 翻到第 2 页
        wait(500);
        QCOMPARE(grid->property("page").toInt(), 1);

        grid->setProperty("contentX", 0.0);                    // 翻回第 1 页
        wait(500);
        QCOMPARE(grid->property("page").toInt(), 0);
    }

    void t16_folderDoesNotDisplace() {
        // 让位与"形成文件夹"是天生冲突的：如果文件夹跟着指针让位，
        // 就永远悬停不住、也合不成。macOS 里拖到文件夹上文件夹是原地不动的。
        model->ensureLoaded();
        QVERIFY(model->mergeInto(appId(0), appId(1)));        // 槽位 0 → 文件夹
        const QString fid = model->idAt(0);
        QVERIFY(folderAt(0));

        pressHold(cellCenter(2));
        QVERIFY(main->property("dragActive").toBool());
        moveTo(cellCenter(0));
        moveTo(cellCenter(0) + QPoint(4, 0));                 // 再挪一下，确保让位判定跑过
        wait(200);
        QVERIFY2(model->idAt(0) == fid, "文件夹被挤走了：让位和合并的逻辑冲突");
        QVERIFY2(folderAt(0), "槽位 0 已经不是文件夹了");

        // 悬停够久 → 应当合并进去
        QTRY_VERIFY_WITH_TIMEOUT(!main->property("dragActive").toBool(), 3000);
        QCOMPARE(folderCount(0), 3);
    }

    void t17_panelPagingDoesNotLeakToApp() {
        // 核心诉求：面板打开时，翻页必须作用于文件夹，不能把启动台翻走
        model->ensureLoaded();
        QVERIFY(model->mergeInto(appId(0), appId(1)));
        const QString fid = model->idAt(0);
        for (int i = 2; i < 12; ++i)
            QVERIFY(model->mergeInto(appId(i), fid));

        click(cellCenter(0));
        QCOMPARE(main->property("folderOpen").toString(), fid);
        QQuickItem *grid = win->findChild<QQuickItem *>("memberGrid");
        QVERIFY2(grid, "找不到 memberGrid");
        QCOMPARE(grid->property("pageCount").toInt(), 2);

        const int appPageBefore = main->property("currentPage").toInt();
        const qreal cw = grid->property("cellWidth").toReal();

        // 1) 在面板上滑动：绝不能把启动台翻走，面板也不能被关掉
        const QPoint from = grid->mapToScene(QPointF(cw * 2.0, cw * 1.5)).toPoint();
        const QPoint to = grid->mapToScene(QPointF(cw * 0.2, cw * 1.5)).toPoint();
        QTest::mousePress(win, Qt::LeftButton, Qt::NoModifier, from);
        QTest::mouseMove(win, from - QPoint(qRound(cw * 0.4), 0));
        QTest::mouseMove(win, to);
        QTest::mouseRelease(win, Qt::LeftButton, Qt::NoModifier, to);
        wait(600);
        QCOMPARE(main->property("currentPage").toInt(), appPageBefore);
        QCOMPARE(main->property("folderOpen").toString(), fid);

        // 注：滚轮翻面板由 Main.qml 的 WheelHandler 负责，但合成滚轮事件在
        // offscreen 下走不到 QML handler，没法在这里断言；面板翻页能力由
        // t15_folderPanelPaginates 覆盖。
    }

    void t18_panelWheelFlipsFolder() {
        // 滚轮要翻文件夹的页。事件链路（MouseArea.onWheel）没法在 offscreen 合成，
        // 这里直接验证它调用的那段逻辑；链路本身由 Main.qml 里与主网格相同的
        // MouseArea.onWheel 写法保证。
        model->ensureLoaded();
        QVERIFY(model->mergeInto(appId(0), appId(1)));
        const QString fid = model->idAt(0);
        for (int i = 2; i < 12; ++i)
            QVERIFY(model->mergeInto(appId(i), fid));

        click(cellCenter(0));
        QCOMPARE(main->property("folderOpen").toString(), fid);
        QQuickItem *grid = win->findChild<QQuickItem *>("memberGrid");
        QVERIFY(grid);
        QCOMPARE(grid->property("pageCount").toInt(), 2);
        QCOMPARE(grid->property("page").toInt(), 0);
        const int appPageBefore = main->property("currentPage").toInt();

        // 向下滚 → 下一页
        QVERIFY(QMetaObject::invokeMethod(main, "wheelPagePanel", Q_ARG(QVariant, -120)));
        wait(500);
        QCOMPARE(grid->property("page").toInt(), 1);
        // 向上滚 → 上一页
        QVERIFY(QMetaObject::invokeMethod(main, "wheelPagePanel", Q_ARG(QVariant, 120)));
        wait(500);
        QCOMPARE(grid->property("page").toInt(), 0);
        // 全程不能波及启动台
        QCOMPARE(main->property("currentPage").toInt(), appPageBefore);

        // 面板关掉后，这个入口不该再吃滚轮
        main->setProperty("folderOpen", QString());
        wait(200);
        QMetaObject::invokeMethod(main, "wheelPagePanel", Q_ARG(QVariant, -120));
        QCOMPARE(grid->property("page").toInt(), 0);
    }

    void t04_editModeAndBlankClick() {
        pressHold(cellCenter(0));
        QVERIFY(main->property("dragActive").toBool());
        drop(cellCenter(0));                       // 原地放下
        QVERIFY2(main->property("editMode").toBool(), "松手后编辑态消失了");

        const QPoint blank(qRound(pagesX * 0.6), 40);
        click(blank);
        QVERIFY2(!main->property("editMode").toBool(), "点空白未退出编辑态");
        QVERIFY2(win->isVisible(), "编辑态下点空白不应关闭窗口");

        click(blank);
        QVERIFY2(!win->isVisible(), "非编辑态点空白应关闭窗口");
        win->showFullScreen();
        wait(400);
    }

    void t05_swipeOnGridPages() {
        QCOMPARE(main->property("currentPage").toInt(), 0);
        const QPoint from = cellCenter(3);                       // 明确落在图标上
        const QPoint to = from - QPoint(qRound(cellW * 2.5), 0);
        QTest::mousePress(win, Qt::LeftButton, Qt::NoModifier, from);
        wait(60);
        QTest::mouseMove(win, to);
        wait(60);
        QVERIFY2(main->property("pageDragging").toBool(), "图标上横向拖动未进入翻页手势");
        QTest::mouseRelease(win, Qt::LeftButton, Qt::NoModifier, to);
        wait(500);
        QCOMPARE(main->property("currentPage").toInt(), 1);
        QVERIFY2(win->isVisible(), "翻页手势不该启动应用或关窗");
    }

    void t06_everyPageShowsItsIcons() {
        // 任意 currentPage 下所有 delegate 都常驻可见，
        // 且属于该页的 delegate 的 x 必须落在 pager 的视口范围内
        const qreal areaW = win->width() - 2 * pagesX;
        for (int page = 0; page < 3; ++page) {
            main->setProperty("currentPage", page);
            wait(600);
            QList<QQuickItem *> items;
            std::function<void(QQuickItem *)> rec = [&](QQuickItem *it) {
                for (QQuickItem *c : it->childItems()) rec(c);
                if (it->property("appRow").isValid()) items << it;
            };
            rec(win->contentItem());
            QCOMPARE(items.size(), APP_COUNT);
            int visibleCount = 0, inView = 0;
            for (QQuickItem *it : items) {
                if (it->property("visible").toBool()) ++visibleCount;
                if (it->property("slotPage").toInt() != page) continue;
                const qreal x = it->x();
                if (x >= page * areaW - 1 && x < (page + 1) * areaW) ++inView;
            }
            QVERIFY2(visibleCount == APP_COUNT,
                     qPrintable(QString("第%1页有 delegate 不可见: %2/%3")
                                    .arg(page).arg(visibleCount).arg(APP_COUNT)));
            QVERIFY2(inView == 35, qPrintable(QString("第%1页只有 %2/35 个图标落在视口内")
                                                  .arg(page).arg(inView)));
        }
        main->setProperty("currentPage", 0);
        wait(300);
    }

    void t07_clipWindowDoesNotMove() {
        // clip 必须由"不自位移"的容器承担，否则裁剪窗口跟着内容跑掉，
        // 第 2 页起的内容会被自己的裁剪框裁掉（坐标全对却不画一个像素）
        QQuickItem *vp = win->findChild<QQuickItem *>("pagerViewport");
        QQuickItem *pg = win->findChild<QQuickItem *>("pager");
        QVERIFY2(vp, "找不到 pagerViewport");
        QVERIFY2(pg, "找不到 pager");
        QVERIFY2(vp->clip(), "裁剪容器没有开 clip");
        QCOMPARE(pg->parentItem(), vp);
        for (int page = 0; page < 3; ++page) {
            main->setProperty("currentPage", page);
            wait(600);
            QCOMPARE(qRound(pg->x()), -page * qRound(pg->width()));
            QVERIFY2(qRound(vp->x()) == 0,
                     qPrintable(QString("裁剪窗口被移动了: x=%1，第 %2 页内容会被裁掉")
                                    .arg(vp->x()).arg(page + 1)));
        }
        main->setProperty("currentPage", 0);
        wait(300);
    }

    // ---------------- 文件夹 ----------------

    void t08_hoverMergesIntoFolder() {
        pressHold(cellCenter(0));
        QVERIFY(main->property("dragActive").toBool());
        moveTo(cellCenter(1));                     // 悬停到邻居图标上
        QCOMPARE(main->property("mergeCandidate").toString(), appId(1));
        QTRY_VERIFY_WITH_TIMEOUT(!main->property("dragActive").toBool(), 3000);   // 等合并定时器

        QCOMPARE(model->count(), APP_COUNT - 1);   // 两个图标合成一个文件夹
        QVERIFY2(folderAt(0), "合并后槽位 0 应该是文件夹");
        QCOMPARE(folderCount(0), 2);
        QVERIFY(model->idAt(0).startsWith("folder:"));
        QVERIFY2(!main->property("dragActive").toBool(), "合并后拖动应结束");
    }

    void t09_folderPanelOpensAndRenames() {
        QVERIFY(model->mergeInto(appId(0), appId(1)));
        const QString fid = model->idAt(0);
        QVERIFY(fid.startsWith("folder:"));

        // 点文件夹图标 → 弹面板
        click(cellCenter(0));
        QCOMPARE(main->property("folderOpen").toString(), fid);
        QVector<QVariant> members;
        const QVariantList ml = model->folderMembers(fid);
        QCOMPARE(ml.size(), 2);
        QVERIFY2(win->isVisible(), "打开文件夹不该关窗");

        // 面板里改名（走真实的 TextInput + 回车）
        QQuickItem *input = win->findChild<QQuickItem *>("folderNameInput");
        QVERIFY2(input, "找不到 folderNameInput");
        input->setProperty("focus", true);
        input->setProperty("text", QStringLiteral("我的工具"));
        wait(120);
        QTest::keyClick(win, Qt::Key_Return);
        wait(300);
        QCOMPARE(model->folderName(fid), QStringLiteral("我的工具"));
        QCOMPARE(model->index(0, 0).data(AppModel::NameRole).toString(), QStringLiteral("我的工具"));

        // 点面板外部收起
        click(QPoint(qRound(win->width() * 0.5), qRound(win->height() * 0.06)));
        QCOMPARE(main->property("folderOpen").toString(), QString());
    }

    void t10_mergeAndTakeFromFolder() {
        model->ensureLoaded();
        QVERIFY(model->mergeInto(appId(0), appId(1)));
        QCOMPARE(model->count(), APP_COUNT - 1);
        const QString fid = model->idAt(0);
        QCOMPARE(folderCount(0), 2);

        // 把第三个图标也拖进已有文件夹
        QVERIFY(model->mergeInto(appId(2), fid));
        QCOMPARE(model->count(), APP_COUNT - 2);
        QCOMPARE(folderCount(0), 3);

        // 拖出一个成员 → 变回独立图标
        QVERIFY(model->takeFromFolder(fid, appId(0)));
        QCOMPARE(model->count(), APP_COUNT - 1);
        QCOMPARE(folderCount(0), 2);
        int found = -1;
        for (int i = 0; i < model->count(); ++i)
            if (model->idAt(i) == appId(0)) { found = i; break; }
        QVERIFY2(found >= 0, "拖出的成员应重新出现在网格上");

        // 成员被搬空 → 文件夹自动解散
        while (folderCount(0) > 0 && model->idAt(0).startsWith("folder:")) {
            const QString f = model->idAt(0);
            const QVariantList mem = model->folderMembers(f);
            if (mem.isEmpty()) break;
            QVERIFY(model->takeFromFolder(f, mem.first().toMap().value("appId").toString()));
        }
        QCOMPARE(model->count(), APP_COUNT);
        for (int i = 0; i < model->count(); ++i)
            QVERIFY2(!model->idAt(i).startsWith("folder:"), "空文件夹应自动消失");
    }

    void t11_searchHitsFolderMembers() {
        model->ensureLoaded();
        QVERIFY(model->mergeInto(appId(0), appId(1)));     // app000 进文件夹
        QCOMPARE(model->count(), APP_COUNT - 1);

        model->setFilter(QStringLiteral("App000"));        // 搜文件夹内的应用
        QCOMPARE(model->count(), 1);
        QCOMPARE(model->idAt(0), appId(0));                // 作为普通图标单独列出
        QVERIFY2(!folderAt(0), "搜索命中的应是应用本身，而不是文件夹");

        // 搜文件夹名 → 命中文件夹本身
        model->setFilter(QString());
    }

    void t12_layoutPersistsAndMigratesFromOrder() {
        // 造布局并持久化
        model->ensureLoaded();
        QVERIFY(model->mergeInto(appId(0), appId(1)));
        const QString fid = model->idAt(0);
        QVERIFY(model->renameFolder(fid, QStringLiteral("测试夹")));

        // 新模型实例应读出同一布局
        AppModel reloaded;
        reloaded.setSearchDirs({g_tmpRoot + "/apps"});
        reloaded.ensureLoaded();
        QCOMPARE(reloaded.count(), APP_COUNT - 1);
        QCOMPARE(reloaded.idAt(0), fid);
        QCOMPARE(reloaded.folderName(fid), QStringLiteral("测试夹"));
        QCOMPARE(reloaded.index(0, 0).data(AppModel::FolderCountRole).toInt(), 2);
        QVERIFY(reloaded.index(0, 0).data(AppModel::IsFolderRole).toBool());

        // 旧版本的 order 配置 → 自动迁移
        {
            QFile::remove(launchpadConfigDir() + "/launchpad.json");
            QSettings s(launchpadConfigDir() + "/settings.conf", QSettings::IniFormat);
            s.remove("layout");
            s.setValue("order", QStringList{appId(2), appId(0), appId(1)}.join(','));
            s.sync();
        }
        AppModel migrated;
        migrated.setSearchDirs({g_tmpRoot + "/apps"});
        migrated.ensureLoaded();
        QCOMPARE(migrated.idAt(0), appId(2));
        QCOMPARE(migrated.idAt(1), appId(0));
        QCOMPARE(migrated.idAt(2), appId(1));
        QCOMPARE(migrated.count(), APP_COUNT);
        QFile check(launchpadConfigDir() + "/launchpad.json");
        QVERIFY(check.open(QIODevice::ReadOnly));
        QVERIFY(!QJsonDocument::fromJson(check.readAll()).object().value("entries").toArray().isEmpty());
    }
};

int main(int argc, char **argv) {
    // 必须在 QGuiApplication 之前重定向，避免碰到用户真实配置
    g_tmpRoot = QDir::tempPath() + "/launchpad-test-" + QString::number(::getpid());
    QDir(g_tmpRoot).removeRecursively();
    QDir().mkpath(g_tmpRoot + "/config");
    writeFakeApps(g_tmpRoot + "/apps", APP_COUNT);
    qputenv("XDG_CONFIG_HOME", (g_tmpRoot + "/config").toUtf8());

    QGuiApplication app(argc, argv);
    DragTest tc;
    const int rc = QTest::qExec(&tc, argc, argv);
    QDir(g_tmpRoot).removeRecursively();
    return rc;
}
#include "tst_drag.moc"
