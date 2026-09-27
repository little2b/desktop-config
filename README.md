# 个人 CachyOS / Arch · Niri / Clavis 桌面

这个公开仓库保存当前桌面的可迁移配置、主题资源和安装脚本。桌面源码位于
[little2b/quickshell](https://github.com/little2b/quickshell/tree/personal/cachyos-niri)，
本仓库通过 `sources.lock.json` 固定 Clavis、定制 Niri、key-cli 和 MacTahoe 图标的版本。

## 在另一台电脑上安装

目标系统需要先装好 **CachyOS 或 Arch Linux**、网络和显卡驱动。以日常用户运行：

```bash
sudo pacman -Syu --needed git python curl
git clone https://github.com/little2b/desktop-config.git
cd desktop-config
./scripts/setup-arch.sh
```

仓库公开，无需登录 GitHub。图形会话里的安装步骤优先使用 `pkexec` 密码框；
没有图形认证环境时在终端输入 sudo 密码。不要以 root 身份运行整个安装脚本。
软件包下载、Niri 的 Rust 编译和 Clavis 的 Qt 编译需要时间、网络以及数 GB 可用磁盘。

**换电脑使用上面的默认命令，不加 `--same-hardware`。** 显示器布局、主屏选择、
设备指标绑定及原机器的 GTK/X11 DPI 将重置，进入桌面后按新显示器设置缩放。
只有同一台电脑重装、且显示器不变时，才使用 `./scripts/setup-arch.sh --same-hardware`。

建议在新机器的 TTY 或其他桌面会话中安装。完成后退出当前会话，在登录界面选择
**Niri**；没有登录管理器时从 TTY 运行 `niri-session`。脚本不配置自动登录或磁盘休眠。

安装流程依次完成：

1. 校验快照并显示恢复计划，安装 Arch 依赖和固定版本的 key-cli。
2. 备份目标电脑已有的同名文件，再恢复桌面设置。
3. 编译固定版本的 `StatIndet/niri-edge` 并应用本仓库补丁；保留 Genie 最小化、
   HiDPI 坐标修复和 PipeWire SHM 屏幕共享修复。
4. 安装固定提交的 MacTahoe 图标主题，编译并安装 Clavis 原生模块和 Niri Launchpad。
5. 校验 Niri 配置，启用 Clavis、剪贴板、Fcitx5 和主题同步服务。
   旧独立 `nyx-dock.service` 会被关闭，避免出现两个 Dock。

## 当前快照包含什么

| 部分 | 内容 |
| --- | --- |
| 原生 Dock | 固定应用、顺序、大小、放大、自动隐藏、窗口预览和最小化设置 |
| 应用菜单 | 基于 cccp00-cup 的 macOS Launchpad，适配 Niri 覆盖层、Clavis 壁纸、图标预加载和统一出场动画；支持 Dock 与单击 Win 呼出，沿用 `config/clavis/launchpad.json` 分组 |
| 顶部组件 | 最大化时自动隐藏、边缘唤出、通知短暂显示、常驻歌词及菜单打开时的顶栏稳定处理 |
| 文件管理器 | 默认使用 Nautilus，保留浅绿色界面、紫灰色 Clavis-Reference 图标，以及防止 KDE GTK 同步覆盖的设置；安装脚本不再安装 Dolphin |
| 图标与字体 | Clavis 使用 MacTahoe-light；保留 Noto Sans CJK、Google Sans Flex 等字体选择和字体配置 |
| 终端 | Kitty、Alacritty 和 Konsole 的配色、透明度、字体、按键与主题同步 |
| Niri | 快捷键、窗口规则、鼠标、光标、模糊和最小化动画配置 |
| 输入法 | Fcitx5、雾凇拼音、跟随壁纸的候选框主题；保留仓库已有 Rime 快照 |
| 壁纸与组件 | 当前壁纸、头像、天气位置、桌面卡片和侧栏设置 |
| QQ / Manggo | 截图与翻译的辅助脚本、Niri 快捷键和 portal 注册 |
| 网盘 | 夸克网盘入口和挂载服务定义；账号在新机重新配置 |
| 本机兼容参考 | 微信/QQ 与 WPS 的 XWayland/输入法启动脚本、微信通知桥接、音量恢复、服务片段及 ChatGPT 启动修复 |

Dock 与应用菜单只保存应用入口，不会安装所有固定的软件。Chrome、QQ、微信、
WPS、Codex、腾讯会议等需另行安装；安装后的 desktop ID 不同时重新固定即可。
未安装的应用在菜单中隐藏，安装后会按保存的布局恢复。

没有上传登录密码、Cookie、API 密钥、SSH 密钥、GitHub/Codex 凭据、通知或剪贴板历史。
Rclone / OpenList 等账号需要在新电脑重新授权；网盘挂载服务不会自动启动。
字体和图标资源的许可证随资源保留；MacTahoe 从其固定的公开源码提交安装。

## 预览与分步安装

```bash
# 只显示计划，不写配置
python3 scripts/restore.py

# 试装到临时目录，不影响当前桌面
python3 scripts/restore.py --target-home /tmp/clavis-preview --apply

# 与 setup-arch.sh 相同的分步流程
./scripts/install-arch-dependencies.sh
./scripts/install-key-cli.sh
python3 scripts/restore.py --apply
./scripts/build-niri.sh
./scripts/install-icon-theme.sh
./scripts/build-clavis.sh
./scripts/build-launchpad.sh
./scripts/install-launchpad-keybinding.sh
./scripts/enable-services.sh
```

恢复程序会检查目标桌面是否正在运行。若需要覆盖正在使用的配置，应先退出 Niri，
或停止它列出的 Clavis、输入法和主题同步服务。旧文件保存在
`~/.local/state/desktop-config-backups/`，不会清空整个配置目录。

Clavis 源码默认放在 `~/.local/share/clavis-source`；用 `CLAVIS_SOURCE_DIR` 可以另选目录。
Niri 源码默认放在 `~/.local/share/niri-desktop-source`；用 `NIRI_SOURCE_DIR` 可以另选目录。
脚本拒绝覆盖已有的不同版本或本地修改。Niri 安装在用户目录，系统软件包保留，
运行中的 compositor 不会被脚本强制重启。

应用菜单源码和 GPL-3.0 许可证在 `components/launchpad/`，上游出处记录于该目录的
`UPSTREAM.md`。`clavis-launchpad.service` 在登录 Niri 时后台预加载应用、图标与壁纸；
它与 Clavis 共用布局文件，已有文件夹和排序不需要手动重建。安装/卸载应用后会刷新列表。
若需切回内置菜单，把 `~/.config/clavis/launchpad-backend.json` 的 `external` 改为 `false`，
再执行 `systemctl --user disable --now clavis-launchpad.service`。

Win 快捷键由 keyd 将左右 Win 的单击映射到 F13 的硬件键码；标准 XKB 映射将它解释为
`XF86Tools`，因此 Niri 同时兼容 `XF86Tools` 和 `F13`，打开应用菜单。
Win 与其他按键组合时保持原来的修饰键功能。单击需在 300ms 内松开，长按不打开菜单。
`install-launchpad-keybinding.sh` 安装 `/etc/keyd/clavis-launchpad.conf` 并启用 keyd；
如已有其他 keyd 配置，脚本会停止，避免覆盖已有映射。停用映射可运行
`pkexec systemctl disable --now keyd.service`。其他桌面若要使用同一单击动作，需绑定
键盘映射实际产生的 `XF86Tools`（部分映射为 `F13`）。

## 新机器上的差异

- 本快照包含 `window-minimize-effect "genie"`，必须完成 `build-niri.sh` 后才使用该配置。
  普通发行版 Niri 可能尚不支持这个选项，不能只复制配置而跳过构建。
- 启用中文 UTF-8 locale（通常是 `zh_CN.UTF-8`）。网络、蓝牙、声卡驱动和休眠能力
  由新系统设置；除上述 keyd 规则外，仓库不自动覆盖 `/etc`、bootloader、resume 或硬件授权。
- 新电脑需要重新确认显示器缩放、布局、鼠标、功耗模式和合盖设置。
  `system-reference/` 保存原机器的电源、设备和应用兼容配置参考。
- QQ、微信、腾讯会议和 WPS 的专用二进制兼容环境不随配置上传。
  QQ 的 `Ctrl+Alt+A` 辅助流程会临时关闭其他屏幕；完成、取消或超时后恢复。
  QQ 应用内的截图按钮不会调用此流程。
- `~/.local/bin` 需要位于 PATH 前部；Niri 配置和服务使用已恢复的包装入口。

`system-reference/user-home/` 按 `config`、`bin`、`share` 保存额外的本机配置，Home
路径使用 `@HOME@` 占位符。它们纳入校验清单，但不会由 `restore.py` 自动安装或启用。
聊天/WPS 启动器依赖另行准备的定制 XWayland 二进制及显示器缩放设置；音量服务对应
JBL PS3500；图标刷新服务保留了旧独立 Dock 的调用，仅作历史配置参考。
`system-reference/chatgpt/` 保存本地启动补丁和 Pacman 钩子，仅匹配已核验的
`26.924.22138` 版本与归档哈希。其他版本使用前需要重新判断，仓库不包含应用归档、
登录数据或补丁运行时的备份。

## 刷新快照

先提交并推送 Clavis 源码，再运行：

```bash
python3 scripts/capture-current.py --apply
python3 -m unittest discover -s tests -v
python3 scripts/restore.py
git add .
git commit -m '更新个人桌面配置'
git push
```

采集程序只收集明确的桌面配置，将 Home 路径替换成安装时展开的占位符，并清空凭据字段。
它不停止输入法，也不新增当前 Rime 学习记录、账号库或应用数据。定制 Niri 的源码补丁
在 `patches/niri-desktop.patch`；`sources.lock.json` 同时记录补丁的 SHA-256。

## 验证范围

Niri Launchpad 的构建、交互回归测试、应用/分组模型测试和进程通信测试均通过；
已在当前 Niri 会话验证覆盖层显示、Dock 调用、关闭后的焦点恢复及原有分组保留。
Clavis 接入通过改动范围的 QML 检查，存在 3 条 QProcess 枚举类型的工具提示。
迁移仓库的 20 项测试及 ShellCheck 通过。
已从远程获取固定的 Niri 源码并验证补丁可完整应用，安装器下载的 SHA-256 也已核对。
在临时目录验证了不同用户名、含空格 Home 路径、原文件备份、原生 Dock 分组、主题
及硬件重置后的恢复结果；恢复后的 Niri 配置通过当前定制版的语法校验。
**尚未在另一台全新电脑实际执行完整安装和图形登录**；下载源、AUR 构建与新硬件驱动
仍会影响安装结果。验证命令均不安装软件或修改当前桌面。
