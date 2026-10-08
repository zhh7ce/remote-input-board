# Remote Input Board 📱→💻

**用手机浏览器给 Linux 电脑远程输入文字。** 电脑上跑一个小服务，手机打开网页输入文字，点发送就通过 [wtype](https://github.com/atx/wtype) 输入到电脑当前光标处。

当前为 Linux/Wayland 精简版，只保留**文字发送**能力（实时 WebSocket，断连自动回退 HTTP）；按键控制、鼠标触控板、快捷指令等 Windows 版功能暂未移植。

每台手机**配对一次**：首次连接输入 **PIN 码**（手机锁屏样式的数字键盘点按，不弹系统键盘），服务端长期记住该设备，之后手机 IP 变化或服务重启都免输；可选 HTTPS 加密传输。

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

终端会打印手机访问地址和 **PIN 码**：

```
http://192.168.x.x:3210
PIN required on first connect: 482915
```

电脑和手机连同一个 WiFi，手机浏览器打开页面，先在锁屏界面点按数字键输入终端里的 PIN，解锁后才能发送文字。发送前记得在电脑上点一下目标窗口，把光标放好。

### PIN 码与设备配对

采用 KDE Connect 式的"配对一次、长期信任"模型，正常使用中**每台手机只需输入一次 PIN**：

- 首次启动会在工作目录自动生成 `pin.txt`（权限 600，已 gitignore），之后一直复用；终端每次启动都会打印当前 PIN
- 想自己指定：`PIN_CODE=135790 python3 -m py_remote_input`（纯数字）
- 手机首次输对 PIN 后拿到随机 token 存在浏览器本地；服务端把设备记到 `trusted_devices.json`（只存 token 的 SHA-256，权限 600，已 gitignore）。**之后手机 IP 变化（DHCP、私人无线局域网地址）或服务重启都不再要求 PIN**，直到主动取消配对
- 取消配对：手机页面右上角「锁定」按钮（只取消本机），或删除工作目录的 `trusted_devices.json`（所有手机重新配对）
- 安全机制：PIN 常量时间比较；token 为 32 字节随机数，服务端只存哈希；同一 IP 连续输错 5 次 PIN 会被限流（15 秒起指数退避到 5 分钟）。token 与 IP 解绑后持有者即可访问，不可信网络请务必启用 HTTPS
- WebSocket 也一样：连接后必须先发 `{"type":"auth","token":...}`，之前的任何消息都会被拒绝

### 配置

| 你想干嘛 | 怎么弄 |
|---------|-------|
| 改端口 | `PORT=3219 python3 -m py_remote_input` |
| 指定 PIN | `PIN_CODE=135790 python3 -m py_remote_input` |
| 局域网访问 | 确保防火墙放行 TCP 3210（HTTP）和 3211（HTTPS） |
| 启用 HTTPS | 工作目录放 `cert.pem`+`key.pem`（`scripts/generate_cert.sh` 生成）即在 **3211** 端口额外开启 HTTPS，与 3210 的 HTTP 同时可用；可用 `HTTPS_PORT` 改端口、`SSL_CERT_FILE`/`SSL_KEY_FILE` 改证书路径（见下） |

### HTTPS（可选）

证书存在时 **HTTP 和 HTTPS 同时提供**：HTTP 始终在 `PORT`（默认 3210），HTTPS 在 `HTTPS_PORT`（默认 **3211**），两者共用同一套 PIN 和配对信息（在一个地址配对过，另一个也免 PIN）。手机用 `http://IP:3210` 或 `https://IP:3211` 打开都行，页面会自动匹配 ws/wss，不用改前端。明文 HTTP 中 PIN 和输入内容在网络上可见——**不可信网络请用 https 地址并考虑防火墙只放行 3211**。

**方式一：自签证书（适合局域网 IP 访问，零成本）**

一键脚本会自动探测本机局域网 IP 并把它写进证书 SAN（也可手动传 IP），证书就生成在工作目录下：

```bash
scripts/generate_cert.sh
# 或指定：scripts/generate_cert.sh 192.168.10.172
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
# 证书路径语义同 shell 的 ${SSL_CERT_FILE:-./cert.pem}，设了才覆盖默认值
```

然后用 `https://` + **HTTPS 端口** + 证书里那个 IP 访问（如 `https://192.168.10.172:3211`）。注意：

- 证书只对生成时写入的 IP 有效；用别的 IP 或主机名访问仍会报警告，换网络/IP 后重新跑一次脚本即可
- 手机首次打开会有红色证书警告，这是自签证书的正常现象：
  - **安卓 Chrome / Edge**：「高级 → 继续前往（不安全）」，点一次后页面和 wss 都会放行
  - **iPhone Safari**：「显示详细信息 → 访问此网站」
  - **安卓 Firefox** 用的是自带证书库，个别版本不给"继续"入口，建议直接换 Chrome
- 想彻底消除警告（不是点"继续"而是真信任）：把 `cert.pem` 传到手机安装——安卓在「设置 → 安全 → 加密与凭据 → 安装证书 → CA 证书」；iOS 安装描述文件后还要到「设置 → 通用 → 关于本机 → 证书信任设置」里启用
- 默认路径/环境变量只找到一个文件（有 cert 没 key，或反过来）时服务会直接报错并指出缺哪个
- 常见误区：启动日志只有 `HTTP on port 3210.` 没有 `HTTPS on port 3211.`，说明工作目录没有 `cert.pem`/`key.pem`，此时访问 3211 会连接失败——跑一次 `scripts/generate_cert.sh` 再重启即可
- 注意协议和端口要配对：3210 只说 HTTP（用 https:// 访问会报错），3211 只说 HTTPS（用 http:// 访问会报错）

**方式二：受信任证书（需要域名）**

如果你有域名指向这台机器，可以用 Caddy 自动签发 Let's Encrypt 证书并反代到 3210，或用 certbot 拿到证书后同样通过 `SSL_CERT_FILE`/`SSL_KEY_FILE` 加载。纯内网 IP 无法申请公网受信任证书。

### 日志与数据

运行目录下生成（可用工作目录控制位置）：

| 文件 | 内容 |
|------|------|
| `pin.txt` | 自动生成的 PIN（600 权限；也可用 `PIN_CODE` 覆盖而不生成文件） |
| `trusted_devices.json` | 已配对设备（只存 token 的 SHA-256，600 权限；删除即全部重新配对） |
| `logs/server.log` | 服务日志 |
| `logs/history/YYYY-MM-DD/HH.log` | 发送历史，按天+小时分文件，一行一条 JSON |
| `logs/stats.json` | 累计字数备份（内存缓存约 5 分钟落盘） |

### 实现说明

- 除页面和 `/api/auth` 外，所有 HTTP 接口都要带 `Authorization: Bearer <token>`；token 由 `POST /api/auth` 用 PIN 换取，持久有效、不绑 IP，`POST /api/logout` 可注销本机
- 文字经 WebSocket（`/ws`，首包 auth，之后消息 `{"type":"type","text":...}`）或 HTTP（`POST /api/type`）到达服务端
- 页面协议自动跟随：HTTP 页面走 `ws://`，HTTPS 页面走 `wss://`
- 服务端调用 `wtype <text>`；换行符会转成 `wtype -k Return`，长文本自动分批调用
- wtype 未安装时接口返回明确的错误提示，手机页面可见

### 技术栈

`Python 标准库（http.server + 手写 WebSocket 帧）` `wtype` `原生 JS（无框架）`
