#pragma once
#include "appmodel.h"
#include <QCryptographicHash>
#include <QDateTime>
#include <QFileSystemWatcher>
#include <QFutureWatcher>
#include <QImage>
#include <QImageReader>
#include <QPainter>
#include <QQuickImageProvider>
#include <QtConcurrent>

class Wallpaper : public QObject {
    Q_OBJECT
    Q_PROPERTY(bool prepared READ prepared NOTIFY ready)
public:
    explicit Wallpaper(QObject *parent = nullptr) : QObject(parent) {
        m_debounce.setSingleShot(true);
        m_debounce.setInterval(250);
        connect(&m_files, &QFileSystemWatcher::directoryChanged, &m_debounce, qOverload<>(&QTimer::start));
        connect(&m_files, &QFileSystemWatcher::fileChanged, &m_debounce, qOverload<>(&QTimer::start));
        connect(&m_debounce, &QTimer::timeout, this, &Wallpaper::refresh);
        connect(&m_job, &QFutureWatcher<QImage>::finished, this, [this] {
            const QImage image = m_job.result();
            if (!image.isNull()) m_image = image;
            m_prepared = true; // A missing wallpaper uses the solid fallback, without a retry loop.
            ++m_revision;
            emit ready();
            if (m_refreshPending) { m_refreshPending = false; refresh(); }
        });
        if (QDir(launchpadConfigDir()).exists()) m_files.addPath(launchpadConfigDir());
        refresh();
    }
    ~Wallpaper() override { m_job.waitForFinished(); }
    bool prepared() const { return m_prepared; }
    Q_INVOKABLE QString url() const {
        return m_image.isNull() ? QString() : QStringLiteral("image://wallpaper/%1").arg(m_revision);
    }
    QImage image() const { return m_image; }

    void refresh() {
        if (m_job.isRunning()) { m_refreshPending = true; return; }
        QFile config(launchpadConfigDir() + "/config.json");
        QString path;
        if (config.open(QIODevice::ReadOnly))
            path = QJsonDocument::fromJson(config.readAll()).object().value("wallpaper").toObject().value("path").toString();
        if (path.startsWith("file://")) path = QUrl(path).toLocalFile();
        const QFileInfo file(path);
        const QString key = path + QString::number(file.lastModified().toMSecsSinceEpoch());
        if (m_prepared && key == m_sourceKey) return;
        m_sourceKey = key;
        if (!m_files.files().isEmpty()) m_files.removePaths(m_files.files());
        if (file.isFile()) m_files.addPath(path);
        const QString cache = QStandardPaths::writableLocation(QStandardPaths::CacheLocation);
        m_job.setFuture(QtConcurrent::run([path, key, cache] { return prepare(path, key, cache); }));
    }

signals:
    void ready();

private:
    static void blur(QImage &image, int radius) {
        const int width = image.width(), height = image.height();
        QImage output(image.size(), QImage::Format_ARGB32_Premultiplied);
        for (int pass = 0; pass < 2; ++pass) {
            const int lines = pass ? width : height, length = pass ? height : width;
            auto pixel = [&](int line, int position) {
                return image.pixel(pass ? line : qBound(0, position, length - 1),
                                   pass ? qBound(0, position, length - 1) : line);
            };
            for (int line = 0; line < lines; ++line) {
                int r = 0, g = 0, b = 0;
                for (int i = -radius; i <= radius; ++i) {
                    const QRgb p = pixel(line, i); r += qRed(p); g += qGreen(p); b += qBlue(p);
                }
                const int count = radius * 2 + 1;
                for (int i = 0; i < length; ++i) {
                    output.setPixel(pass ? line : i, pass ? i : line, qRgb(r / count, g / count, b / count));
                    const QRgb old = pixel(line, i - radius), next = pixel(line, i + radius + 1);
                    r += qRed(next) - qRed(old); g += qGreen(next) - qGreen(old); b += qBlue(next) - qBlue(old);
                }
            }
            image.swap(output);
        }
    }

    static QImage prepare(const QString &path, const QString &key, const QString &cache) {
        if (!QFileInfo(path).isFile()) return {};
        QDir().mkpath(cache);
        const QString destination = cache + "/wallpaper-" + QCryptographicHash::hash(key.toUtf8(), QCryptographicHash::Sha256).toHex().left(24) + ".png";
        QImage cached(destination);
        if (!cached.isNull()) return cached;
        QImageReader reader(path);
        reader.setAutoTransform(true);
        if (reader.size().isValid()) reader.setScaledSize(reader.size().scaled(1600, 1000, Qt::KeepAspectRatio));
        QImage image = reader.read();
        if (image.isNull()) return {};
        image = image.scaledToWidth(800, Qt::SmoothTransformation).convertToFormat(QImage::Format_ARGB32_Premultiplied);
        blur(image, 13); blur(image, 10); blur(image, 7);
        image = image.scaledToWidth(1600, Qt::SmoothTransformation);
        QPainter painter(&image);
        painter.fillRect(image.rect(), QColor(0, 0, 0, 42));
        painter.end();
        image.save(destination, "PNG");
        const auto files = QDir(cache).entryInfoList({"wallpaper-*.png"}, QDir::Files, QDir::Time);
        for (int i = 4; i < files.size(); ++i) QFile::remove(files.at(i).absoluteFilePath());
        return image;
    }

    bool m_prepared = false, m_refreshPending = false;
    int m_revision = 0;
    QString m_sourceKey;
    QImage m_image;
    QFileSystemWatcher m_files;
    QFutureWatcher<QImage> m_job;
    QTimer m_debounce;
};

class WallpaperProvider : public QQuickImageProvider {
public:
    explicit WallpaperProvider(Wallpaper *wallpaper) : QQuickImageProvider(QQuickImageProvider::Image), m_wallpaper(wallpaper) {}
    QImage requestImage(const QString &, QSize *size, const QSize &) override {
        const QImage image = m_wallpaper->image();
        if (size) *size = image.size();
        return image;
    }
private:
    Wallpaper *m_wallpaper;
};
