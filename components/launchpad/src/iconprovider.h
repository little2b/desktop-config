#pragma once
#include <QIcon>
#include <QImage>
#include <QMutex>
#include <QMutexLocker>
#include <QQuickImageProvider>
#include <QUrl>

// Decode on the GUI thread before opening; image requests only read cached pixels.
class IconProvider : public QQuickImageProvider {
public:
    IconProvider() : QQuickImageProvider(QQuickImageProvider::Image) {}

    void preload(const QStringList &names) {
        for (const auto &name : names) {
            {
                QMutexLocker lock(&m_mutex);
                if (m_images.contains(name)) continue;
            }
            QIcon icon = name.startsWith('/') ? QIcon(name) : QIcon::fromTheme(name);
            if (icon.isNull()) icon = QIcon::fromTheme("application-x-executable");
            QImage pixels = icon.pixmap(256, 256).toImage();
            if (pixels.isNull()) {
                pixels = QImage(128, 128, QImage::Format_ARGB32_Premultiplied);
                pixels.fill(QColor("#8b91a4"));
            }
            QMutexLocker lock(&m_mutex);
            m_images.insert(name, pixels);
        }
    }

    QImage requestImage(const QString &id, QSize *size, const QSize &requested) override {
        QImage image;
        {
            QMutexLocker lock(&m_mutex);
            image = m_images.value(QUrl::fromPercentEncoding(id.toUtf8()));
        }
        if (requested.isValid() && !image.isNull())
            image = image.scaled(requested.boundedTo(QSize(256, 256)), Qt::KeepAspectRatio, Qt::SmoothTransformation);
        if (size) *size = image.size();
        return image;
    }

private:
    QMutex m_mutex;
    QHash<QString, QImage> m_images;
};
