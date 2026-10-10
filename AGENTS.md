# AGENTS.md

## 项目简介

远程输入板（Linux 版） — 用手机浏览器作为 Linux 电脑的远程文本输入面板。当前为精简版，核心是**文字发送**：手机网页发送文字，电脑端通过 **fcitx5-text-injector** 模块（Unix socket → fcitx5 `commitString()`）提交到当前光标处。选它而非 wtype/ydotool 的原因：后两者模拟按键事件，会被中文输入法拦截重组，导致输入乱掉；`commitString()` 直接交成品文字，**输入法开着也正常**。通信为**无状态纯 HTTP，无 WebSocket 长连接**：token 与文本可同置一条链接（`GET /api/type?token=...&text=...`），也可 Bearer 头 + POST body。另有可选的**空发送回车**：前端复选框控制（localStorage `remoteInput.enterWhenEmpty`），勾选后输入框为空点发送即按一次 Enter——回车必须是真实按键，`commitString()` 产生不了，所以**这一条仍走 `wtype -k Return`**。

- **服务端口**: 3210（HTTP）/ 3211（HTTPS）
- **Python 包**: `py_remote_input`（纯标准库，无第三方运行时依赖）
- **入口**: 源码 `python3 -m py_remote_input`（或 `uv run ...`）；安装后为命令 `remote-input-board`（pyproject `[project.scripts]`）
- **系统依赖**: `fcitx5` + **fcitx5-text-injector** addon（文字输入，需单独构建安装并重启 fcitx5）、`wtype`（仅远程回车，Arch: pacman；Debian: apt）；运行在 Wayland 会话中，需要能访问 `WAYLAND_DISPLAY` / `XDG_RUNTIME_DIR`
- **注入 socket 路径**: 由 fcitx5 模块自己创建，默认 `$XDG_RUNTIME_DIR/text-injector.sock`（无 `XDG_RUNTIME_DIR` 时回落 `/tmp/text-injector-<uid>.sock`）。本服务用 `injector_socket_path()` 镜像同一套规则，`TEXT_INJECTOR_SOCKET` 可覆盖（对应模块配置项 `SocketPath`）
- **访问控制**: KDE Connect 式配对。手机首次过 PIN 锁屏（纯点按数字键盘）后获得持久 token，服务端把设备哈希记入配置目录 `trusted_devices.json`，之后 IP 变化/重启都免 PIN，直到 `/api/logout` 或删除该文件。PIN 来自 `PIN_CODE` 环境变量，否则读配置目录 `pin.txt`，再没有就自动生成 6 位数字（0600）并打印到启动日志
- **文件布局（XDG）**: 配置（pin.txt / trusted_devices.json / cert.pem / key.pem）在 `$XDG_CONFIG_HOME/remote-input-board`（默认 `~/.config/...`，目录 0700）；数据（logs/ 含 server.log、history、stats.json）在 `$XDG_DATA_HOME/remote-input-board`（默认 `~/.local/share/...`）。`REMOTE_INPUT_CONFIG_DIR` / `REMOTE_INPUT_DATA_DIR` 可覆盖。路径逻辑集中在 `py_remote_input/paths.py`，`serve()` 启动时先 `ensure_app_dirs()` 再 `migrate_legacy_files()`（旧 CWD 文件仅迁移一次）
- **Arch 打包**: `packaging/arch/PKGBUILD`（`remote-input-board-git`，`source=()` + 从 `$startdir/../..` 即**当前工作树**复制源，不再 clone GitHub，同 fcitx5-text-injector 的做法；PEP517 wheel + installer）；`packaging/systemd/remote-input-board.service` 装到 `/usr/lib/systemd/user/`；scripts/ 两个脚本装为 `/usr/bin/remote-input-board-generate-cert`、`/usr/bin/remote-input-board-rebuild-stats`

开机自启动由随包安装的 user unit 提供（不默认启用）：`systemctl --user enable --now remote-input-board.service`。

---

## 运行与验证

```bash
# 启动（配置在 ~/.config/remote-input-board，数据在 ~/.local/share/remote-input-board）
python3 -m py_remote_input
# Arch 安装后：remote-input-board，或 systemctl --user enable --now remote-input-board

# 测试
python3 -m unittest discover -s tests

# 验证接口（/api/* 除 auth 外都要 Bearer token）
curl -s http://127.0.0.1:3210/api/auth-info
TOKEN=$(curl -s -X POST http://127.0.0.1:3210/api/auth -H 'Content-Type: application/json' \
  -d '{"pin":"<启动日志里的PIN>"}' | python3 -c 'import sys,json;print(json.load(sys.stdin)["token"])')
curl -s -H "Authorization: Bearer $TOKEN" http://127.0.0.1:3210/api/stats
curl -s -X POST http://127.0.0.1:3210/api/type -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -d '{"text":"你好"}'
# 空发送回车（等价前端勾选复选框后的行为）：
curl -s -X POST http://127.0.0.1:3210/api/type -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -d '{"key":"Return"}'
# 链接直发（token 与文本全在 URL 里，适合快捷指令/书签）：
curl -sG http://127.0.0.1:3210/api/type --data-urlencode "token=$TOKEN" --data-urlencode "text=你好"
# 校验配对：
curl -s "http://127.0.0.1:3210/api/ping?token=$TOKEN"

# 排查文字通道：确认 fcitx5-text-injector 的 socket 在并应答
ls -la "$XDG_RUNTIME_DIR/text-injector.sock"
echo '{"type":"ping"}' | socat - UNIX-CONNECT:"$XDG_RUNTIME_DIR/text-injector.sock"   # {"pong":true}
```

## 关键文件说明

| 文件 | 作用 |
|------|------|
| `py_remote_input/templates/index.html` | 前端页面（单文件，极简：输入框 + 发送 + 选项 + 本地记录；无状态条/累计字数 UI/WebSocket——未配对由全屏锁屏承担，token 失效 401 自动回锁屏；发送失败走底部 toast，成功以清空输入框为反馈。textarea 的内容**原样发送**，多行不再被改写） |
| `py_remote_input/server.py` | HTTP 服务入口（`build_handler` 注入 `type_text` 与 `press_key`，解析 query 传给路由；`serve()` 组装 XDG 路径、迁移、日志、双端口；`log_message` 整体静默，防止 URL 里的 token/文本进日志） |
| `py_remote_input/paths.py` | XDG 路径：`config_dir()`/`data_dir()`/`ensure_app_dirs()`/`migrate_legacy_files()`；覆盖变量 `REMOTE_INPUT_CONFIG_DIR`/`REMOTE_INPUT_DATA_DIR` |
| `py_remote_input/web.py` | HTTP 路由 + 请求处理（auth / type / key / ping / stats）；token 接受 `Authorization: Bearer` 头或 `?token=` 查询参数；`ALLOWED_REMOTE_KEYS={"Return"}` 为远程按键白名单；`MAX_GET_TEXT_CHARS=600` 限制 URL 直发长度 |
| `py_remote_input/auth.py` | PIN 加载与限流；trusted-device 配对：32 字节随机 token、服务端只存 SHA-256、落盘 `trusted_devices.json`（0600）、**不绑 IP、重启不失效**、`revoke()` 取消配对 |
| `py_remote_input/typer.py` | 输入通道，**两条**：`type_text(text)` 连 `text-injector.sock` 发 `{"type":"commit","text":...}` 由 fcitx5 提交，**换行原样保留**（`commitString()` 交的是字符而非按键事件，所以多行等同粘贴、不会替你按回车；`normalize_line_endings()` 只把 CRLF/裸 CR 归一成 LF）；`press_key(keysym)` 按 `ALLOWED_KEYSYMS` 白名单校验后执行 `wtype -k <keysym>`（回车必须是真实按键，`commitString()` 给不了），`press_return()` 为其便捷封装。异常：`TextInjectorUnavailableError`（socket 连不上）、`TextInjectorError`（模块回 `success:false`）、`WtypeNotFoundError` |
| `py_remote_input/stats.py` | 字数统计存储 |
| `py_remote_input/logger.py` | 日志（同时输出 stdout 和文件） |
| `scripts/rebuild_stats.py` | 从 history 重建 stats.json（默认读写 data 目录；安装后为 `/usr/bin/remote-input-board-rebuild-stats`） |
| `scripts/generate_cert.sh` | 生成自签证书到配置目录（安装后为 `/usr/bin/remote-input-board-generate-cert`） |
| `packaging/arch/PKGBUILD` | Arch VCS 包（`remote-input-board-git`）：`source=()`，源由 `prepare()` 从 `$_repo="$startdir/../.."`（本仓库根目录）复制，**不联网 clone**；`pkgver()` 仍读本地 git 出 `rN.gHASH`。PEP517 build wheel + installer 入包、check() 跑 unittest。`depends` 只有 `python`/`wtype`——fcitx5-text-injector 未进任何仓库，写进 depends 会让本包装不上，故列为 `optdepends` 并在注释里说明必须单独构建。注意：打的是**当前工作树**（含未提交改动），对外分享前先 commit |
| `packaging/systemd/remote-input-board.service` | systemd --user 单元，入包 `/usr/lib/systemd/user/`，不默认 enable |
| `~/.config/remote-input-board/pin.txt` | 自动生成的 PIN（配置目录 0700，文件 0600） |
| `~/.config/remote-input-board/trusted_devices.json` | 已配对设备列表（仅 token 的 SHA-256 + 时间/最近 IP，0600；删除即全部重新配对） |
| `~/.local/share/remote-input-board/logs/server.log` | 服务日志 |
| `~/.local/share/remote-input-board/logs/stats.json` | 累计字数备份（手机上报，内存缓存约 5 分钟落盘） |
| `~/.local/share/remote-input-board/logs/history/YYYY-MM-DD/HH.log` | 输入历史，按天+小时分文件，一行一条 JSON（`{"kind":"text",...}` / `{"kind":"key","key":"Return"}`；只有 text 计字数） |

## 通信协议

- `GET /`：手机页面（含锁屏，无需鉴权）
- `GET /api/auth-info`：公开，返回 `{"pinLength": 6}`
- `POST /api/auth`：公开，`{"pin": "..."}` 换 `{"token": "..."}`；token 为持久 trusted-device 凭证，**不绑 IP**，服务端只存其 SHA-256；错误 PIN 返回 401，触发限流返回 429 + `retryAfter`
- `POST /api/logout`：携带有效 token（Bearer 头或 `?token=`），注销（取消配对）当前设备
- `GET /api/stats`、`GET|POST /api/type`、`GET /api/ping`：必须带 token——`Authorization: Bearer <token>` 头或 URL `?token=<token>` 查询参数（等价，头优先），否则 401 + `authRequired`
- `POST /api/type` body 两种：`{"text":"..."}`（空文本 400，成功回含 `sentChars`/`totalChars`）或 `{"key":"Return"}`（单键，成功回 `{"ok":true,"key":"Return",...}`，无 totalChars；非白名单按键 400 `Unsupported key.`）
- `GET /api/type`：token/text/key 全在查询串；`key=Return` 优先于 `text`；text 上限 `MAX_GET_TEXT_CHARS=600`（超长 400 提示改 POST）；两者都没有 400
- `GET /api/ping`：配对状态探针，有效 token 回 `{"ok":true}`，用于页面启动时校验
- `GET /?token=<token>`：页面读取后存入 localStorage 并用 `history.replaceState` 抹掉地址栏——把带 token 的链接发给新设备即可免 PIN 配对（**链接含凭证，勿外发**）
- 无 WebSocket：发送全部是无状态 HTTP 请求；`log_message` 整体静默，token 与文本不会进访问日志
- Handler 保持 `protocol_version = "HTTP/1.1"`：启用 keep-alive，重复发送复用连接
- 配对状态由 `AuthStore` 持久化在配置目录 `trusted_devices.json`：重启不失效，IP 变化不失效；删除该文件或调用 logout 才需要重新输 PIN

## HTTPS（可选，与 HTTP 同时监听）

- **双端口模型**（见 `server.create_servers`）：HTTP 始终监听 `PORT`（默认 3210）；配置目录存在 cert/key 时，**额外**在 `HTTPS_PORT`（默认 `PORT+1`，即 3211）起一个 TLS server。两个 server 共用同一个 handler（PIN/配对/统计/历史完全互通，一个端口配对后另一个也免 PIN）。无证书→只有 HTTP；`HTTPS_PORT==PORT`（非 0）启动报错
- 证书路径解析见 `server.resolve_tls_files`，语义同 shell `: "${SSL_CERT_FILE:=<config>/cert.pem}"`：**默认读配置目录的 `cert.pem`/`key.pem`，环境变量设了才覆盖**；只找到一个文件→启动报错并指出缺哪个
- 自签证书用 `scripts/generate_cert.sh`（安装后 `remote-input-board-generate-cert`）生成（自动探测局域网 IP 写入 SAN，输出到配置目录 cert.pem/key.pem）；底层等价于 `openssl req -x509 -newkey rsa:2048 -nodes -keyout key.pem -out cert.pem -days 3650 -subj "/CN=remote-input" -addext "subjectAltName=IP:<LAN-IP>"`
- 排查：启动日志 `HTTP on port X. HTTPS on port Y.` 两行都有才是双协议；只有 HTTP 行说明没找到 cert/key。协议与端口严格配对（3210 只说 HTTP，3211 只说 HTTPS）
- 前端无需改动：所有发送都是同源相对路径 HTTP 请求，HTTP/HTTPS 自动跟随页面协议
- 环境变量一览：`PORT`、`HTTPS_PORT`（不设则 PORT+1）、`PIN_CODE`（纯数字；不设则读/生成配置目录 `pin.txt`）、`SSL_CERT_FILE`、`SSL_KEY_FILE`（不设则默认配置目录下同名文件）、`XDG_CONFIG_HOME`/`XDG_DATA_HOME`、`REMOTE_INPUT_CONFIG_DIR`/`REMOTE_INPUT_DATA_DIR`（最高优先级的目录覆盖）
- 从任意目录启动均可；旧版本写在 CWD 的 pin.txt/trusted_devices.json/cert/key/logs 首次启动时自动迁移到 XDG 目录（仅当新配置目录未初始化，且不覆盖已有文件）
- 无证书（HTTP-only）时启动日志打 WARN：PIN 在网络上可见，不可信网络应生成证书并用 https 端口

## 注意事项

- **文字输入需要 fcitx5**：焦点应用必须正使用 fcitx5 输入法。没有 fcitx5、或模块未加载时 socket 不存在，`type_text` 抛 `TextInjectorUnavailableError`（HTTP 层转成 500，手机页面可见）
- **回车仍依赖 wtype（Wayland-only）**：X11 会话要改用 xdotool/ydotool 发 Return，目前未实现
- 两条通道都向**当前焦点窗口**输入，发送前需在电脑上点好目标输入位置
- 需确保防火墙允许局域网访问 TCP 3210（HTTP）；启用 HTTPS 后还要放行 3211（或自定义的 `HTTPS_PORT`）
- 页面被前端强缓存时可能需要强制刷新
