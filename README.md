# Remote Input Board 📱→💻

**用手机浏览器给 Linux 电脑远程输入文字。** 电脑上跑一个小服务，手机打开网页输入文字，点发送就通过 [fcitx5-text-injector](https://github.com/zhh7ce/fcitx5-text-injector) 走 fcitx5 的 `commitString()` 提交到电脑当前光标处。

**为什么不用 wtype/ydotool 打字**：它们模拟的是按键事件，一旦系统开着中文输入法，按键会被输入法拦截并重新组字，导致输入乱掉。fcitx5 模块直接把成品文字提交给焦点应用，**输入法开着也正常**。回车仍由 wtype 发出（`commitString()` 产生不了真实按键）。

当前为 Linux/Wayland 精简版，只保留**文字发送**能力（无长连接，纯 HTTP：token 与内容随请求发送）；另有一个可开关的小功能：输入框为空时点发送可在电脑上触发回车。鼠标触控板、快捷指令等 Windows 版功能暂未移植。

每台手机**配对一次**：首次连接输入 **PIN 码**（手机锁屏样式的数字键盘点按，不弹系统键盘），服务端长期记住该设备，之后手机 IP 变化或服务重启都免输；可选 HTTPS 加密传输。

---

### 环境要求

- Linux + **Wayland** 会话 + **fcitx5** 输入法框架
- 安装 `wtype`（仅远程回车用）：

```bash
# Debian / Ubuntu
sudo apt install wtype
# Arch
sudo pacman -S wtype
# Fedora
sudo dnf install wtype
```

- 安装 **fcitx5-text-injector** 模块（文字输入用）。它是一个 fcitx5 addon，需要单独构建安装：

```bash
git clone https://github.com/zhh7ce/fcitx5-text-injector.git
cd fcitx5-text-injector/packaging/arch
makepkg -si
# 装好后重启 fcitx5，让模块加载并创建 socket
fcitx5 -rd
```

装好后应能看到 socket 文件，并能 ping 通：

```bash
ls -la "$XDG_RUNTIME_DIR/text-injector.sock"
echo '{"type":"ping"}' | socat - UNIX-CONNECT:"$XDG_RUNTIME_DIR/text-injector.sock"
# {"pong":true}
```

> 服务进程需要能访问你的图形会话（`WAYLAND_DISPLAY`、`XDG_RUNTIME_DIR`）。在桌面会话里启动，或用 systemd --user 服务，通常都能自动继承。模块若在 fcitx5 配置里改了 socket 路径，用 `TEXT_INJECTOR_SOCKET` 告诉本服务。

### Arch Linux 安装（PKGBUILD）

仓库自带滚动打包脚本，一条命令构建并安装：

```bash
git clone https://github.com/zhh7ce/remote-input-board.git
cd remote-input-board/packaging/arch
makepkg -si
```

安装后得到（遵循 Linux FHS，配置与数据按 XDG 放在用户目录）：

| 路径 | 内容 |
|------|------|
| `/usr/bin/remote-input-board` | 启动服务（等同 `python3 -m py_remote_input`） |
| `/usr/bin/remote-input-board-generate-cert` | 生成自签 HTTPS 证书到配置目录 |
| `/usr/bin/remote-input-board-rebuild-stats` | 从历史重建累计字数 |
| `/usr/lib/python3.x/site-packages/py_remote_input/` | 程序本体（含页面模板） |
| `/usr/lib/systemd/user/remote-input-board.service` | 用户服务，`systemctl --user enable --now remote-input-board` 启用 |

依赖 `python` 与 `wtype`（由 pacman 自动安装）。**文字输入还额外需要 fcitx5-text-injector 模块**——它尚未进任何仓库，所以没写进 `depends`（否则本包会装不上），请按上面的步骤单独构建安装。`openssl`、`systemd` 为可选依赖。

> **打包取的是本地工作树，不联网**：`PKGBUILD` 的 `source=()` 为空，`prepare()` 直接从仓库根目录（`$startdir/../..`）复制源码，所以在自己的 checkout 里改完代码就能立刻 `makepkg -f`，不必先 push 到 GitHub。代价是打出来的包**包含未提交的改动**——要分享给别人就先 commit（`pkgver()` 报的是当前 HEAD 的 `rN.gHASH`，不会体现未提交内容）。已在 `packaging/arch/` 下留下的旧 GitHub 克隆会在每次 `prepare()` 时被清掉，不会串味。

### 快速开始（源码方式）

纯标准库实现，无需安装依赖，直接跑：

```bash
python3 -m py_remote_input
# 或
uv run python -m py_remote_input
```

终端会打印手机访问地址和 **PIN 码**：

```
http://192.168.x.x:3210
PIN required on first connect: 482915
```

电脑和手机连同一个 WiFi，手机浏览器打开页面，先在锁屏界面点按数字键输入终端里的 PIN，解锁后才能发送文字。发送前记得在电脑上点一下目标窗口，把光标放好。

页面底部有两个可选项：「回车直接发送（Shift+回车换行）」和「无文字时点发送 = 在电脑上按回车」——后者勾选后，输入框留空点发送就会在电脑上触发一次 Enter（比如用来发送 IM 消息、确认对话框），选择会记住在本手机上。发送失败以底部短暂浮层提示，成功就是把输入框清空。**多行文字原样送出**：换行走的是 fcitx5 文本提交，等同粘贴一个换行字符，**不会替你按下回车**（需要回车就用空发送功能显式触发）。没有连接状态显示——未配对时就是全屏 PIN 锁屏，token 失效会自动回到锁屏。

### PIN 码与设备配对

采用 KDE Connect 式的"配对一次、长期信任"模型，正常使用中**每台手机只需输入一次 PIN**：

- 首次启动会在配置目录（`~/.config/remote-input-board/pin.txt`，权限 600）自动生成 PIN，之后一直复用；终端每次启动都会打印当前 PIN
- 想自己指定：`PIN_CODE=135790 python3 -m py_remote_input`（纯数字）
- 手机首次输对 PIN 后拿到随机 token 存在浏览器本地；服务端把设备记到配置目录的 `trusted_devices.json`（只存 token 的 SHA-256，权限 600）。**之后手机 IP 变化（DHCP、私人无线局域网地址）或服务重启都不再要求 PIN**，直到主动取消配对
- 取消配对：手机页面右上角「锁定」按钮（只取消本机），或删除 `~/.config/remote-input-board/trusted_devices.json`（所有手机重新配对）
- 安全机制：PIN 常量时间比较；token 为 32 字节随机数，服务端只存哈希；同一 IP 连续输错 5 次 PIN 会被限流（15 秒起指数退避到 5 分钟）。token 与 IP 解绑后持有者即可访问，不可信网络请务必启用 HTTPS
- HTTP 接口同样严格：携带无效 token 的请求一律 401 拒绝；GET 链接里的 token 与文本不会写入服务端日志（访问日志已整体关闭）

### 配置

| 你想干嘛 | 怎么弄 |
|---------|-------|
| 改端口 | `PORT=3219 python3 -m py_remote_input` |
| 指定 PIN | `PIN_CODE=135790 python3 -m py_remote_input` |
| 局域网访问 | 确保防火墙放行 TCP 3210（HTTP）和 3211（HTTPS） |
| 启用 HTTPS | 配置目录放 `cert.pem`+`key.pem`（`remote-input-board-generate-cert` 或 `scripts/generate_cert.sh` 生成）即在 **3211** 端口额外开启 HTTPS，与 3210 的 HTTP 同时可用；可用 `HTTPS_PORT` 改端口、`SSL_CERT_FILE`/`SSL_KEY_FILE` 改证书路径（见下） |

### HTTPS（可选）

证书存在时 **HTTP 和 HTTPS 同时提供**：HTTP 始终在 `PORT`（默认 3210），HTTPS 在 `HTTPS_PORT`（默认 **3211**），两者共用同一套 PIN 和配对信息（在一个地址配对过，另一个也免 PIN）。手机用 `http://IP:3210` 或 `https://IP:3211` 打开都行。明文 HTTP 中 PIN 和输入内容在网络上可见——**不可信网络请用 https 地址并考虑防火墙只放行 3211**。

**方式一：自签证书（适合局域网 IP 访问，零成本）**

一键脚本会自动探测本机局域网 IP 并把它写进证书 SAN（也可手动传 IP），证书生成在配置目录 `~/.config/remote-input-board/`：

```bash
# 已安装（PKGBUILD）：
remote-input-board-generate-cert
# 源码方式：
scripts/generate_cert.sh
# 或指定 IP：scripts/generate_cert.sh 192.168.10.172
```

生成后**正常启动即可，不用设任何环境变量**——启动后会看到日志同时列出 http:// 和 https:// 地址：

```bash
python3 -m py_remote_input
# INFO Remote input server is running. HTTP on port 3210. HTTPS on port 3211.
```

可选环境变量（不设就用括号里的默认值）：

```bash
HTTPS_PORT=8443 \
SSL_CERT_FILE=/path/cert.pem SSL_KEY_FILE=/path/key.pem \
  python3 -m py_remote_input
# 证书路径语义同 shell 的 ${SSL_CERT_FILE:-<配置目录>/cert.pem}，设了才覆盖默认值
```

然后用 `https://` + **HTTPS 端口** + 证书里那个 IP 访问（如 `https://192.168.10.172:3211`）。注意：

- 证书只对生成时写入的 IP 有效；用别的 IP 或主机名访问仍会报警告，换网络/IP 后重新跑一次脚本即可
- 手机首次打开会有红色证书警告，这是自签证书的正常现象：
  - **安卓 Chrome / Edge**：「高级 → 继续前往（不安全）」，点一次后页面即放行
  - **iPhone Safari**：「显示详细信息 → 访问此网站」
  - **安卓 Firefox** 用的是自带证书库，个别版本不给"继续"入口，建议直接换 Chrome
- 想彻底消除警告（不是点"继续"而是真信任）：把 `cert.pem` 传到手机安装——安卓在「设置 → 安全 → 加密与凭据 → 安装证书 → CA 证书」；iOS 安装描述文件后还要到「设置 → 通用 → 关于本机 → 证书信任设置」里启用
- 默认路径/环境变量只找到一个文件（有 cert 没 key，或反过来）时服务会直接报错并指出缺哪个
- 常见误区：启动日志只有 `HTTP on port 3210.` 没有 `HTTPS on port 3211.`，说明配置目录没有 `cert.pem`/`key.pem`，此时访问 3211 会连接失败——跑一次 `remote-input-board-generate-cert` 再重启即可
- 注意协议和端口要配对：3210 只说 HTTP（用 https:// 访问会报错），3211 只说 HTTPS（用 http:// 访问会报错）

**方式二：受信任证书（需要域名）**

如果你有域名指向这台机器，可以用 Caddy 自动签发 Let's Encrypt 证书并反代到 3210，或用 certbot 拿到证书后同样通过 `SSL_CERT_FILE`/`SSL_KEY_FILE` 加载。纯内网 IP 无法申请公网受信任证书。

### 文件位置（XDG 目录）

从任意目录启动都可以，运行时文件不再写在工作目录（旧版本放在工作目录的文件会在首次启动时**自动迁移一次**）：

| 文件 | 位置 | 内容 |
|------|------|------|
| `pin.txt` | `~/.config/remote-input-board/`（700 目录、600 文件） | 自动生成的 PIN（也可用 `PIN_CODE` 覆盖而不生成文件） |
| `trusted_devices.json` | 同上 | 已配对设备（只存 token 的 SHA-256，600；删除即全部重新配对） |
| `cert.pem` / `key.pem` | 同上 | HTTPS 证书（可选） |
| `logs/server.log` | `~/.local/share/remote-input-board/logs/` | 服务日志 |
| `logs/history/YYYY-MM-DD/HH.log` | 同上 | 发送历史，按天+小时分文件，一行一条 JSON（`kind=text` 为文字、`kind=key` 为按键） |
| `logs/stats.json` | 同上 | 累计字数备份（只统计文字，按键不计字；内存缓存约 5 分钟落盘） |

目录遵循 XDG：设置了 `XDG_CONFIG_HOME`/`XDG_DATA_HOME` 时随之变化；也可用 `REMOTE_INPUT_CONFIG_DIR`、`REMOTE_INPUT_DATA_DIR` 单独覆盖。

### 实现说明

- 除页面和 `/api/auth` 外，所有 HTTP 接口都要带 token；token 由 `POST /api/auth` 用 PIN 换取，持久有效、不绑 IP，`POST /api/logout` 可注销本机。token 携带方式两种等价：`Authorization: Bearer <token>` 头，或 URL 查询参数 `?token=<token>`
- 发送走无状态的 HTTP 请求，没有 WebSocket/长连接：
  - `POST /api/type`，body `{"text":"..."}`（页面内部用法，长度不限）
  - `GET /api/type?token=...&text=...`（**链接直发**：token 和文本全在链接里，适合快捷指令/书签/curl；限 600 字，换行用 `%0A`）
  - `GET /api/type?token=...&key=Return`（触发回车）
  - `GET /api/ping?token=...`（校验配对状态）
- 打开 `http://IP:3210/?token=<token>` 可**跳过 PIN 直接配对**（页面把 token 存入浏览器后自动从地址栏抹掉）；把这条链接发给新手机即完成授权
- 空发送回车：HTTP body `{"key":"Return"}`；服务端有按键白名单（当前仅 `Return`），非白名单返回 400。历史中记为 `{"kind":"key","key":"Return"}`，不计入累计字数
- 服务端通过 Unix socket 让 fcitx5-text-injector 执行 `commit`，把文本作为成品文字提交给焦点应用，**因此不受输入法干扰**。**换行符原样提交**：`commitString()` 交出去的是字符而不是按键事件，所以多行内容等同粘贴，不会提前触发提交/执行。需要回车时用空发送回车功能，它才会真的走 `wtype -k Return`
- 提交前只做一处归一：CRLF 和裸 CR 统一转成 LF（裸 CR 进了文本框在多数应用里显示成乱码）
- 单行输入框（如搜索栏）本身不接多行，收到带换行的提交时各应用表现不一——这属于目标应用的既有行为，本服务不改写内容
- 回车走 wtype 而非 fcitx5：`commitString()` 只能交文本，产生不了真实按键事件
- socket 连不上（模块没装、fcitx5 没开）或 wtype 未安装时，接口返回明确的错误提示，手机页面可见
- 长文本一次性通过 socket 发送，不受命令行长度限制（这是相对 wtype 打字的一个额外好处）

### 技术栈

`Python 标准库（http.server）` `fcitx5-text-injector（Unix socket）` `wtype（仅回车）` `原生 JS（无框架）`
