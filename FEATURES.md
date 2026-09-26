# 当前桌面功能

此快照使用 Clavis 原生 Dock，准确源码版本见 `sources.lock.json`。

| 功能 | 入口或行为 |
| --- | --- |
| 应用菜单 | Dock 左侧九宫格，或 `qs -c clavis ipc call launchpad toggle` |
| 应用分组 | 拖动排序，悬停另一图标创建文件夹，支持重命名、移出和跨页拖动 |
| 菜单动画 | 打开/关闭淡入缩放、整页滑动，图标和壁纸预加载，页面缓存 |
| 原生 Dock | 悬停放大、固定应用、自动隐藏、窗口预览、文件夹和废纸篓 |
| 最小化 | 固定版本的 Niri Edge 提供缩放/Genie 动画及 HiDPI 修复 |
| Spotlight | 搜索应用、文件、剪贴板、壁纸及换算工具 |
| 设置入口 | Clavis 设置使用明确名称，并过滤不适合 Niri 的重复入口 |
| 顶栏 | 最大化自动隐藏，边缘唤出；打开应用菜单时保持活动应用区域稳定 |
| 灵动岛歌词 | `qs -c clavis ipc call keystone lyrics`，保留常驻模式和顶栏隐藏联动 |
| 文件管理器 | Nautilus 自定义浅色样式、紫灰色图标；KDE GTK 自动同步关闭 |
| 终端和输入法 | Kitty / Alacritty / Konsole 与 Fcitx5 的样式和壁纸配色同步 |
| 主题 | MacTahoe-light 图标，Noto Sans CJK 与 Google Sans Flex 字体选择 |
| 屏幕共享 | 固定 Niri 源码及 PipeWire SHM 兼容补丁，实际可用性也取决于应用和 portal |
| QQ 截图 | Ctrl+Alt+A 保留 QQ 标注；多屏兼容流程自动恢复显示器 |
| 网盘 | 保留入口和设置，账号在新电脑重新配置 |

旧版独立 Dock 和其卸载菜单不再作为当前桌面的安装内容。软件安装、凭据、系统服务
和硬件驱动需要在新电脑分别准备；迁移脚本不会自动授予额外设备读取权限。
