# AGENTS.md — remote-input-board

本文档面向在本仓库工作的 coding agent。内容以当前代码为准，改动行为时同步更新本文档。

## 概述

手机浏览器作为 Linux 电脑的远程文字输入板。电脑端是纯标准库的 Python HTTP 服务，手机发送文字，服务端把它提交到当前焦点应用的光标处。

输入分两条完全独立的通道，代码也按此拆成两处：文字经 Unix socket 交给 [fcitx5-text-injector](../fcitx5-text-injector)（fcitx5 addon），由它调用 `commitString()` 提交文本，见 `text_input.py`；按键走按键模拟后端，见 `key_input/`，接口在 `base.py`，`ydotool_backend.py` 与 `wtype_backend.py` 各实现一个，`__init__.py` 注册并按参数选择，默认 ydotool。新增按键能力只改按键通道，文字通道不产生按键事件。

通信是无状态 HTTP，不使用 WebSocket。token 与内容位于同一请求（`GET /api/type?token=…&text=…`）。早期 Windows 版的鼠标触摸板、快捷指令、剪贴板模式等功能未移植。

## 运行与验证

```bash
python3 -m py_remote_input                 # 启动，PORT 默认 3210
python3 -m unittest discover -s tests      # 90 个测试，纯标准库 unittest，秒级
```

端到端手测，PIN 在启动日志中：

```bash
TOKEN=$(curl -s -X POST http://127.0.0.1:3210/api/auth -H 'Content-Type: application/json' \
  -d '{"pin":"<日志里的 PIN>"}' | python3 -c 'import sys,json;print(json.load(sys.stdin)["token"])')
curl -sG http://127.0.0.1:3210/api/type --data-urlencode "token=$TOKEN" --data-urlencode "text=你好"
curl -s -X POST http://127.0.0.1:3210/api/type -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -d '{"key":"Return"}'
```

单独验证文字通道，确认 addon 的 socket 存在并应答：

```bash
ls -la "$XDG_RUNTIME_DIR/text-injector.sock"
echo '{"type":"ping"}' | socat - UNIX-CONNECT:"$XDG_RUNTIME_DIR/text-injector.sock"   # {"pong":true}
```

按键通道看启动日志的 `Key input backend:` 一行，它给出当前后端以及该后端的可执行文件是否存在；`KEY_BACKEND=ydotool|wtype` 切换，重启生效。

## 代码结构

包名 `py_remote_input`，入口 `__main__:main` → `server.serve()`。无第三方运行时依赖，`pyproject.toml` 的 `dependencies` 保持为空。

| 文件 | 职责 |
|------|------|
| `server.py` | 组装层：`serve()` 解析环境变量、创建 XDG 目录、迁移旧文件、加载 PIN、启动双端口（HTTP 与可选 HTTPS）、注册信号并优雅退出；`build_handler()` 生成 `BaseHTTPRequestHandler` 子类；`build_history_recorder()` 生成历史写入闭包 |
| `web.py` | 路由层：`handle_request(method, path, body, type_text, logger, *, press_key, record_history, auth, client_ip, token, query)` 返回 `Response(status_code, content_type, body)`。不依赖 `http.server`，可脱离真实服务器单测 |
| `text_input.py` | 文字输入通道：`type_text()` 经 Unix socket 让 fcitx5 提交文本，`injector_socket_path()` 解析 socket 路径，`normalize_line_endings()` 处理换行。异常 `TextInjectorError`、`TextInjectorUnavailableError` |
| `key_input/__init__.py` | 按键输入通道的对外接口与后端注册：`BACKENDS`、`get_backend(name=None)`、`active_backend()`、`press_key(keysym, backend=None, run=subprocess.run)`、`press_return()`；`ALLOWED_KEYS`、`BACKEND_ENV`、`DEFAULT_BACKEND`；`UnknownKeyBackendError` |
| `key_input/base.py` | 接口 `KeyInputBackend`：子类给出 `name`、`binary`、`install_hint`、`failure_hint` 并实现 `build_command(keysym)`；基类的 `is_available()` 与 `press()` 负责查找可执行文件、执行命令、超时与异常转换。`COMMAND_TIMEOUT_SECONDS` 与异常 `KeyBackendNotFoundError`、`KeyPressFailedError` |
| `key_input/ydotool_backend.py` | `YdotoolBackend`：`ydotool key <码>:1 <码>:0`，键码表 `KEYCODES`（回车 28，取自 linux/input-event-codes.h）。Wayland 与 X11 都可用，需要 ydotoold。默认后端 |
| `key_input/wtype_backend.py` | `WtypeBackend`：`wtype -k <keysym>`，按 keysym 名交给 wtype 解析。仅 Wayland |
| `auth.py` | `load_pin()`（`PIN_CODE` → `pin.txt` → 生成 6 位）；`AuthStore`：PIN 校验、限流、持久 trusted-device 表 |
| `paths.py` | XDG 路径与旧文件迁移：`config_dir()`、`data_dir()`、`ensure_app_dirs()`、`migrate_legacy_files()` |
| `logger.py` | `Logger`：同时输出到 stdout 和 `logs/server.log`，UTC ISO 时间戳，meta 序列化为 JSON |
| `templates/index.html` | 前端单文件（590 行）：PIN 数字键盘锁屏、输入框、两个选项、本地发送记录。原生 JS，无框架、无构建 |

测试分布：`test_web.py` 路由与鉴权闸门，`test_text_input.py` 文字通道（socket 路径、注入协议、换行、失败映射），`test_key_input.py` 按键通道（后端选择、白名单、接口契约、失败映射），`test_auth.py` 鉴权与限流，`test_paths.py` 目录与迁移，`test_server.py` 历史录制，`test_frontend.py` 读取 HTML 文本做字符串断言。

两条通道的测试都不调用真实工具：文字用临时 Unix socket 扮演 addon（`_serve_once()`），按键注入假的命令执行器（`FakeRun`）并接管可执行文件检查（`stub_availability()` 替换 `KeyInputBackend.is_available`），断言"是否执行、执行了几次、结果如何映射成异常"。接口契约用 `base.KeyInputBackend` 的桩子类验证（命令来自 `build_command`、返回 `{method, key, durationMs}`、提示文案取自该子类）。注意 `PressKeyTests` 之外的用例若调用 `press_key()`，必须自行包住 `stub_availability()`，否则会走到真实工具。

改动落点：接口与路由行为在 `web.py`，文字注入在 `text_input.py`，按键能力在 `key_input/`（新增后端＝新加一个实现文件并注册进 `BACKENDS`，`press_key` 流程不动），鉴权与限流在 `auth.py`，文件位置在 `paths.py`，端口与生命周期在 `server.py`，页面在 `templates/index.html`。

## 路由与鉴权

| 方法 路径 | 鉴权 | 行为 |
|---|---|---|
| `GET /` | 公开 | 返回 `HTML_PAGE`，模板在模块导入时读取一次 |
| `GET /api/auth-info` | 公开 | `{ok, pinLength}` |
| `POST /api/auth` | 公开 | PIN 错误 401；`RateLimited` 429 附 `retryAfter`；成功 `{ok, token}` |
| `POST /api/logout` | 在闸门之前处理 | 撤销请求自带 token，固定返回 200 `{ok:true}` |
| `GET /api/ping` | 需要 token | 配对有效性检查，`{ok:true}` |
| `GET /api/type` | 需要 token | query 中 `key=` 走按键、`text=` 走文字，两者都无返回 400 |
| `POST /api/type` | 需要 token | body 中 `key` 优先于 `text` |
| `OPTIONS *` | 无 | 204 + CORS 头 |
| 其它路径 | 需要 token | 无 token 先 401，有 token 返回 404 |

`web.PUBLIC_ROUTES` 只包含 `GET /`、`GET /api/auth-info`、`POST /api/auth`。`/api/logout` 不在该集合内，但在 `handle_request` 中位于鉴权闸门之前返回，因此无效 token 调用它同样得到 200：撤销只针对请求自带的 token，无 token 时无副作用。调整这段顺序前需确认该语义。

`auth` 参数为 `None` 时跳过闸门，测试借此绕开鉴权；生产路径始终传入 `AuthStore`。

## 需要遵守的约定

### 前端统一使用 `POST /api/type?token=…`

前端把 token 拼在查询参数里（`sendRequest()`），body 为 JSON。`server._bearer_token()` 支持 `Authorization: Bearer`，`handle_request` 中取值顺序为 `token or params.get("token")`，头优先于 query，无效 query token 不会覆盖有效头令牌（`test_bearer_takes_precedence_over_query_token`）。新增前端请求沿用 query 形式。

### 远程按键白名单有两处

`web.ALLOWED_REMOTE_KEYS`（HTTP 层，非白名单返回 400 `Unsupported key.`）与 `key_input.ALLOWED_KEYS`（执行层，抛 `ValueError`），当前均为 `{Return}`。来自网络请求的 keysym 不允许直接传给按键后端，新增按键必须同时加入两处，ydotool 后端还要在 `key_input/ydotool_backend.py` 的 `KEYCODES` 里补键码（wtype 按 keysym 名工作，无需额外映射）。

### 按键后端

`KEY_BACKEND` 选择 `ydotool`（默认）或 `wtype`，取值忽略大小写与空格；未知取值抛 `UnknownKeyBackendError`，指定的工具不在 PATH 中抛 `KeyBackendNotFoundError`。两种情况都不做静默回退，错误消息里给出安装方式与切换办法。

后端差异收在各自的实现文件里，共同点收在接口里：接口 `base.KeyInputBackend` 只把 `build_command(keysym)` 列为抽象方法（wtype 用 keysym 名，ydotool 用内核键码，回车是 `KEYCODES` 里的 28，按下与松开成对给出），其余由基类承担——`is_available()` 查 PATH、`press()` 执行命令并套用 `COMMAND_TIMEOUT_SECONDS` 超时、把 `CalledProcessError` 与 `TimeoutExpired` 转成 `KeyPressFailedError` 并拼上该后端的 `failure_hint`、返回 `{method, key, durationMs}`。子类额外给出 `name`、`binary`、`install_hint`、`failure_hint` 四个类属性。`__init__.py` 的 `BACKENDS` 把名字映射到实例，选择逻辑只在 `get_backend()` 一处。新增后端＝一个实现文件加一项注册，`press_key` 的流程不用改。

`server.serve()` 在装配 handler 后调用一次 `active_backend()`，再用 `backend.is_available()` 决定打印后端名还是 WARN，配置错误因此在启动时暴露，而不是等到手机第一次按回车。`KEY_BACKEND` 是进程级的；按请求切换后端的能力留在 `press_key(keysym, backend=...)` 参数上，HTTP 层目前没有使用。

### 不记录 HTTP 访问日志

`RequestHandler.log_message` 直接 `return`。GET 请求行包含 token 与用户输入原文，任何增加请求级日志的改动都会把凭证或用户文本写进 `server.log`。需要记录时只记元信息，参考 `_handle_type_text` 中的 `{"textLength": …}`。

### token 与 IP 无关，服务端只存哈希

`AuthStore.validate()` 不校验 IP，因为局域网地址会因 DHCP、iOS/Android 私有 WiFi 地址而变动。持久化的是 `secrets.token_urlsafe(32)` 的 SHA-256。新增鉴权设计保持 IP 无关。限流按 IP 统计：10 分钟窗口内 5 次失败进入指数退避（基准 15s，上限 5min），一次成功即清除该 IP 的失败记录。

trusted-device 的 `lastUsedAt`/`lastIp` 更新按 60 秒节流落盘（`USAGE_FLUSH_INTERVAL_SECONDS`）；`authenticate`、`revoke` 强制落盘，`serve()` 退出时调用 `auth.flush()`。写盘使用 `.tmp` 加 `replace` 原子替换，权限 0600。

### 历史写入路径

`server.build_history_recorder(log_dir)` 返回 `record_history(item)` 闭包，向 `logs/history/YYYY-MM-DD/HH.log` 追加。目录与文件名按本地日期与小时，`createdAt` 为 UTC ISO，一行一条 JSON。`kind` 只有 `text` 和 `key` 两种。仅在注入成功后写入。测试见 `tests/test_server.py`。

### 换行原样提交

`text_input.normalize_line_endings()` 只把 CRLF 与裸 CR 归一为 LF，其余不改动。`commitString()` 提交的是字符而非按键事件，多行内容等同粘贴，不会触发回车。这是设计行为（提交由用户显式触发），不要把换行折叠成空格或自动补回车。

### 异常统一转 500 并回传消息

`_handle_type_text` 与 `_handle_type_key` 用 `except Exception` 兜底，返回 `json_response(500, {"error": str(exc)})`。手机端需要看到"未安装 addon""按键后端找不到""ydotoold 没在运行"这类可执行提示，文案定义在 `text_input.py` 与 `key_input/` 的异常消息中（按键后端的提示文案是各实现文件里的 `install_hint` 与 `failure_hint`），按键失败还会附加工具的原始输出。

### 前端测试基于字符串断言

`tests/test_frontend.py` 读取 HTML 文本，断言控件 id、`sendRequest({ text: … })` 形状，并包含负向断言（不应出现 `new WebSocket`、`totalChars`、`累计`、`/api/stats`、`trackpad`、`/api/paste`、`已配对` 等）。这些负向断言对应本 UI 已明确移除的内容，重构前端时不要为了让测试通过而恢复它们。

前端其他约束：锁屏只用页内数字键盘，不放 `<input>`，避免弹出系统键盘（`test_pin_lock_screen_uses_on_screen_keypad_without_text_input`）；localStorage 键为 `remoteInput.token`、`.history`、`.sendOnEnter`、`.enterWhenEmpty`，记录上限 20 条；收到 401 清除 token 并回到锁屏；`?token=` 打开即配对，随后用 `history.replaceState` 从地址栏移除。

### GET 文本长度上限

`web.MAX_GET_TEXT_CHARS = 600`，只作用于 `GET /api/type` 的 query 文本（percent-encoding 后中文膨胀 3–9 倍，该上限保证 URL 不超过常见代理与浏览器限制）。POST body 无此限制，超限返回 400 并提示改用 POST。

## 端口、TLS 与生命周期（server.py）

- `create_servers()`：HTTP 始终监听 `PORT`；配置目录中 cert 与 key 同时存在时，额外在 `HTTPS_PORT`（默认 `PORT+1`）启动 TLS server。两者共用同一个 handler 类，PIN、配对、历史互通。
- 只存在其中一个文件时 `tls_status()` 抛 `RuntimeError` 并指出缺失项；`HTTPS_PORT == PORT`（非 0）同样抛错。无证书时只跑 HTTP，并记录一条 WARN 说明 PIN 与文本在网络上可见。
- 两个 server 均设置 `daemon_threads = True`，`serve_forever` 各自跑在 daemon 线程中。
- `SIGINT` 与 `SIGTERM` 共用 `_request_stop` → `stop_event` → `finally` 中 `shutdown()`、`server_close()`、`auth.flush()`。新增信号处理需保留优雅退出。
- `serve()` 中 `migrate_legacy_files()` 必须在 Logger 写入 `logs/` 之前调用，否则旧的整个 `logs/` 目录无法迁移。
- `get_local_addresses()` 只列出非 `127.` 开头的 IPv4，通过 `socket.gethostname()` 解析，失败时静默返回空列表。
- `resolve_tls_files()` 语义等同 shell 的 `${SSL_CERT_FILE:-<配置目录>/cert.pem}`，设置后才覆盖默认路径。

## 对接 fcitx5-text-injector

注入侧 socket 协议（一连接一请求：发送 JSON、`shutdown(SHUT_WR)`、读到 EOF 取得响应，未知 type 返回 `success:false`）与线程约束（fcitx5 API 只能在主事件循环线程调用，IPC 线程必须经 `event_dispatcher_.schedule()`）记录在 `../fcitx5-text-injector/AGENTS.md`，修改协议前先读该文档。模块侧收发超时各 2 秒，本客户端 `SOCKET_TIMEOUT_SECONDS = 5`。

`text_input.injector_socket_path()` 镜像 addon 的默认路径规则：`TEXT_INJECTOR_SOCKET` → `$XDG_RUNTIME_DIR/text-injector.sock`（要求以 `/` 开头）→ `/tmp/text-injector-<uid>.sock`。模块侧对应配置项为 `SocketPath`，两侧不一致时用 `TEXT_INJECTOR_SOCKET` 覆盖。

异常分层，HTTP 层统一转为 500 并把消息回给手机端：`TextInjectorUnavailableError`（socket 连不上或无应答，文案引导安装 addon 或设置 `TEXT_INJECTOR_SOCKET`）、`TextInjectorError`（模块返回 `success:false` 或响应无法解析）。

`text_input.type_text()` 成功返回 `{method:"fcitx5", charCount, durationMs}`，`key_input.press_key()` 返回 `{method:<后端名>, key, durationMs}`，`web` 层再补 `ok` 与 `sentChars`。

`test_text_input.py` 用真实临时 Unix socket 模拟 addon（`_serve_once()`），断言收到的 JSON 与半关闭语义，是协议改动的主要回归覆盖。

## 已知问题

- 按键依赖外部工具：默认后端 ydotool 需要 ydotoold 守护进程在运行、当前用户能访问 `/dev/uinput`（通常要加入 input 组），wtype 仅支持 Wayland。两个都不装时文字照常工作，按键返回 500 与安装提示。
- `packaging/arch/{pkg,src,remote-input-board/,*.pkg.tar.zst}` 是 makepkg 产物，已在 `.gitignore` 中。`prepare()` 每次清空 `src/`，`remote-input-board/` 目录是早期从 GitHub clone 留下的裸仓库，现已不再使用。
- 焦点由使用者负责：服务端只把文字交给 `lastFocusedInputContext()`，没有固定目标窗口的概念。

## 已移除的功能

以下内容由较大范围实现回退而来，恢复前先确认原因已经解决：

- 累计字数统计：`stats.py`（`TextStatsStore`、`count_text_history_chars`）、`GET /api/stats`、`/api/type` 响应中的 `totalChars`、`scripts/rebuild_stats.py` 均已删除。原实现只在启动时扫描历史、运行期间不自增，前端也已不显示。`tests/test_web.py::test_stats_endpoint_is_gone` 要求 `/api/stats` 返回 404。历史文件仍在写入（`kind=text` 那条含原文），需要统计可直接扫描历史。
- WebSocket 实时通道：`websocket.py` 与 `/ws` 已删除，改为无状态 HTTP。
- Windows 版功能：`img/`（触摸板等截图）与 `docs/plans/`（两份 Win32 剪贴板方案文档）随功能一并删除。`/api/paste`、`/api/key`、`/api/mouse`、snippet、配对状态栏均不存在。

## 提交前

修改代码后先 bump `pyproject.toml` 的 `version` 并运行 `uv lock`，再 commit。PKGBUILD 的 `pkgver` 是 git 派生的 `rN.gHASH`，不手动修改。不要自动 `git push`。

## 打包与部署

- `packaging/arch/PKGBUILD`：包名 `remote-input-board-git`，VCS 滚动包。`source=()` 为空，`prepare()` 从 `$startdir/../..`（当前工作树）复制源，不联网 clone，修改后可直接 `makepkg -f`，代价是产物含未提交改动。`check()` 运行 unittest；使用 PEP517 构建 wheel，`python -m installer` 安装。`depends` 只有 `python`：fcitx5-text-injector 不在任何仓库中，ydotool 与 wtype 只有按键功能才需要，三者都放 `optdepends`。
- `packaging/systemd/remote-input-board.service`：安装到 `/usr/lib/systemd/user/`，不默认启用，由用户执行 `systemctl --user enable --now`。
- `scripts/generate_cert.sh`：安装为 `/usr/bin/remote-input-board-generate-cert`，探测全局 IPv4 写入 SAN，输出 cert/key 到配置目录（`OUT_DIR` 可改目标，也可显式传 IP）。这是 `scripts/` 下唯一的脚本，PKGBUILD 的 `package()` 只安装它。

## 环境变量

`PORT`、`HTTPS_PORT`、`PIN_CODE`、`KEY_BACKEND`、`SSL_CERT_FILE`、`SSL_KEY_FILE`、`TEXT_INJECTOR_SOCKET`、`XDG_CONFIG_HOME`、`XDG_DATA_HOME`、`REMOTE_INPUT_CONFIG_DIR`、`REMOTE_INPUT_DATA_DIR`（后两个优先级最高）。
