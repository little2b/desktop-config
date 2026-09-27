#pragma once
/*
 * AppModel：启动台顶层布局模型
 *   顶层项（Entry）要么是一个应用，要么是一个装着若干应用的文件夹。
 *   负责扫描 .desktop、加载/迁移/持久化布局、搜索过滤、启动应用。
 *
 * 抽成独立头文件是为了让测试能直接验证真实实现（而不是一份会漂移的 stub）。
 */
#include <QAbstractListModel>
#include <QDir>
#include <QDirIterator>
#include <QFileSystemWatcher>
#include <QSaveFile>
#include <QTimer>
#include <QLocale>

#pragma push_macro("signals")
#undef signals
#include <gio/gdesktopappinfo.h>
#pragma pop_macro("signals")
#include <QFileInfo>
#include <QHash>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QJsonValue>
#include <QProcess>
#include <QRegularExpression>
#include <QSet>
#include <QSettings>
#include <QStandardPaths>
#include <QStringList>
#include <QUuid>
#include <QVector>
#include <algorithm>

static inline QString launchpadConfigDir() {
    const QString override = qEnvironmentVariable("CLAVIS_CONFIG_HOME");
    return override.startsWith('/') ? override : QStandardPaths::writableLocation(QStandardPaths::GenericConfigLocation) + "/clavis";
}

struct AppInfo {
    QString name, icon, desktopId, exec, path;
};

// 顶层布局项：一个应用，或一个装着若干应用的文件夹
struct Entry {
    bool isFolder = false;
    QString id;             // app: desktopId；folder: "folder:<uuid8>"
    QString name;           // folder: 显示名
    QStringList members;    // folder: 成员 desktopId（有序）
};

class AppModel : public QAbstractListModel {
    Q_OBJECT
    Q_PROPERTY(int count READ count NOTIFY countChanged)
    Q_PROPERTY(QString filter READ filter WRITE setFilter NOTIFY filterChanged)
public:
    enum Roles {
        NameRole = Qt::UserRole + 1, IconRole, IdRole, RowRole,
        IsFolderRole, FolderIconsRole, FolderCountRole
    };

    explicit AppModel(QObject *parent = nullptr) : QAbstractListModel(parent) {
        m_refreshTimer.setSingleShot(true);
        m_refreshTimer.setInterval(400);
        connect(&m_watcher, &QFileSystemWatcher::directoryChanged, this, [this] {
            m_reloadPending = true;
            if (!m_uiActive) m_refreshTimer.start();
        });
        connect(&m_refreshTimer, &QTimer::timeout, this, [this] {
            if (m_uiActive) return;
            m_reloadPending = false;
            beginResetModel();
            loadApps();
            loadLayout();
            rebuild();
            emit applicationsChanged(); // Warm new icons before delegates see the reset.
            endResetModel();
            emit countChanged();
        });
    }

    // 测试用：覆写 .desktop 扫描目录（留空则扫描系统目录）
    void setSearchDirs(const QStringList &dirs) { m_searchDirs = dirs; }

    // 由 QML 在窗口显示时调用
    Q_INVOKABLE void ensureLoaded() {
        if (m_loaded) return;
        m_loaded = true;
        beginResetModel();
        loadApps();
        loadLayout();
        rebuild();
        emit applicationsChanged();
        endResetModel();
        emit countChanged();
    }

    Q_INVOKABLE void setUiActive(bool active) {
        m_uiActive = active;
        if (!active && m_reloadPending) m_refreshTimer.start();
    }

    QStringList icons() const {
        QStringList icons;
        for (const auto &app : m_apps) icons << app.icon;
        icons.removeDuplicates();
        return icons;
    }

    int rowCount(const QModelIndex & = {}) const override { return m_view.size(); }
    int count() const { return m_view.size(); }
    QString filter() const { return m_filter; }

    void setFilter(const QString &f) {
        if (f == m_filter) return;
        m_filter = f;
        emit filterChanged();
        refresh();
    }

    QVariant data(const QModelIndex &idx, int role) const override {
        const int row = idx.row();
        if (row < 0 || row >= m_view.size()) return {};
        const Entry &e = m_view.at(row);
        switch (role) {
        case NameRole:  return e.isFolder ? e.name : appName(e.id);
        case IconRole:  return e.isFolder ? QString() : appIcon(e.id);
        case IdRole:    return e.id;
        case RowRole:   return row;
        case IsFolderRole: return e.isFolder;
        case FolderIconsRole: {
            // 文件夹图标：最多取 9 个成员图标，QML 画成 3x3 缩略网格
            QStringList icons;
            if (e.isFolder) {
                for (const auto &member : e.members) {
                    if (m_index.contains(member) && icons.size() < 9) icons << appIcon(member);
                }
            }
            return icons;
        }
        case FolderCountRole: return e.isFolder ? folderMembers(e.id).size() : 0;
        }
        return {};
    }

    QHash<int, QByteArray> roleNames() const override {
        return {{NameRole, "appName"},   {IconRole, "appIcon"},
                {IdRole, "appId"},       {RowRole, "row"},
                {IsFolderRole, "isFolder"},
                {FolderIconsRole, "folderIcons"},
                {FolderCountRole, "folderCount"}};
    }

    Q_INVOKABLE QString idAt(int row) const {
        if (row < 0 || row >= m_view.size()) return QString();
        return m_view.at(row).id;
    }

    Q_INVOKABLE bool launch(const QString &desktopId) const {
        const int i = m_index.value(desktopId, -1);
        if (i < 0) return false;
        QStringList command;
        if (desktopId == "org.clavis.Settings")
            command = {"qs", "-c", "clavis", "ipc", "call", "control-center", "open", ""};
        else
            command = {"gio", "launch", m_apps.at(i).path};
        // Start a scope before launching: restarting the menu must not kill its apps.
        QStringList scoped{"--user", "--scope", "--collect", "--quiet", "--slice=app.slice", "--expand-environment=no", "--"};
        scoped.append(command);
        return QProcess::startDetached(QStringLiteral("systemd-run"), scoped);
    }

    // ---------- 布局变更接口（QML 调用，立即持久化） ----------

    // 拖动排序：QML 提交顶层项 id 的新顺序
    Q_INVOKABLE void commitLayout(const QVariantList &idsInOrder) {
        if (!m_loaded || !m_filter.isEmpty()) return;
        if (idsInOrder.size() != m_view.size()) return;
        QVector<Entry> reordered;
        QSet<QString> requested, visible;
        for (const auto &entry : m_view) visible.insert(entry.id);
        for (const QVariant &v : idsInOrder) {
            const QString id = v.toString();
            const int i = indexOfEntry(id);
            if (i < 0 || !visible.contains(id) || requested.contains(id)) return;
            requested.insert(id);
            reordered << m_entries.at(i);
        }
        int index = 0;
        for (auto &entry : m_entries)
            if (visible.contains(entry.id)) entry = reordered.at(index++);
        persist();
        refresh();
    }

    // 拖到另一个图标上 → 合成新文件夹 / 加入已有文件夹
    Q_INVOKABLE bool mergeInto(const QString &draggedId, const QString &targetId) {
        if (!m_loaded || !m_filter.isEmpty()) return false;
        if (draggedId.isEmpty() || draggedId == targetId) return false;
        const int di = indexOfEntry(draggedId);
        const int ti = indexOfEntry(targetId);
        if (di < 0 || ti < 0) return false;
        // 已经在一起了就别重复
        if (m_entries.at(ti).isFolder && m_entries.at(ti).members.contains(draggedId)) return false;
        if (m_entries.at(di).isFolder && m_entries.at(di).members.contains(targetId)) return false;

        QStringList moved;
        if (m_entries.at(di).isFolder) moved = m_entries.at(di).members;
        else moved << draggedId;

        if (m_entries.at(ti).isFolder) {
            QStringList &members = m_entries[ti].members;
            for (const QString &m : moved)
                if (!members.contains(m)) members << m;
            m_entries.removeAt(di);
        } else {
            Entry f;
            f.isFolder = true;
            f.id = QStringLiteral("folder:") +
                   QUuid::createUuid().toString(QUuid::WithoutBraces).left(8);
            f.name = defaultFolderName();
            f.members = moved;
            f.members << targetId;
            m_entries.removeAt(di);
            const int at = indexOfEntry(targetId);   // 删除后索引会变，重新定位
            m_entries.removeAt(at);
            m_entries.insert(at, f);
        }
        pruneEmptyFolders();
        persist();
        refresh();
        return true;
    }

    // 从文件夹里拖出成员 → 变回独立图标，插在该文件夹后面
    Q_INVOKABLE bool takeFromFolder(const QString &folderId, const QString &memberId) {
        if (!m_loaded) return false;
        const int fi = indexOfEntry(folderId);
        if (fi < 0 || !m_entries.at(fi).isFolder) return false;
        if (!m_entries[fi].members.removeOne(memberId)) return false;
        Entry e;
        e.id = memberId;
        m_entries.insert(fi + 1, e);
        pruneEmptyFolders();
        persist();
        refresh();
        return true;
    }

    Q_INVOKABLE bool renameFolder(const QString &folderId, const QString &name) {
        if (!m_loaded) return false;
        const int i = indexOfEntry(folderId);
        if (i < 0 || !m_entries.at(i).isFolder) return false;
        const QString trimmed = name.trimmed();
        if (m_entries.at(i).name == trimmed) return true;
        m_entries[i].name = trimmed.isEmpty() ? defaultFolderName() : trimmed.left(60);
        persist();
        refresh();
        return true;
    }

    // 面板内拖动重排：只接受同一批成员换顺序，别的一律拒绝
    Q_INVOKABLE bool reorderFolder(const QString &folderId, const QVariantList &memberIds) {
        if (!m_loaded) return false;
        const int i = indexOfEntry(folderId);
        if (i < 0 || !m_entries.at(i).isFolder) return false;
        QStringList ids;
        ids.reserve(memberIds.size());
        for (const QVariant &v : memberIds) ids << v.toString();
        if (ids.size() != m_entries.at(i).members.size()) return false;
        for (const QString &id : ids)
            if (!m_entries.at(i).members.contains(id)) return false;
        m_entries[i].members = ids;
        persist();
        refresh();
        return true;
    }

    // 面板用：文件夹成员（id / name / icon）
    Q_INVOKABLE QVariantList folderMembers(const QString &folderId) const {
        QVariantList out;
        const int i = indexOfEntry(folderId);
        if (i < 0 || !m_entries.at(i).isFolder) return out;
        for (const QString &m : m_entries.at(i).members) {
            if (!m_index.contains(m)) continue;
            QVariantMap o;
            o["appId"] = m;
            o["appName"] = appName(m);
            o["appIcon"] = appIcon(m);
            out << o;
        }
        return out;
    }

    Q_INVOKABLE bool isFolder(const QString &id) const {
        const int i = indexOfEntry(id);
        return i >= 0 && m_entries.at(i).isFolder;
    }

    Q_INVOKABLE QString folderName(const QString &folderId) const {
        const int i = indexOfEntry(folderId);
        return (i >= 0 && m_entries.at(i).isFolder) ? m_entries.at(i).name : QString();
    }

private:
    static QString defaultFolderName() { return QStringLiteral("文件夹"); }

    QString appName(const QString &id) const {
        const int i = m_index.value(id, -1);
        return i >= 0 ? m_apps.at(i).name : id;
    }
    QString appIcon(const QString &id) const {
        const int i = m_index.value(id, -1);
        return i >= 0 ? m_apps.at(i).icon : QStringLiteral("application-x-executable");
    }

    int indexOfEntry(const QString &id) const {
        for (int i = 0; i < m_entries.size(); ++i)
            if (m_entries.at(i).id == id) return i;
        return -1;
    }

    // 成员被搬空的文件夹自动消失
    void pruneEmptyFolders() {
        for (int i = m_entries.size() - 1; i >= 0; --i)
            if (m_entries.at(i).isFolder && m_entries.at(i).members.isEmpty())
                m_entries.removeAt(i);
    }

    void refresh() {
        beginResetModel();
        rebuild();
        endResetModel();
        emit countChanged();
    }

    void loadApps() {
        m_apps.clear();
        m_index.clear();
        QSet<QString> seen;
        QStringList watched;
        const QByteArray desktop = qEnvironmentVariable("XDG_CURRENT_DESKTOP", "niri").toUtf8();
        for (const QString &dirPath : searchDirs()) {
            if (!QDir(dirPath).exists()) continue;
            watched << dirPath;
            QDirIterator files(dirPath, {"*.desktop"}, QDir::Files, QDirIterator::Subdirectories);
            while (files.hasNext()) {
                const QString path = files.next();
                QString id = QDir(dirPath).relativeFilePath(path);
                id.chop(8);
                id.replace('/', '-');
                if (seen.contains(id)) continue;
                seen.insert(id); // Hidden user overrides also suppress system entries.
                if (id == "launchpad" || id == "org.clavis.NiriLaunchpad" || id == "org.clavis.Launchpad") continue;
                GDesktopAppInfo *info = g_desktop_app_info_new_from_filename(path.toUtf8().constData());
                if (!info) continue;
                if (g_desktop_app_info_get_is_hidden(info) || g_desktop_app_info_get_nodisplay(info)
                    || !g_desktop_app_info_get_show_in(info, desktop.constData())) {
                    g_object_unref(info);
                    continue;
                }
                AppInfo a;
                a.desktopId = id;
                a.path = path;
                a.name = QString::fromUtf8(g_app_info_get_display_name(G_APP_INFO(info)));
                if (a.name.isEmpty()) a.name = id;
                char *icon = g_desktop_app_info_get_string(info, "Icon");
                a.icon = icon ? QString::fromUtf8(icon) : QStringLiteral("application-x-executable");
                g_free(icon);
                const char *command = g_app_info_get_commandline(G_APP_INFO(info));
                a.exec = command ? QString::fromUtf8(command) : QString();
                m_apps << a;
                g_object_unref(info);
            }
        }
        if (m_searchDirs.isEmpty() && QFileInfo::exists(launchpadConfigDir() + "/config.json")
            && !QStandardPaths::findExecutable("qs").isEmpty()) {
            AppInfo settings;
            settings.desktopId = "org.clavis.Settings";
            settings.name = QLocale().language() == QLocale::Chinese ? QStringLiteral("Clavis 设置") : QStringLiteral("Clavis Settings");
            settings.icon = "preferences-system";
            m_apps << settings;
        }
        std::sort(m_apps.begin(), m_apps.end(), [](const AppInfo &a, const AppInfo &b) {
            return a.name.localeAwareCompare(b.name) < 0;
        });
        for (int i = 0; i < m_apps.size(); ++i) m_index.insert(m_apps.at(i).desktopId, i);
        if (!m_watcher.directories().isEmpty()) m_watcher.removePaths(m_watcher.directories());
        if (!watched.isEmpty()) m_watcher.addPaths(watched);
    }

    // 顶层布局：优先读新的 layout（JSON），否则从旧的 order 迁移
    void loadLayout() {
        m_entries.clear();
        QSettings s(launchpadConfigDir() + "/settings.conf", QSettings::IniFormat);
        QFile layout(launchpadConfigDir() + "/launchpad.json");
        QString json;
        if (layout.open(QIODevice::ReadOnly)) {
            QJsonParseError error;
            const auto document = QJsonDocument::fromJson(layout.readAll(), &error);
            if (error.error != QJsonParseError::NoError || !document.object().value("entries").isArray()) {
                qWarning("Invalid Launchpad layout; leaving it untouched");
                m_writable = false;
            } else {
                json = QString::fromUtf8(QJsonDocument(document.object().value("entries").toArray()).toJson());
            }
        } else if (!layout.exists()) {
            json = s.value("layout").toString();
        } else {
            m_writable = false;
        }
        // 从旧版 order 迁移过来时，写完一次 layout 就算迁移完成
        const bool needMigrate =
            json.isEmpty() && !s.value("order").toString().isEmpty();
        if (!json.isEmpty()) {
            const QJsonArray arr = QJsonDocument::fromJson(json.toUtf8()).array();
            for (const QJsonValue &v : arr) {
                const QJsonObject o = v.toObject();
                Entry e;
                e.isFolder = (o.value("kind").toString(o.value("type").toString()) == "folder");
                e.id = o.value("id").toString();
                if (e.id.isEmpty()) continue;
                if (e.isFolder) {
                    e.name = o.value("name").toString();
                    if (e.name.isEmpty()) e.name = defaultFolderName();
                    for (const QJsonValue &mv : o.value("children").toArray(o.value("members").toArray())) {
                        const QString mid = mv.toString();
                        if (!mid.isEmpty() && !e.members.contains(mid))
                            e.members << mid;
                    }
                }
                m_entries << e;
            }
        } else {
            const QStringList order = s.value("order").toString().split(',', Qt::SkipEmptyParts);
            for (const QString &id : order) {
                if (!m_index.contains(id)) continue;
                Entry e;
                e.id = id;
                m_entries << e;
            }
        }

        // 布局里没提到过的应用（首次运行 / 新装的）按名字顺序补到末尾
        QSet<QString> placed;
        for (const Entry &e : m_entries) {
            if (e.isFolder) {
                for (const QString &m : e.members) placed.insert(m);
            } else {
                placed.insert(e.id);
            }
        }
        for (const AppInfo &a : m_apps) {
            if (placed.contains(a.desktopId)) continue;
            Entry e;
            e.id = a.desktopId;
            m_entries << e;
        }
        pruneEmptyFolders();
        if (needMigrate) persist();
    }

    void persist() const {
        if (!m_writable) return;
        QJsonArray arr;
        for (const Entry &e : m_entries) {
            QJsonObject o;
            o["kind"] = e.isFolder ? "folder" : "app";
            o["id"] = e.id;
            if (e.isFolder) {
                o["name"] = e.name;
                o["children"] = QJsonArray::fromStringList(e.members);
            }
            arr.append(o);
        }
        QDir().mkpath(launchpadConfigDir());
        QSaveFile file(launchpadConfigDir() + "/launchpad.json");
        if (!file.open(QIODevice::WriteOnly)) return;
        const QByteArray data = QJsonDocument(QJsonObject{{"schemaVersion", 1}, {"entries", arr}}).toJson();
        if (file.write(data) != data.size() || !file.commit())
            qWarning("Unable to save Launchpad layout");
    }

    bool matches(const AppInfo &a) const {
        return a.name.contains(m_filter, Qt::CaseInsensitive) ||
               a.desktopId.contains(m_filter, Qt::CaseInsensitive);
    }

    void rebuild() {
        m_view.clear();
        if (m_filter.isEmpty()) {
            for (const auto &entry : m_entries) {
                const bool available = entry.isFolder
                    ? std::any_of(entry.members.begin(), entry.members.end(), [this](const QString &id) { return m_index.contains(id); })
                    : m_index.contains(entry.id);
                if (available) m_view << entry;
            }
            return;
        }
        // 搜索：文件夹名命中 → 文件夹本身；成员命中 → 把该应用当普通图标单独列出
        for (const Entry &e : m_entries) {
            if (e.isFolder) {
                if (e.name.contains(m_filter, Qt::CaseInsensitive)) m_view << e;
                for (const QString &mid : e.members) {
                    const int ai = m_index.value(mid, -1);
                    if (ai >= 0 && matches(m_apps.at(ai))) {
                        Entry leaf;
                        leaf.id = mid;
                        m_view << leaf;
                    }
                }
            } else {
                const int ai = m_index.value(e.id, -1);
                if (ai >= 0 && matches(m_apps.at(ai))) m_view << e;
            }
        }
    }

    QStringList searchDirs() const {
        if (!m_searchDirs.isEmpty()) return m_searchDirs;
        return QStandardPaths::standardLocations(QStandardPaths::ApplicationsLocation);
    }

    QStringList m_searchDirs;
    QVector<AppInfo> m_apps;
    QHash<QString, int> m_index;   // desktopId → m_apps 下标
    QVector<Entry> m_entries;      // 顶层布局（真实）
    QVector<Entry> m_view;         // 当前显示项（= m_entries，或搜索结果）
    QString m_filter;
    bool m_loaded = false;
    bool m_writable = true;
    bool m_uiActive = false;
    bool m_reloadPending = false;
    QFileSystemWatcher m_watcher;
    QTimer m_refreshTimer;

signals:
    void applicationsChanged();
    void countChanged();
    void filterChanged();
};
