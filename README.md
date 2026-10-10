# Remote Input Board

手机浏览器作为 Linux 电脑的文字输入工具。电脑运行一个只用 Python 标准库的 HTTP 服务，手机在同一局域网打开网页输入文字，服务端把文字提交到当前焦点应用的光标位置。

## 工作方式

文字与按键是两条互不相干的通道。文字经 Unix socket 交给 fcitx5 addon `fcitx5-text-injector`（源码在同级目录 `../fcitx5-text-injector`），由它调用 `commitString()` 提交文本，因此不受输入法影响，中文、日文、emoji 都能原样输入。按键（目前是回车）由 `key_input` 执行，默认后端 `ydotool`，可切换为 `wtype`。多行文本原样提交，换行不会触发回车。

```
手机浏览器  ──HTTP──▶  Python 服务（本仓库）
                          │
              ┌───────────┴───────────┐
              │ 文字                   │ 按键
              ▼                       ▼
   Unix socket JSON            ydotool 或 wtype
              │                       │
              ▼                       ▼
  fcitx5-text-injector        合成按键事件
  ic->commitString()          （ydotool 经 uinput）
              │                       │
              └───────────┬───────────┘
                          ▼
             当前焦点应用的输入框
```

通信为无状态 HTTP，不使用 WebSocket。token 与内容位于同一个请求中（`GET /api/type?token=…&text=…`），curl、浏览器快捷指令、书签都能直接调用。

## 依赖

| 依赖 | 必需性 | 用途 |
|------|--------|------|
| Python >= 3.11 | 必需 | 服务端本体，无第三方包 |
| fcitx5 + fcitx5-text-injector | 文字输入必需 | 文字注入通道，不在任何仓库中，需单独构建安装 |
| ydotool | 按键输入需要 | 默认按键后端，Wayland 与 X11 都可用，另需 ydotoold 守护进程 |
| wtype | 备选按键后端 | `KEY_BACKEND=wtype` 时使用，仅 Wayland |
| openssl | 可选 | 生成自签 HTTPS 证书 |

只发文字可以不装任何按键工具，服务端启动时会说明当前按键后端是否可用。

## 按键后端

`KEY_BACKEND` 选择后端，取值 `ydotool`（默认）或 `wtype`，两者都不做自动回退：指定的工具不在 PATH 中时接口直接返回错误并提示如何切换。启动日志会打印实际使用的后端：

```bash
KEY_BACKEND=wtype python3 -m py_remote_input
```

ydotool 通过内核 uinput 工作，因此 X11 会话同样可用，前提是 ydotoold 守护进程在运行、当前用户对 `/dev/uinput` 或 ydotool socket 有权限。Arch 上的典型设置：

```bash
sudo pacman -S ydotool
sudo usermod -aG input $USER          # 重新登录生效
sudo systemctl enable --now ydotoold
```

回车对应的内核键码是 28（`linux/input-event-codes.h` 的 `KEY_ENTER`），写在 `py_remote_input/key_input/ydotool_backend.py` 的 `KEYCODES` 表里。两个后端各占一个文件，实现 `key_input/base.py` 定义的 `KeyInputBackend` 接口：子类只需给出工具名、可执行文件名、把 keysym 变成命令行参数的方法，以及安装与失败两段的提示文案；查找工具、执行、超时和异常转换都由基类完成。新增一个按键工具因此是加一个实现文件并在 `key_input/__init__.py` 的 `BACKENDS` 里注册一项，`KEY_BACKEND` 的取值范围随之扩大。

## 启动

```bash
python3 -m py_remote_input
```

日志打印配置与数据目录、按键后端、手机可访问的地址、本次 PIN，以及未启用 HTTPS 时的提示：

```
[2026-10-10T09:12:03.412Z] INFO Config directory: /home/you/.config/remote-input-board
[2026-10-10T09:12:03.412Z] INFO Data directory:   /home/you/.local/share/remote-input-board
[2026-10-10T09:12:03.415Z] INFO Generated a new PIN and saved it to .../pin.txt (chmod 600).
[2026-10-10T09:12:03.416Z] INFO Key input backend: ydotool.
[2026-10-10T09:12:03.500Z] INFO Remote input server is running. HTTP on port 3210.
[2026-10-10T09:12:03.500Z] INFO Open one of these addresses on your phone:
[2026-10-10T09:12:03.500Z] INFO http://192.168.1.20:3210
[2026-10-10T09:12:03.500Z] INFO PIN required on first connect: 482915
[2026-10-10T09:12:03.500Z] WARN Running over plain HTTP only: the PIN and typed text are visible on the network. ...
```

首次启动在配置目录生成 6 位数字 PIN（权限 0600），之后每次复用同一个；设了 `PIN_CODE` 则以其为准且不再写文件。

## 配对

手机浏览器打开上述地址，页面显示数字键盘，输入 PIN 即完成配对。配对 token 存在手机 localStorage，设备记录存在电脑磁盘，换 WiFi、IP 变化、服务重启都不需要重新输入 PIN。页面右上角的"锁定"调用 `/api/logout` 取消本机信任并回到 PIN 页面。

打开 `http://host:3210/?token=<token>` 会自动完成配对，页面随后从地址栏移除 token，可以把这种链接存成快捷方式给其它设备用。

## 页面与选项

页面是单个 HTML 文件，原生 JS，无框架、无构建步骤。

- 输入框与发送、清空按钮：发送后清空输入框。
- 回车直接发送（Shift+回车换行）：默认关闭。判断条件包含 `isComposing`，输入法候选过程中的回车不会触发发送。
- 无文字时点发送等于在电脑上按回车：默认关闭，开启后空发送走按键通道提交一次真实按键。
- 发送记录：最近 20 条保存在手机本地，点击可填回输入框，支持一键清空，不与电脑同步。

## HTTPS

HTTP 始终监听 `PORT`。当配置目录里 cert.pem 和 key.pem 同时存在时，额外在 `HTTPS_PORT`（默认 `PORT+1`）启动 TLS 监听，两个端口共用同一个 handler，PIN、配对与历史互通。

```bash
remote-input-board-generate-cert        # 源码树里为 scripts/generate_cert.sh
```

脚本探测所有全局 IPv4 地址写入 SAN，有效期 3650 天，输出到配置目录。生成后重启服务即可启用，页面全部使用同源相对路径，协议自动跟随，前端无需改动。

只有其中一个文件存在时启动报错并指出缺失项；`HTTPS_PORT` 与 `PORT` 相同（非 0）同样报错。两个文件都没有时只跑 HTTP，并在日志中提示 PIN 和文本在网络上明文可见。自签证书需要在手机上手动信任一次。

## API

除 `GET /`、`GET /api/auth-info`、`POST /api/auth` 外，所有接口都需要 token。token 可以放在 `Authorization: Bearer …` 头或 `?token=` 查询参数中，两者同时存在时以头为准。

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/` | 手机页面 |
| `GET` | `/api/auth-info` | 返回 `{ok, pinLength}`，页面据此确定键盘点数 |
| `POST` | `/api/auth` | `{"pin":"482915"}` → `{ok, token}`；PIN 错误 401；尝试过多 429 并带 `retryAfter` |
| `GET` | `/api/ping` | 配对有效性检查，有效返回 `{ok:true}` |
| `POST` | `/api/type` | body `{"text":"…"}` 提交文字，body `{"key":"Return"}` 按当前按键后端按下按键 |
| `GET` | `/api/type` | query 形式，`?text=…` 或 `?key=Return`；文本上限 600 字符，超限返回 400 并提示改用 POST |
| `POST` | `/api/logout` | 取消信任当前设备 |
| `OPTIONS` | 任意路径 | CORS 预检，返回 204 |

所有响应都带 `Access-Control-Allow-*` 头，允许跨域调用。协议为 HTTP/1.1，连接复用。

```bash
TOKEN=$(curl -s -X POST http://127.0.0.1:3210/api/auth -H 'Content-Type: application/json' \
  -d '{"pin":"482915"}' | python3 -c 'import sys,json;print(json.load(sys.stdin)["token"])')

curl -sG http://127.0.0.1:3210/api/type --data-urlencode "token=$TOKEN" --data-urlencode "text=你好"
# {"ok":true,"sentChars":2,"method":"fcitx5","charCount":2,"durationMs":3}

curl -s -X POST http://127.0.0.1:3210/api/type -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -d '{"key":"Return"}'
# {"ok":true,"method":"ydotool","key":"Return","durationMs":14}

# 单条链接形式
curl -sG http://127.0.0.1:3210/api/type --data-urlencode "token=$TOKEN" --data-urlencode "text=粘贴自手机"
```

响应中的 `method` 标明实际走到的通道：文字固定为 `fcitx5`，按键为后端名（`ydotool` 或 `wtype`）。

失败时服务端返回 500，`error` 字段是具体原因（连不上 addon、addon 拒绝、按键后端未安装、ydotoold 未运行等）以及对应的处理建议。

## 文件位置

使用 XDG 目录，因此从任意工作目录启动（包括 systemd 用户服务）都不依赖当前目录：

| 内容 | 位置 |
|------|------|
| PIN、已配对设备、TLS 证书与私钥 | `$XDG_CONFIG_HOME/remote-input-board/`，默认 `~/.config/…`，新建时权限 0700 |
| 服务日志、输入历史 | `$XDG_DATA_HOME/remote-input-board/logs/`，默认 `~/.local/share/…` |

磁盘上只保存 token 的 SHA-256，`trusted_devices.json` 内容不包含可用 token；`pin.txt` 与私钥权限 0600。

旧版本将这些文件写在启动目录，首次启动时若新配置目录尚未初始化，会一次性把它们迁移过去，已有 PIN 与配对关系保持不变。

每次成功输入向 `logs/history/YYYY-MM-DD/HH.log` 追加一行 JSON，目录与文件按本地日期和时间命名，`createdAt` 为 UTC。项目本身不做统计，需要汇总可自行扫描这些文件。

服务端不输出 HTTP 访问日志：GET 请求行里包含 token 和文本原文。运行日志只记录 `textLength` 这类元信息。

## 环境变量

| 变量 | 默认 | 说明 |
|------|------|------|
| `PORT` | `3210` | HTTP 监听端口 |
| `HTTPS_PORT` | `PORT+1` | 存在证书时的 TLS 端口 |
| `PIN_CODE` | — | 覆盖 PIN，必须是纯数字 |
| `KEY_BACKEND` | `ydotool` | 按键后端，取值 `ydotool` 或 `wtype` |
| `SSL_CERT_FILE` / `SSL_KEY_FILE` | 配置目录的 `cert.pem` / `key.pem` | 设置后覆盖对应默认路径 |
| `TEXT_INJECTOR_SOCKET` | 见下 | fcitx5-text-injector 的 socket 路径 |
| `XDG_CONFIG_HOME` / `XDG_DATA_HOME` | `~/.config` / `~/.local/share` | 目录根 |
| `REMOTE_INPUT_CONFIG_DIR` / `REMOTE_INPUT_DATA_DIR` | — | 优先级最高的目录覆盖 |

未设置 `TEXT_INJECTOR_SOCKET` 时按 addon 的默认规则推导：`$XDG_RUNTIME_DIR/text-injector.sock`，不可用时退到 `/tmp/text-injector-<uid>.sock`。

## Arch Linux 打包

```bash
cd packaging/arch && makepkg -si
```

包名 `remote-input-board-git`，VCS 滚动包。`prepare()` 直接从当前工作树复制源文件，不联网 clone，修改后立即可打包，代价是产物包含未提交改动。`check()` 运行单元测试。安装内容：

- `remote-input-board` — 服务命令
- `remote-input-board-generate-cert` — 证书生成脚本
- `/usr/lib/systemd/user/remote-input-board.service` — 用户服务，安装后不自动启用

```bash
systemctl --user enable --now remote-input-board.service
journalctl --user -fu remote-input-board
```

`depends` 只有 `python`。fcitx5-text-injector 不在任何仓库中，写入 depends 会导致依赖无法解析；ydotool 与 wtype 只有按键功能才需要，因此三者都在 `optdepends`，按需自行安装。

## 排查

文字无反应时检查注入通道：

```bash
ls -la "$XDG_RUNTIME_DIR/text-injector.sock"
echo '{"type":"ping"}' | socat - UNIX-CONNECT:"$XDG_RUNTIME_DIR/text-injector.sock"
# 期望 {"pong":true}
```

无应答说明 addon 未安装或 fcitx5 未重启，可用 `fcitx5-diagnose` 查看加载状态；两侧 socket 路径不一致时用 `TEXT_INJECTOR_SOCKET` 覆盖。

按键失败时先看启动日志里的 `Key input backend:` 一行，它说明当前用的是哪个后端、以及该后端的可执行文件是否找到。常见两种情况：后端工具没装（安装它，或用 `KEY_BACKEND` 换成另一个）；ydotool 在但 ydotoold 没跑或用户没有 `/dev/uinput` 权限，错误信息里会带上工具的原始输出。X11 会话用默认后端即可，`wtype` 则是 Wayland 专用。

手机连不上：确认两侧在同一局域网，检查防火墙是否放行 `PORT`。启动日志列出的地址来自服务对本机 IPv4 的探测，若列表为空说明没有取得全局地址。

## 开发

```bash
python3 -m unittest discover -s tests    # 90 个测试，纯标准库，秒级
```

路由层不依赖 `http.server`，`handle_request()` 接收 method、path、body、query 并返回 `Response`，大部分行为可脱离真实服务器测试。测试按两条输入通道组织：`test_text_input.py` 用临时 Unix socket 模拟 addon，`test_key_input.py` 注入假的命令执行器并接管可执行文件检查，两者都不需要真的装上 fcitx5、ydotool 或 wtype。前端测试直接读取 HTML 文本做字符串断言。

## 限制

- 按键后端各有前提：ydotool 需要 ydotoold 守护进程与 `/dev/uinput` 访问权限（通常要把用户加进 input 组，或以 root 运行守护进程），wtype 只支持 Wayland。
- 文字输入依赖 fcitx5，其它输入法框架（IBus 等）没有对应后端。
- 服务端只面向当前焦点输入上下文，发送前需自行确认目标窗口处于聚焦状态。
- 自签证书需要手动信任。

## 来源

早期版本是 Windows 实现，包含鼠标触摸板、快捷指令、剪贴板粘贴模式。移植到 Linux 时按最小可用范围裁剪，只保留文字输入主线，上述 Windows 专属功能未一并迁移。
