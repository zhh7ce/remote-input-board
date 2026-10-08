# AGENTS.md

## 项目简介

远程输入板（Linux 版） — 用手机浏览器作为 Linux 电脑的远程文本输入面板。当前为精简版，核心是**文字发送**：手机网页发送文字，电脑端通过 `wtype`（Wayland virtual-keyboard）输入到当前光标处。另有可选的**空发送回车**：前端复选框控制（localStorage `remoteInput.enterWhenEmpty`），勾选后输入框为空点发送即按一次 Enter（`wtype -k Return`）。

- **服务端口**: 3210
- **Python 包**: `py_remote_input`
- **入口**: `python3 -m py_remote_input`（纯标准库，无第三方依赖；也可用 `uv run python -m py_remote_input`）
- **系统依赖**: `wtype`（如 `sudo apt install wtype`），且运行在 Wayland 会话中，需要能访问 `WAYLAND_DISPLAY` / `XDG_RUNTIME_DIR`
- **访问控制**: KDE Connect 式配对。手机首次过 PIN 锁屏（纯点按数字键盘）后获得持久 token，服务端把设备哈希记入 `trusted_devices.json`，之后 IP 变化/重启都免 PIN，直到 `/api/logout` 或删除该文件。PIN 来自 `PIN_CODE` 环境变量，否则读工作目录 `pin.txt`，再没有就自动生成 6 位数字（0600）并打印到启动日志

开机自启动不在本仓库内配置，由外部（如 systemd --user）自行管理。

---

## 运行与验证

```bash
# 启动（日志写入当前工作目录下的 logs/）
python3 -m py_remote_input

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
```

## 关键文件说明

| 文件 | 作用 |
|------|------|
| `py_remote_input/templates/index.html` | 前端页面（单文件，极简：输入框 + 发送 + 本地记录；状态条固定显示连接态 connecting/online/offline，发送结果走底部 toast；无累计字数 UI） |
| `py_remote_input/server.py` | HTTP + WebSocket 服务入口（`build_handler` 把 `type_text` 与 `press_key` 一起注入 handler） |
| `py_remote_input/web.py` | HTTP 路由 + WebSocket 消息处理（auth / type / key / ping / stats）；`ALLOWED_REMOTE_KEYS={"Return"}` 为远程按键白名单 |
| `py_remote_input/auth.py` | PIN 加载与限流；trusted-device 配对：32 字节随机 token、服务端只存 SHA-256、落盘 `trusted_devices.json`（0600）、**不绑 IP、重启不失效**、`revoke()` 取消配对 |
| `py_remote_input/typer.py` | Linux 文字输入：调用 `wtype`，换行转 `-k Return`，长文本分批；`press_key(keysym)` 按 `ALLOWED_KEYSYMS` 白名单校验后执行 `wtype -k <keysym>`，`press_return()` 为其便捷封装 |
| `py_remote_input/stats.py` | 字数统计存储 |
| `py_remote_input/websocket.py` | 手写 WebSocket 帧协议（标准库） |
| `py_remote_input/logger.py` | 日志（同时输出 stdout 和文件） |
| `scripts/rebuild_stats.py` | 从 history 重建 stats.json |
| `pin.txt` | 工作目录下自动生成的 PIN（0600，已 gitignore） |
| `trusted_devices.json` | 已配对设备列表（仅 token 的 SHA-256 + 时间/最近 IP，0600，已 gitignore；删除即全部重新配对） |
| `logs/server.log` | 服务日志 |
| `logs/stats.json` | 累计字数备份（手机上报，内存缓存约 5 分钟落盘） |
| `logs/history/YYYY-MM-DD/HH.log` | 输入历史，按天+小时分文件，一行一条 JSON（`{"kind":"text",...}` / `{"kind":"key","key":"Return"}`；只有 text 计字数） |

## 通信协议

- `GET /`：手机页面（含锁屏，无需鉴权）
- `GET /api/auth-info`：公开，返回 `{"pinLength": 6}`
- `POST /api/auth`：公开，`{"pin": "..."}` 换 `{"token": "..."}`；token 为持久 trusted-device 凭证，**不绑 IP**，服务端只存其 SHA-256；错误 PIN 返回 401，触发限流返回 429 + `retryAfter`
- `POST /api/logout`：携带有效 Bearer token，注销（取消配对）当前设备
- `GET /api/stats`、`POST /api/type`：必须带 `Authorization: Bearer <token>`，否则 401 + `authRequired`
- `POST /api/type` body 两种：`{"text":"..."}`（空文本 400，成功回含 `sentChars`/`totalChars`）或 `{"key":"Return"}`（单键，成功回 `{"ok":true,"key":"Return",...}`，无 totalChars；非白名单按键 400 `Unsupported key.`）
- `GET /ws`：WebSocket；连上后首包必须是 `{"type":"auth","id":N,"token":"..."}`，鉴权前其它消息一律回 `authRequired`；通过后发 `{"type":"type","id":N,"text":"..."}`（原样回 `id`）或 `{"type":"key","id":N,"key":"Return"}`；另有 `ping`/`pong`、`getStats`/`setStats`
- Handler 必须保持 `protocol_version = "HTTP/1.1"`：浏览器只接受 `HTTP/1.1 101` 的升级响应，返回 HTTP/1.0 会导致 WS 连上即断
- 配对状态由 `AuthStore` 持久化在工作目录 `trusted_devices.json`：重启不失效，IP 变化不失效；删除该文件或调用 logout 才需要重新输 PIN

## HTTPS（可选，与 HTTP 同时监听）

- **双端口模型**（见 `server.create_servers`）：HTTP 始终监听 `PORT`（默认 3210）；工作目录存在 cert/key 时，**额外**在 `HTTPS_PORT`（默认 `PORT+1`，即 3211）起一个 TLS server。两个 server 共用同一个 handler（PIN/配对/统计/历史完全互通，一个端口配对后另一个也免 PIN）。无证书→只有 HTTP；`HTTPS_PORT==PORT`（非 0）启动报错
- 证书路径解析见 `server.resolve_tls_files`，语义同 shell `: "${SSL_CERT_FILE:=./cert.pem}"`：**默认读工作目录的 `cert.pem`/`key.pem`，环境变量设了才覆盖**；只找到一个文件→启动报错并指出缺哪个
- 自签证书用 `scripts/generate_cert.sh` 生成（自动探测局域网 IP 写入 SAN，输出 cert.pem/key.pem，均已 gitignore）；底层等价于 `openssl req -x509 -newkey rsa:2048 -nodes -keyout key.pem -out cert.pem -days 3650 -subj "/CN=remote-input" -addext "subjectAltName=IP:<LAN-IP>"`
- 排查：启动日志 `HTTP on port X. HTTPS on port Y.` 两行都有才是双协议；只有 HTTP 行说明没找到 cert/key。协议与端口严格配对（3210 只说 HTTP，3211 只说 HTTPS）
- 前端无需改动：页面是 https 时自动用 wss，是 http 时用 ws
- 环境变量一览：`PORT`、`HTTPS_PORT`（不设则 PORT+1）、`PIN_CODE`（纯数字；不设则读/生成 `pin.txt`）、`SSL_CERT_FILE`、`SSL_KEY_FILE`（不设则默认工作目录下同名文件）
- 无证书（HTTP-only）时启动日志打 WARN：PIN 在网络上可见，不可信网络应生成证书并用 https 端口

## 注意事项

- 只支持 Wayland（wtype）。X11 场景需要改用 xdotool/ydotool，目前未实现
- wtype 向**当前焦点窗口**输入，发送前需在电脑上点好目标输入位置
- 需确保防火墙允许局域网访问 TCP 3210（HTTP）；启用 HTTPS 后还要放行 3211（或自定义的 `HTTPS_PORT`）
- 页面被前端强缓存时可能需要强制刷新
