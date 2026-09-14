import QtQuick
import Quickshell
import Quickshell.Io

QtObject {
    id: root
    // Resolve the same generated palette as Clavis Common/Paths.qml.
    readonly property string dataHome: Quickshell.env("CLAVIS_DATA_HOME")
        || (Quickshell.env("XDG_DATA_HOME") || Quickshell.env("HOME") + "/.local/share") + "/clavis"
    readonly property string profile: Quickshell.env("CLAVIS_PROFILE") || "default"
    readonly property string profileHome: Quickshell.env("CLAVIS_PROFILE_HOME") || dataHome + "/profiles/" + profile
    property string colorsPath: (Quickshell.env("CLAVIS_GENERATED_HOME") || profileHome + "/generated") + "/clavis/colors.json"
    property bool loaded: false
    property var palette: ({background: "#0f1416", primary: "#88d0ec", on_background: "#dee3e6",
        on_surface: "#dee3e6", on_surface_variant: "#bfc8cd", outline_variant: "#40484c",
        surface_container_high: "#252b2d", tertiary: "#c6c2ea", error: "#ffb4ab"})

    // Match Appearance.colors.colLayer0Base: 99% background, 1% primary.
    readonly property color background: mix(palette.background, palette.primary, 0.99)
    readonly property color foreground: palette.on_background
    readonly property color muted: palette.on_surface_variant
    readonly property color primary: palette.primary
    readonly property color urgent: palette.error
    readonly property color outline: mix(palette.outline_variant, background, 0.4)
    readonly property color hover: alpha(palette.on_surface, 0.08)
    readonly property color focused: alpha(palette.primary, 0.12)
    readonly property color tooltipBackground: palette.surface_container_high
    readonly property color tooltipForeground: palette.on_surface

    function alpha(color, opacity) {
        const c = Qt.color(color);
        return Qt.rgba(c.r, c.g, c.b, Math.max(0, Math.min(1, opacity)));
    }
    function mix(first, second, weight) {
        const a = Qt.color(first), b = Qt.color(second);
        return Qt.rgba(a.r * weight + b.r * (1 - weight),
                       a.g * weight + b.g * (1 - weight),
                       a.b * weight + b.b * (1 - weight), 1);
    }
    property FileView colorFile: FileView {
        path: root.colorsPath
        preload: true
        blockLoading: true
        watchChanges: true
        onFileChanged: reloadDelay.restart()
        onLoaded: {
            try {
                const next = JSON.parse(text());
                for (const key of Object.keys(root.palette)) {
                    if (typeof next[key] !== "string" || !/^#[0-9a-fA-F]{6}$/.test(next[key]))
                        throw new Error("Invalid theme color: " + key);
                }
                root.palette = Object.assign({}, root.palette, next);
                root.loaded = true;
            } catch (error) {
                // Keep the last complete palette while a theme is being regenerated.
                console.warn("Dock theme:", error);
            }
        }
    }
    property Timer reloadDelay: Timer {
        interval: 100
        onTriggered: root.colorFile.reload()
    }
}
