# Remote Input Board 📱→💻

**用手机浏览器给 Linux 电脑远程输入文字。** 电脑上跑一个小服务，手机打开网页输入文字，点发送就通过 [wtype](https://github.com/atx/wtype) 输入到电脑当前光标处。

当前为 Linux/Wayland 精简版，只保留**文字发送**能力（实时 WebSocket，断连自动回退 HTTP）；按键控制、鼠标触控板、快捷指令等 Windows 版功能暂未移植。

---

### 环境要求

- Linux + **Wayland** 会话（wtype 依赖 virtual-keyboard 协议）
- 安装 `wtype`：

```bash
# Debian / Ubuntu
sudo apt install wtype
# Arch
sudo pacman -S wtype
# Fedora
sudo dnf install wtype
```

> 服务进程需要能访问你的图形会话（`WAYLAND_DISPLAY`、`XDG_RUNTIME_DIR`）。在桌面会话里启动，或用 systemd --user 服务，通常都能自动继承。

### 快速开始

纯标准库实现，无需安装依赖，直接跑：

```bash
python3 -m py_remote_input
# 或
uv run python -m py_remote_input
```

终端会打印手机访问地址：

```
http://192.168.x.x:3210
```

电脑和手机连同一个 WiFi，手机浏览器打开即可。发送前先在电脑上点一下目标窗口，把光标放好。

### 配置

| 你想干嘛 | 怎么弄 |
|---------|-------|
| 改端口 | `PORT=3219 python3 -m py_remote_input` |
| 局域网访问 | 确保防火墙放行 TCP 3210 |
| 启用 HTTPS | 同时设置 `SSL_CERT_FILE` 和 `SSL_KEY_FILE`（见下） |

### HTTPS（可选）

**家里 WiFi 用其实不需要 HTTPS**——HTTP 下页面、WebSocket（ws://）都能正常工作。只有在不可信网络或确实需要加密时再启用。启用后必须用 `https://` 访问，手机页面会自动改用 `wss://`，不用改前端。

**方式一：自签证书（适合局域网 IP 访问，零成本）**

```bash
# 把 192.168.x.x 换成电脑的局域网 IP
openssl req -x509 -newkey rsa:2048 -nodes \
  -keyout key.pem -out cert.pem -days 3650 \
  -subj "/CN=remote-input" \
  -addext "subjectAltName=IP:192.168.x.x"

SSL_CERT_FILE=$PWD/cert.pem SSL_KEY_FILE=$PWD/key.pem \
  PORT=3210 python3 -m py_remote_input
```

手机首次访问 `https://192.168.x.x:3210` 会有证书警告，点「高级 → 仍然继续」信任一次即可，WebSocket 的 wss 连接同样会被信任。只设了一个环境变量时服务会直接报错提醒。

**方式二：受信任证书（需要域名）**

如果你有域名指向这台机器，可以用 Caddy 自动签发 Let's Encrypt 证书并反代到 3210，或用 certbot 拿到证书后同样通过 `SSL_CERT_FILE`/`SSL_KEY_FILE` 加载。纯内网 IP 无法申请公网受信任证书。

### 日志与数据

运行目录下生成（可用工作目录控制位置）：

| 文件 | 内容 |
|------|------|
| `logs/server.log` | 服务日志 |
| `logs/history/YYYY-MM-DD/HH.log` | 发送历史，按天+小时分文件，一行一条 JSON |
| `logs/stats.json` | 累计字数备份（内存缓存约 5 分钟落盘） |

### 实现说明

- 文字经 WebSocket（`/ws`，消息 `{"type":"type","text":...}`）或 HTTP（`POST /api/type`）到达服务端
- 页面协议自动跟随：HTTP 页面走 `ws://`，HTTPS 页面走 `wss://`
- 服务端调用 `wtype <text>`；换行符会转成 `wtype -k Return`，长文本自动分批调用
- wtype 未安装时接口返回明确的错误提示，手机页面可见

### 技术栈

`Python 标准库（http.server + 手写 WebSocket 帧）` `wtype` `原生 JS（无框架）`
