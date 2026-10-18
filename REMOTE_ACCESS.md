# WUXING 远程接入指南（O5 · T5）

本指南说明如何让手机（Android / HarmonyOS / iOS）安全地连接电脑上的 WUXING 壳服务。WUXING 只提供接入支持，不运营穿透服务；通路由你自选并自费维持。

> **安全前提**：远程绑定必须配置访问令牌；不要把壳服务直接暴露到公网。优先 overlay（Tailscale / EasyTier）或带登录门的隧道（Cloudflare Tunnel + Access）。

## 1. 先选通路

| 场景 | 推荐通路 | 手机要装 App | 公网暴露 | 成本 |
|---|---|---|---|---|
| 同一 Wi-Fi，先验证 | **LAN 直连** | 否（浏览器/薄壳） | 仅局域网 | ¥0 |
| 日常远程，安全优先 | **Tailscale**（overlay） | 是 | 无（仅 tailnet） | ¥0（个人档） |
| 国内网络、少配置 | **EasyTier** | 是 | 无/共享节点中继 | ¥0（共享节点） |
| 不想装 App、有域名 | **Cloudflare Tunnel + Access** | 否 | 有域名，Access 登录门 | 域名费 |
| 完全自控、可养 VPS | **frp + VPS** | 否 | VPS 端口/域名 | VPS 月费 |
| 零运维付费 | **蒲公英 / 花生壳** | 否 | 第三方中继 | 免费档受限 |

## 2. 通用准备

### 2.1 生成访问令牌

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

把输出保存到只有你能读的地方（密码管理器）。不要提交到 git、不要发到聊天/截图里。

### 2.2 找到电脑地址

- LAN：`ipconfig`（Windows）→ IPv4，例如 `192.168.1.5`。
- Tailscale：`tailscale ip -4` → `100.x.y.z`。
- EasyTier：客户端里查看虚拟 IP。
- 隧道：使用隧道服务商给的公开域名。

### 2.3 启动壳服务

**推荐：绑定具体地址（该地址会自动加入 Host/Origin 白名单，且非环回绑定会强制 token）**

```powershell
$env:WUXING_SHELL_TOKEN="<你的令牌>"
wuxing shell serve --host 192.168.1.5 --port 8723
```

- `--host` 用 LAN / overlay 的具体 IP，不要用 `0.0.0.0`。
- 手机与电脑必须能互通（同一 Wi-Fi / 同一 tailnet / 同一 EasyTier 网络）。
- Windows 防火墙弹窗时允许 Python 访问「专用网络」。

**如果必须绑定 `0.0.0.0`**：必须同时把实际访问的主机名/IP 写入配置，否则会 403。

```jsonc
// ~/.wuxing/config.jsonc（或工作区 config.jsonc）
{
  "shell_allow_hosts": ["192.168.1.5", "wuxing.example.com"],
  "shell_allow_origins": [
    "http://192.168.1.5:8723",
    "https://wuxing.example.com"
  ]
}
```

### 2.4 手机端填写

- 地址：`http://192.168.1.5:8723`（LAN/overlay）或 `https://wuxing.example.com`（隧道）
- 令牌：`WUXING_SHELL_TOKEN` 的值
- iOS 首次启动允许「本地网络」；Android/HarmonyOS 允许对应网络权限。

## 3. 各通路接入

### 3.1 LAN 直连（最小验证）

1. 电脑：`wuxing shell serve --host 192.168.1.5 --port 8723`（带 token）。
2. 手机与电脑同一 Wi-Fi；关闭 AP 隔离（若路由器开启）。
3. App 填 `http://192.168.1.5:8723` + token。

> LAN HTTP 是明文：同网设备可嗅探首次 `?token=` 换发请求。仅建议作为验证台阶；长期远程用 overlay/隧道。

### 3.2 Tailscale（推荐日常）

1. 电脑与手机安装 Tailscale，登录同一账号（同一 tailnet）。
2. 电脑执行 `tailscale ip -4` 取 `100.x.y.z`。
3. 启动：`wuxing shell serve --host 100.x.y.z --port 8723`（带 token）。
4. 手机 App 填 `http://100.x.y.z:8723` + token。
5. 可选：`tailscale serve` 提供 tailnet 内 HTTPS；此时 App 用 `https://<machine>.<tailnet>.ts.net`，并把该域名加入 `shell_allow_hosts` / `shell_allow_origins`。

### 3.3 Cloudflare Tunnel + Access（不装 App）

前置：自有域名已接入 Cloudflare；安装 `cloudflared`。

1. 建议创建**命名隧道**（named tunnel）并绑定 `wuxing.example.com`；quick tunnel（`trycloudflare.com`）只用于临时测试，不能配 Access。
2. 隧道 origin 指向 **LAN IP + token 的壳服务**（推荐）：
   ```bash
   cloudflared tunnel --url http://192.168.1.5:8723
   ```
   或命名隧道的 ingress：
   ```yaml
   ingress:
     - hostname: wuxing.example.com
       service: http://192.168.1.5:8723
     - service: http_status:404
   ```
3. 壳服务保持 `--host 192.168.1.5` + token（token 守卫生效）。
4. 配置白名单（Host 头是公开域名）：
   ```jsonc
   {
     "shell_allow_hosts": ["wuxing.example.com"],
     "shell_allow_origins": ["https://wuxing.example.com"]
   }
   ```
5. 在 Cloudflare Zero Trust → Access 为 `wuxing.example.com` 建策略（邮箱 OTP / SSO），只允许你自己。
6. 手机浏览器/薄壳填 `https://wuxing.example.com` + token。

> 如果隧道 origin 指向 `127.0.0.60`（环回），壳服务不会安装 token 守卫——此时 Access 是唯一登录门；不建议把环回 origin 与无 Access 的 quick tunnel 组合使用。

### 3.4 frp + VPS（完全自控）

1. VPS 运行 `frps`，配置 TLS/`auth.token`；只开放必要端口。
2. 电脑 `frpc` 把本地壳服务映射到 VPS：
   ```toml
   serverAddr = "vps.example.com"
   serverPort = 7000
   auth.token = "<frp-token>"

   [[proxies]]
   name = "wuxing"
   type = "tcp"
   localIP = "192.168.1.5"
   localPort = 8723
   remotePort = 18723
   ```
3. 壳服务 `--host 192.168.1.5` + token。
4. 通过 VPS 的 `https://wuxing.example.com`（反代 + TLS）访问；在壳配置里加入该域名 Host/Origin 白名单。
5. 建议 frp 只监听本机/防火墙白名单，不要把 `frps` 管理端口暴露公网。

### 3.5 EasyTier（国内 overlay）

1. 电脑与手机安装 EasyTier，加入同一网络（共享节点或自建中继）。
2. 查看电脑虚拟 IP（例如 `10.126.x.y`）。
3. 壳服务：`wuxing shell serve --host 10.126.x.y --port 8723`（带 token）。
4. 手机 App 填 `http://10.126.x.y:8723` + token。

### 3.6 蒲公英 / 花生壳

1. 在服务商控制台创建映射：内网 `192.168.1.5:8723` → 公网域名/端口。
2. 壳服务 `--host 192.168.1.5` + token。
3. 把服务商给的公网域名加入 `shell_allow_hosts` / `shell_allow_origins`。
4. 手机填公网地址 + token；若服务商支持 HTTPS，优先 HTTPS。

## 4. 令牌与吊销纪律

- **生成**：≥32 字节随机值（`secrets.token_urlsafe(32)`）。
- **存放**：优先环境变量 `WUXING_SHELL_TOKEN`；或设置页保存到本机凭据（write-only，界面不回读）。不要写进 `config.jsonc`、README、脚本、截图。
- **轮换**：换新 token → 重启壳服务 → 手机 App 重新填写；旧 token 立即失效。
- **吊销**：停止壳服务 / 移除隧道 / 在 overlay 控制台移除设备 / 关闭 Access 策略。
- **审计**：壳服务失败限速（10 次/60s）与审计事件只记 IP/路径，不落 token；定期检查 `shell_allow_hosts` / `shell_allow_origins` 是否有不再需要的条目。
- **最小暴露**：能 overlay 就不公网；能 Access 就不裸隧道；能绑具体 IP 就不绑 `0.0.0.0`。

## 5. 故障排查

| 现象 | 处理 |
|---|---|
| 403「本地安全校验失败」 | Host 不在白名单：绑定具体 IP（自动加入），或把域名/IP 写入 `shell_allow_hosts`；跨源请求还要 `shell_allow_origins` |
| 401 / 令牌无效 | 检查 `WUXING_SHELL_TOKEN` 是否与 App 填写一致；重启服务后 token 是否变化 |
| 429 | 失败尝试过多，等待 60s；检查是否被扫描 |
| 手机打不开、电脑能开 | 防火墙/路由器 AP 隔离/VPN 未连；确认手机与电脑在同一网络 |
| iOS 提示本地网络权限 | 设置 → WUXING → 本地网络 → 允许；或删除重装 |
| HTTPS 证书错误 | 隧道/反代证书链不完整；自签证书不被 WKWebView 信任 |
| 隧道 502 | 隧道 origin 地址/端口错误，或壳服务未启动 |
| 免费 iOS 签名 7 天后失效 | 用 Sideloadly 重新签装（见 `apps/mobile/ios/README.md`） |

## 6. 已知限制

- LAN HTTP 明文：同网可嗅探 token；长期远程用 overlay/隧道。
- 多端同时操作同一挂起确认：服务端幂等兜底，但多端冲突策略属 P2。
- iOS 免费签名 7 天有效；远程推送/后台常驻不做。
- 三端实机测试目前延期（无实体 iPhone）；本指南的真机验证随设备到位执行。
- 远端 App 只是同一壳服务的第二客户端；引擎、账本、产物仍在电脑上。
