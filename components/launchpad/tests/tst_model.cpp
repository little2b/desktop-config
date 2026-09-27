#include "appmodel.h"
#include <QTemporaryDir>
#include <QtTest>

class ModelTest : public QObject {
    Q_OBJECT
    QTemporaryDir m_root;

    void desktop(const QString &relative, const QByteArray &extra = {}) {
        const QString path = m_root.path() + '/' + relative;
        QDir().mkpath(QFileInfo(path).absolutePath());
        QFile file(path);
        QVERIFY(file.open(QIODevice::WriteOnly));
        file.write("[Desktop Entry]\nType=Application\nName=Example\nExec=/bin/true\n" + extra);
    }

private slots:
    void initTestCase() {
        QVERIFY(m_root.isValid());
        qputenv("CLAVIS_CONFIG_HOME", (m_root.path() + "/config").toUtf8());
        qputenv("XDG_CURRENT_DESKTOP", "niri");
        QDir().mkpath(launchpadConfigDir());
    }
    void cleanup() {
        QFile::remove(launchpadConfigDir() + "/launchpad.json");
    }
    void desktopVisibilityAndOverrides() {
        desktop("system/hidden.desktop");
        desktop("user/hidden.desktop", "Hidden=true\n");
        desktop("system/kde.desktop", "OnlyShowIn=KDE;\n");
        desktop("system/niri.desktop", "OnlyShowIn=niri;\n");
        desktop("system/excluded.desktop", "NotShowIn=niri;\n");
        desktop("system/missing.desktop", "TryExec=/does/not/exist\n");
        desktop("system/nested/tool.desktop");
        AppModel model;
        model.setSearchDirs({m_root.path() + "/user", m_root.path() + "/system"});
        model.ensureLoaded();
        QSet<QString> actual;
        for (int i = 0; i < model.count(); ++i) actual.insert(model.idAt(i));
        QCOMPARE(actual, (QSet<QString>{"niri", "nested-tool"}));
    }
    void existingClavisGroupsArePreserved() {
        desktop("layout-apps/one.desktop");
        desktop("layout-apps/two.desktop");
        const QJsonArray members{"one", "temporarily-unavailable", "two"};
        QFile file(launchpadConfigDir() + "/launchpad.json");
        QVERIFY(file.open(QIODevice::WriteOnly));
        file.write(QJsonDocument(QJsonObject{{"schemaVersion", 1}, {"entries", QJsonArray{
            QJsonObject{{"kind", "folder"}, {"id", "existing-folder"}, {"name", "工作"}, {"children", members}}}}}).toJson());
        file.close();
        AppModel model;
        model.setSearchDirs({m_root.path() + "/layout-apps"});
        model.ensureLoaded();
        QCOMPARE(model.count(), 1);
        QCOMPARE(model.folderName("existing-folder"), QStringLiteral("工作"));
        QCOMPARE(model.folderMembers("existing-folder").size(), 2);
        QVERIFY(model.renameFolder("existing-folder", "工具"));
        QVERIFY(file.open(QIODevice::ReadOnly));
        const auto saved = QJsonDocument::fromJson(file.readAll()).object().value("entries").toArray().first().toObject();
        QCOMPARE(saved.value("children").toArray(), members);
        QCOMPARE(saved.value("id").toString(), QStringLiteral("existing-folder"));
        QCOMPARE(saved.value("name").toString(), QStringLiteral("工具"));
    }
    void malformedLayoutIsNotOverwritten() {
        desktop("invalid-apps/one.desktop");
        desktop("invalid-apps/two.desktop");
        QFile file(launchpadConfigDir() + "/launchpad.json");
        QVERIFY(file.open(QIODevice::WriteOnly));
        file.write("{incomplete");
        file.close();
        AppModel model;
        model.setSearchDirs({m_root.path() + "/invalid-apps"});
        model.ensureLoaded();
        QVERIFY(model.mergeInto("one", "two"));
        QVERIFY(file.open(QIODevice::ReadOnly));
        QCOMPARE(file.readAll(), QByteArray("{incomplete"));
    }
};
QTEST_GUILESS_MAIN(ModelTest)
#include "tst_model.moc"
