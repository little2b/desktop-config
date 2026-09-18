# 个人 Niri / Clavis 桌面迁移配置

这个仓库保存独立 Dock、本机桌面设置及迁移资源。仓库当前为**公开**，新增快照不包含账号凭据或历史记录。Clavis 应用源码在
[little2b/quickshell 的 personal/fedora-niri 分支](https://github.com/little2b/quickshell/tree/personal/fedora-niri)。
两者配合恢复整套桌面。新增功能入口与当前启用状态见 [FEATURES.md](FEATURES.md)。`sources.lock.json` 固定了本快照对应的 Clavis 提交。

## 在同一台电脑上从 Fedora 换到 Arch

先完成 Arch 的基础安装、网络、显卡驱动及中文 UTF-8 locale，然后以日常桌面用户运行：

```bash
sudo pacman -Syu --needed git github-cli python curl
gh auth login
gh auth setup-git
gh repo clone little2b/desktop-config
cd desktop-config
./scripts/setup-arch.sh --same-hardware
```

脚本依次安装依赖、恢复配置、编译定制 Clavis、启用用户服务。使用已校验 SHA-256
的上游 Arch 安装器安装依赖，并保留自己的 Clavis 源码入口。AUR 构建和软件包下载
需要网络和时间；安装器可能请求 sudo。**不要在当前 Fedora 上执行 Arch 安装脚本。**

完成后在登录界面选择 **Niri** 会话。若没有登录管理器，可从 TTY 按 Arch 的 Niri
会话方式启动 `niri-session`。使用 `niri.service` 管理的会话，才能自动启动关联服务。

换了电脑或显示器时去掉 `--same-hardware`，显示器和设备绑定会留待重新设置；
同一台笔记本重装时使用该参数，可保留 200% 缩放、显示器排列、主屏和指标设备选择。

## 本次桌面行为

- 普通窗口使用 8 像素圆角、柔和阴影和 2 像素聚焦边框；设置类窗口默认浮动。
- 点击应用自己的最大化按钮后占满屏幕，保留浏览器标签栏与地址栏。
  顶栏自动收起，鼠标移到边缘可唤出；还原窗口后恢复显示。
- 最大化时收到新通知，中间组件短暂显示，约 7 秒后自动收起；遵守勿扰模式，
  通知侧栏已打开时不重复弹出。通知侧栏快捷键为 **Win + N**。
- 中间组件退出后撤下显示窗口，内容淡入完成后才启用背景模糊，避免留下壁纸轮廓。

这些效果需要 **Niri 26.04 或更新版本**，以及上游安装器提供的 Quickshell 背景模糊支持。
源码分支名虽然包含 `fedora`，迁移脚本会在 Arch 上重新编译原生模块并使用 Arch 配置。

## 先查看计划或分步恢复

```bash
python3 scripts/restore.py --same-hardware
# 上一条只显示计划，不写入文件。
./scripts/install-arch-dependencies.sh
./scripts/install-key-cli.sh
python3 scripts/restore.py --apply --same-hardware
./scripts/build-clavis.sh
./scripts/enable-services.sh
```

恢复前若目标桌面已经在运行，先停止 `clavis-shell.service`、`nyx-dock.service`、
`fcitx5-niri.service`、`nyx-theme-sync.path` 和 `nyx-theme-sync.service`。恢复程序会检查这一点并保留现有文件到
`~/.local/state/desktop-config-backups/`，不会清空整个配置目录。
可用 `--target-home /tmp/desktop-preview` 试装到临时目录。

源目录默认是 `~/.local/share/clavis-source`，也可用 `CLAVIS_SOURCE_DIR` 指定。
构建程序不覆盖含有未提交修改的源码。原生库必须在 Arch 上编译；仓库不含 Fedora
的 `.so`、可执行运行库或 Python 虚拟环境。构建并安装后，桌面入口指向这份源码。

## 已包含

| 部分 | 内容 |
|---|---|
| 独立 Dock | 悬停保持显示、右键操作菜单、应用页面左键启动/右键菜单、拖拽分组、固定顺序及外观设置 |
| 应用卸载 | Arch 的 pacman/AUR、Fedora 的 RPM 和 Flatpak 卸载确认；手动安装程序和网页应用显示处理提示 |
| 文件管理器/终端 | 默认 Nautilus，浅色背景和紫灰色 Papirus 衍生图标；保留 Dolphin、Alacritty/Konsole 的主题同步 |
| Niri | 快捷键、窗口规则、缩放与显示器布局、鼠标和光标配置 |
| Clavis | 主题、侧栏、桌面卡片、时间卡片位置、输入偏好、电源设置、沙坪坝天气及网盘功能开关 |
| 输入法 | Fcitx5 配置、雾凇拼音源码词库、自定义配置及一致性快照的用户词库 |
| 外观资源 | 当前壁纸、头像、Clavis 字体与许可证、天气图标包、GTK/终端主题 |
| 服务 | Clavis、剪贴板后端、独立 Dock、Fcitx5 和主题同步的用户服务 |
| 系统参考 | 原来的合盖行为、休眠延迟配置，仅供重新设置参考 |

字体与天气图标的许可证随资源保留。雾凇拼音许可证见 `rime/LICENSE.rime-ice`。
不包含通知/剪贴板历史、GitHub 凭据、SSH 密钥、RustDesk 连接密码或工作文档。
Microsoft Office/WPS 字体及其他软件的账号、数据和授权需要单独迁移。

## Arch 上需要重新确认

- 中文语言：在 `/etc/locale.gen` 启用 `zh_CN.UTF-8 UTF-8` 并运行 `sudo locale-gen`。
  Dolphin 包装脚本使用该 locale。
- 网络及蓝牙：按新系统的网络方案启用 NetworkManager/BlueZ；脚本不接管正在使用的网络服务。
- 休眠：先配置新系统的 swap、resume 与启动参数。`system-reference/` 不会自动覆盖 `/etc`，
  验证休眠后再从 Clavis 电源设置恢复合盖策略；不能照搬 Fedora 的引导设置。
- 键盘指示灯、功耗采样：安装依赖时没有自动授予额外设备或文件读取权限。
  普通输入法和 CPU 占用显示不依赖这些授权；需要相关功能时使用 key-cli/keytop 的授权方式。
- Dock 固定项会保留，但对应软件必须另外安装；例如浏览器、WPS、微信、QQ、RustDesk、Codex。
  安装后的 desktop ID 若不同，在 Dock 设置中重新选择对应应用。
- 网盘：已启用 rclone 前端；在设置 → 高级 → 网盘中重新添加服务并授权。仓库不包含 rclone 账号配置、令牌或网盘文件。
- RustDesk：重新安装后打开远程会话里的“缩放光标”，避免自适应画面下光标过大；连接凭据未上传。
- 首次启动 Fcitx5 会重新部署雾凇拼音，稍等词库构建完成。Arch 的 `librime` 已包含 Lua 插件。

## 后续修改和更新

这是 2026-09-18 更新的快照，Clavis 已合入作者 `ac388ac`，包含四圆液态动画、文件搜索、换算工具和顶栏媒体控件。保留最大化时顶栏自动收起、浏览器标签栏、
边缘唤出、通知短暂显示、圆角/阴影渲染与模糊残留修复，以及此前的侧栏、抽屉、
滚动、通知布局和天气测试隔离。后续修改 Clavis 源码推送到 `quickshell` 的定制分支；修改本机 Dock 或桌面偏好后，在本仓库收集当前设置并提交：

```bash
python3 scripts/capture-current.py --apply
python3 -m unittest discover -s tests -v
python3 scripts/restore.py --same-hardware
git add .
git commit -m '更新个人桌面配置'
git push
```

更新 Clavis 固定版本前，在独立源码目录验证新提交，再更新 `sources.lock.json`。
不要将包含真实凭据的目录添加到本仓库。迁移前若当前桌面又有调整，需先刷新快照。

`capture-current.py` 只收集明确的桌面设置、Dock 源码和卸载辅助程序；替换本机 Home 路径、
移除 API 密钥/令牌字段，并清空网盘账号绑定。它不会停止输入法，也不会新增当前
Rime 个人短语或用户数据库；仓库已有的词库快照保持不变。Clavis 源码必须先提交，快照才会
记录对应提交，避免新系统构建出不同的桌面。现有 Arch 专用服务和主题同步适配会保留。

应用卸载在 Arch 上使用 `pacman -R` 并保留确认步骤，AUR 安装的包也由 pacman 管理。
它不会绕过软件包依赖保护或删除 Flatpak 个人数据。应用并非由软件包管理器安装时，
菜单会给出安装位置和处理提示；不会猜测目录并递归删除。主题同步不依赖完整 Plasma
桌面，缺少 `plasma-apply-colorscheme` 时使用 KDE 标准颜色配置与刷新信号。

当前 CachyOS 快照使用 `niri-git`，包含 PipeWire SHM 屏幕共享支持。依赖脚本会在
配置的软件仓库提供该包时优先安装；普通 Arch 仓库没有该包时仍使用稳定版 Niri。

## 本次应用外观与网盘设置

- Nautilus 是默认文件管理器，GTK 4 样式位于 `config/gtk-4.0/reference-nautilus.css`。
  紫灰色图标位于 `share/icons/Clavis-Reference`，还需安装 Papirus 作为继承主题。
- `bin/apply-desktop-preferences` 恢复已收集的 GNOME 外观、图标视图和文件关联；
  `enable-services.sh` 会调用它，不导入整份 dconf 数据库。
- `rclone-quark.service` 和“夸克网盘”入口已保存，使用只读挂载和 5 GiB 磁盘缓存目标。
  新系统仍需自行配置 OpenList 及 rclone 的 `quark-openlist` WebDAV 连接。Cookie、密码、
  rclone 配置和缓存文件均不在快照内；挂载服务不会被恢复脚本自动启动。
- 新版 Spotlight 的文件搜索及换算需要 `sources.lock.json` 固定的 key-cli 源码。
  `install-key-cli.sh` 调用它自己的安装器部署到 `/usr/local`，优先通过图形密码框认证；
  不改设备权限、不启动服务。`bin/key` 与原生模块路径和当前安装保持一致。

## 验证范围

本仓库在 Fedora 上完成了配置校验和临时目录恢复测试，包括不同用户名/路径、原文件备份、
硬件配置选择及清单校验；没有在全新 Arch 安装中实际运行完整的软件包安装和图形会话。
`python3 -m unittest discover -s tests -v` 可重复运行文件恢复测试，不触碰当前桌面。
