// Niri integration for cccp00-cup/macos-launchpad-for-linux; GPL-3.0.
#include "appmodel.h"
#include "iconprovider.h"
#include "wallpaper.h"
#include <LayerShellQt/Window>
#include <QCommandLineParser>
#include <QCoreApplication>
#include <QGuiApplication>
#include <QLocalServer>
#include <QLocalSocket>
#include <QLockFile>
#include <QPointer>
#include <QQmlApplicationEngine>
#include <QQmlContext>
#include <QQuickWindow>
#include <QScreen>
#include <cstdio>

static QString socketPath() {
    return QStandardPaths::writableLocation(QStandardPaths::RuntimeLocation) + "/clavis-launchpad.sock";
}

static void printJson(const QJsonObject &object) {
    const QByteArray line = QJsonDocument(object).toJson(QJsonDocument::Compact) + '\n';
    std::fwrite(line.constData(), 1, line.size(), stdout);
    std::fflush(stdout);
}

static int client(QCoreApplication &app, const QStringList &arguments) {
    QString action = "toggle", output;
    for (const auto &candidate : {"show", "hide", "toggle", "status", "watch"})
        if (arguments.contains("--" + QString::fromLatin1(candidate))) action = candidate;
    const int index = arguments.indexOf("--output");
    if (index >= 0 && index + 1 < arguments.size()) output = arguments.at(index + 1);
    QLocalSocket socket;
    const bool watch = action == "watch";
    QTimer reconnect, timeout;
    reconnect.setSingleShot(true);
    reconnect.setInterval(1000);
    timeout.setSingleShot(true);
    timeout.setInterval(2500);
    const auto connectSocket = [&] { socket.abort(); socket.connectToServer(socketPath()); };
    QObject::connect(&reconnect, &QTimer::timeout, &app, connectSocket);
    QObject::connect(&socket, &QLocalSocket::connected, &app, [&] {
        socket.write(QJsonDocument(QJsonObject{{"action", action}, {"output", output}}).toJson(QJsonDocument::Compact) + '\n');
        if (watch) timeout.stop();
    });
    QObject::connect(&socket, &QLocalSocket::readyRead, &app, [&] {
        while (socket.canReadLine()) {
            const auto message = QJsonDocument::fromJson(socket.readLine()).object();
            if (!message.isEmpty()) printJson(message);
            if (!watch) app.exit(message.value("ok").toBool(true) ? 0 : 1);
        }
    });
    QObject::connect(&socket, &QLocalSocket::errorOccurred, &app, [&](QLocalSocket::LocalSocketError) {
        if (watch) {
            printJson({{"schemaVersion", 1}, {"visible", false}, {"phase", "unavailable"}});
            reconnect.start();
        } else {
            std::fprintf(stderr, "Launchpad is not running. Start clavis-launchpad.service.\n");
            app.exit(2);
        }
    });
    QObject::connect(&socket, &QLocalSocket::disconnected, &app, [&] {
        if (watch) {
            printJson({{"schemaVersion", 1}, {"visible", false}, {"phase", "unavailable"}});
            reconnect.start();
        }
    });
    QObject::connect(&timeout, &QTimer::timeout, &app, [&] { app.exit(2); });
    if (!watch) timeout.start();
    QTimer::singleShot(0, &app, connectSocket);
    return app.exec();
}

class Controller : public QObject {
    Q_OBJECT
public:
    explicit Controller(QQuickWindow *window, AppModel *model, QObject *parent = nullptr)
        : QObject(parent), m_window(window), m_model(model) {
        if (QGuiApplication::platformName() == "wayland") {
            m_layer = LayerShellQt::Window::get(window);
            m_layer->setScope("clavis-external-launchpad");
            m_layer->setLayer(LayerShellQt::Window::LayerOverlay);
            m_layer->setAnchors(LayerShellQt::Window::Anchors(LayerShellQt::Window::AnchorTop) | LayerShellQt::Window::AnchorBottom
                                | LayerShellQt::Window::AnchorLeft | LayerShellQt::Window::AnchorRight);
            m_layer->setExclusiveZone(-1);
            m_layer->setKeyboardInteractivity(LayerShellQt::Window::KeyboardInteractivityExclusive);
            m_layer->setCloseOnDismissed(true);
        }
        connect(window, SIGNAL(phaseChanged()), this, SLOT(phaseChanged()));
        connect(window, &QWindow::visibleChanged, this, [this](bool visible) {
            if (!visible) {
                m_requested = false;
                m_model->setUiActive(false);
                // Let Niri restore the previously focused window before releasing Clavis chrome.
                QTimer::singleShot(35, this, [this] { if (!m_requested) broadcast(); });
            }
        });
        m_server.setSocketOptions(QLocalServer::UserAccessOption);
        QLocalServer::removeServer(socketPath());
        if (!m_server.listen(socketPath())) qFatal("Cannot listen on Launchpad socket");
        connect(&m_server, &QLocalServer::newConnection, this, [this] {
            while (m_server.hasPendingConnections()) {
                auto *socket = m_server.nextPendingConnection();
                connect(socket, &QLocalSocket::disconnected, socket, &QObject::deleteLater);
                connect(socket, &QLocalSocket::readyRead, this, [this, socket] {
                    if (socket->bytesAvailable() > 65536) { socket->disconnectFromServer(); return; }
                    while (socket->canReadLine()) {
                        const auto request = QJsonDocument::fromJson(socket->readLine()).object();
                        const QString action = request.value("action").toString();
                        if (action == "watch") {
                            m_watchers << socket;
                        } else if (action == "show" || action == "toggle") {
                            if (action == "toggle" && m_requested) hide();
                            else show(request.value("output").toString());
                        } else if (action == "hide") hide();
                        else if (action != "status") {
                            send(socket, {{"ok", false}, {"error", "Unknown action"}});
                            socket->disconnectFromServer();
                            return;
                        }
                        send(socket, state());
                        if (action != "watch") socket->disconnectFromServer();
                    }
                });
            }
        });
    }

    QJsonObject state() const {
        return {{"schemaVersion", 1}, {"ok", true}, {"visible", m_requested || m_window->isVisible()},
                {"phase", m_requested && !m_window->isVisible() ? "preparing" : m_window->property("phase").toString()},
                {"output", m_window->screen() ? m_window->screen()->name() : QString()},
                {"ready", m_window->property("contentReady").toBool()}, {"entries", m_model->count()}};
    }

    void show(const QString &output) {
        m_requested = true;
        m_model->setUiActive(true);
        QScreen *screen = nullptr;
        for (auto *candidate : QGuiApplication::screens())
            if (candidate->name() == output) screen = candidate;
        if (!screen) screen = QGuiApplication::primaryScreen();
        if (screen && screen != m_window->screen()) {
            m_window->hide();
            m_window->destroy();
            m_window->setScreen(screen);
            m_requested = true;
            m_model->setUiActive(true);
        }
        if (m_layer) {
            if (screen) m_layer->setScreen(screen);
            m_layer->setDesiredSize(screen ? screen->geometry().size() : QSize(1280, 720));
        }
        if (screen) m_window->resize(screen->geometry().size());
        if (m_window->isVisible()) {
            QMetaObject::invokeMethod(m_window, "reopen");
            broadcast();
            return;
        }
        broadcast();
        // The state subscription reaches Clavis before the surface takes keyboard focus.
        QTimer::singleShot(35, this, [this] {
            if (!m_requested) return;
            if (m_window->isVisible()) QMetaObject::invokeMethod(m_window, "reopen");
            else m_window->show();
        });
    }

    void hide() {
        m_requested = false;
        if (m_window->isVisible()) QMetaObject::invokeMethod(m_window, "closeWindow");
        else broadcast();
    }

private slots:
    void phaseChanged() {
        const QString phase = m_window->property("phase").toString();
        if (phase == "closing") m_requested = false;
        if (phase != "hidden") broadcast();
    }

private:
    static void send(QLocalSocket *socket, const QJsonObject &message) {
        socket->write(QJsonDocument(message).toJson(QJsonDocument::Compact) + '\n');
        socket->flush();
    }
    void broadcast() {
        for (int i = m_watchers.size() - 1; i >= 0; --i) {
            if (!m_watchers.at(i) || m_watchers.at(i)->state() != QLocalSocket::ConnectedState) m_watchers.removeAt(i);
            else send(m_watchers.at(i), state());
        }
    }
    QQuickWindow *m_window;
    AppModel *m_model;
    LayerShellQt::Window *m_layer = nullptr;
    QLocalServer m_server;
    QList<QPointer<QLocalSocket>> m_watchers;
    bool m_requested = false;
};

int main(int argc, char **argv) {
    QStringList arguments;
    for (int i = 0; i < argc; ++i) arguments << QString::fromLocal8Bit(argv[i]);
    if (arguments.contains("--help")) {
        std::puts("clavis-launchpad --background | --show | --hide | --toggle | --status | --watch [--output NAME]");
        return 0;
    }
    if (!arguments.contains("--background")) {
        QCoreApplication app(argc, argv);
        return client(app, arguments);
    }
    QGuiApplication app(argc, argv);
    app.setApplicationName("clavis-launchpad");
    app.setOrganizationName("clavis");
    app.setDesktopFileName("org.clavis.NiriLaunchpad");
    app.setQuitOnLastWindowClosed(false);
    QLockFile lock(socketPath() + ".lock");
    if (!lock.tryLock(0)) return 0;
    // Clavis may use a different icon theme from GTK applications.
    QFile config(launchpadConfigDir() + "/config.json");
    if (config.open(QIODevice::ReadOnly)) {
        const auto settings = QJsonDocument::fromJson(config.readAll()).object();
        const QString theme = settings.value("theme").toObject().value("iconTheme").toString();
        if (!theme.isEmpty()) QIcon::setThemeName(theme);
    }
    AppModel model;
    auto *icons = new IconProvider;
    QObject::connect(&model, &AppModel::applicationsChanged, &app, [&] { icons->preload(model.icons()); });
    model.ensureLoaded();
    Wallpaper wallpaper;
    QQmlApplicationEngine engine;
    engine.addImageProvider("wallpaper", new WallpaperProvider(&wallpaper));
    engine.addImageProvider("appicon", icons);
    engine.rootContext()->setContextProperty("AppListModel", &model);
    engine.rootContext()->setContextProperty("WallpaperBackend", &wallpaper);
    engine.loadFromModule("Launchpad", "Main");
    if (engine.rootObjects().isEmpty()) return 1;
    auto *window = qobject_cast<QQuickWindow *>(engine.rootObjects().first());
    if (!window) return 1;
    Controller controller(window, &model);
    return app.exec();
}

#include "main.moc"
