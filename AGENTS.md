# AGENTS.md

## 项目简介

远程输入板（Linux 版） — 用手机浏览器作为 Linux 电脑的远程文本输入面板。当前为精简版，只支持**文字发送**：手机网页发送文字，电脑端通过 `wtype`（Wayland virtual-keyboard）输入到当前光标处。

- **服务端口**: 3210
- **Python 包**: `py_remote_input`
- **入口**: `python3 -m py_remote_input`（纯标准库，无第三方依赖；也可用 `uv run python -m py_remote_input`）
- **系统依赖**: `wtype`（如 `sudo apt install wtype`），且运行在 Wayland 会话中，需要能访问 `WAYLAND_DISPLAY` / `XDG_RUNTIME_DIR`

开机自启动不在本仓库内配置，由外部（如 systemd --user）自行管理。

---

## 运行与验证

```bash
# 启动（日志写入当前工作目录下的 logs/）
python3 -m py_remote_input

# 测试
python3 -m unittest discover -s tests

# 验证接口
curl -s http://127.0.0.1:3210/
curl -s -X POST http://127.0.0.1:3210/api/type -H 'Content-Type: application/json' -d '{"text":"你好"}'
```

## 关键文件说明

| 文件 | 作用 |
|------|------|
| `py_remote_input/templates/index.html` | 前端页面（单文件，极简：输入框 + 发送 + 本地记录） |
| `py_remote_input/server.py` | HTTP + WebSocket 服务入口 |
| `py_remote_input/web.py` | HTTP 路由 + WebSocket 消息处理（只保留 type / ping / stats） |
| `py_remote_input/typer.py` | Linux 文字输入：调用 `wtype`，换行转 `-k Return`，长文本分批 |
| `py_remote_input/stats.py` | 字数统计存储 |
| `py_remote_input/websocket.py` | 手写 WebSocket 帧协议（标准库） |
| `py_remote_input/logger.py` | 日志（同时输出 stdout 和文件） |
| `scripts/rebuild_stats.py` | 从 history 重建 stats.json |
| `logs/server.log` | 服务日志 |
| `logs/stats.json` | 累计字数备份（手机上报，内存缓存约 5 分钟落盘） |
| `logs/history/YYYY-MM-DD/HH.log` | 输入历史，按天+小时分文件，一行一条 JSON |

## 通信协议

- `GET /`：手机页面
- `GET /api/stats`：累计字数
- `POST /api/type`：`{"text": "..."}`，HTTP 兜底通道
- `GET /ws`：WebSocket；客户端发 `{"type":"type","id":N,"text":"..."}`，服务端原样回 `id`；另有 `ping`/`pong`、`getStats`/`setStats`
- Handler 必须保持 `protocol_version = "HTTP/1.1"`：浏览器只接受 `HTTP/1.1 101` 的升级响应，返回 HTTP/1.0 会导致 WS 连上即断

## HTTPS（可选）

- 同时设置环境变量 `SSL_CERT_FILE` 和 `SSL_KEY_FILE` 即启用 TLS（见 `server.maybe_wrap_tls`），启动日志和 URL 会切换为 https
- 自签证书需把局域网 IP 写进 SAN：`openssl req -x509 -newkey rsa:2048 -nodes -keyout key.pem -out cert.pem -days 3650 -subj "/CN=remote-input" -addext "subjectAltName=IP:192.168.x.x"`
- 前端无需改动：页面是 https 时自动用 wss，是 http 时用 ws
- 不设环境变量就是纯 HTTP；只设其中一个会直接报错

## 注意事项

- 只支持 Wayland（wtype）。X11 场景需要改用 xdotool/ydotool，目前未实现
- wtype 向**当前焦点窗口**输入，发送前需在电脑上点好目标输入位置
- 服务端口 3210 需确保防火墙允许局域网访问
- 页面被前端强缓存时可能需要强制刷新
