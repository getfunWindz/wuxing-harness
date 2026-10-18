# WUXING iOS 薄壳（O5 T4-D）

无签名、可侧载的 iPhone 薄壳：配置电脑上 WUXING 壳服务的地址与令牌，用 `WKWebView` 承载同一套 Web UI，并提供最小原生桥（通知 / 剪贴板）。

> 当前范围：**只做 iPhone**；**向最新 iOS SDK 适配、不向后适配**；**不上架 App Store**。免费侧载签名 7 天有效，到期需重签。

## 目录

```
apps/mobile/ios/
├─ project.yml                  # XcodeGen 工程定义
├─ Core/                        # SwiftPM 纯 Foundation 逻辑（可独立单测）
│  ├─ Sources/WuxingCore/       # Connection / ConnectionForm / TokenStoring
│  └─ Tests/WuxingCoreTests/
├─ WuxingShell/
│  ├─ App/                      # AppDelegate / SceneDelegate
│  ├─ Services/                 # Keychain / 通知 / 原生桥 / 连接 URL
│  ├─ UI/                       # 主题 / 配置屏 / WebView
│  └─ Resources/                # Info.plist / Assets.xcassets
├─ WuxingShellTests/            # Keychain 集成测试（模拟器）
├─ scripts/make_icon.py         # 由 favicon 图形生成 AppIcon
└─ README.md
```

## 构建

### 方式 A：GitHub Actions（推荐，无需 Mac）

工作流：`.github/workflows/ios-unsigned.yml`。触发：

- 手动：Actions → **iOS Unsigned Build** → Run workflow；
- 或推送 `apps/mobile/ios/**` 的改动。

CI 会：

1. `swift test --package-path apps/mobile/ios/Core`；
2. `xcodegen generate` + `xcodebuild test`（模拟器）；
3. 用 runner 的**最新 iOS SDK** 做无签名 Release device build（`CODE_SIGNING_ALLOWED=NO`）；
4. 打包 `WuxingShell-unsigned.ipa`、`.app.zip`、dSYM、日志与 SHA256；
5. 上传 artifact `wuxing-ios-unsigned`。

产物摘要会打印 `Bundle ID` 与 `MinimumOSVersion`。**`MinimumOSVersion` 等于当次 CI 使用的最新 SDK 版本**；设备 iOS 低于该版本无法安装。如需固定到某个版本，改 `project.yml` 的 `deploymentTarget` / CI 的 `IPHONEOS_DEPLOYMENT_TARGET`。

### 方式 B：本机 macOS

前置：Xcode（含 iOS SDK）、XcodeGen。

```bash
cd apps/mobile/ios
brew install xcodegen
xcodegen generate
swift test --package-path Core
xcodebuild test -project WuxingShell.xcodeproj -scheme WuxingShell \
  -destination 'platform=iOS Simulator,name=iPhone 16'
```

无签名 device 构建：

```bash
SDK=$(xcrun --sdk iphoneos --show-sdk-version)
xcodebuild -project WuxingShell.xcodeproj -scheme WuxingShell \
  -configuration Release -sdk iphoneos -destination 'generic/platform=iOS' \
  IPHONEOS_DEPLOYMENT_TARGET="$SDK" \
  CODE_SIGNING_ALLOWED=NO CODE_SIGNING_REQUIRED=NO CODE_SIGN_IDENTITY="" build
```

## Windows 侧载（Sideloadly + 免费 Apple ID）

1. 安装 **Sideloadly**（sideloadly.io）与 **Apple Devices**（Apple 官网，Microsoft Store 版本常缺驱动）。
2. iPhone 连接电脑，解锁并「信任此电脑」。
3. 下载 CI artifact，解压得到 `WuxingShell-unsigned.ipa`。
4. 打开 Sideloadly，把 IPA 拖入，选择你的 iPhone，输入 **免费 Apple ID**（Sideloadly 会用免费个人团队重签）。按提示完成双重认证。
5. 安装完成后，在 iPhone「设置 → 通用 → VPN 与设备管理」信任你的开发者证书。
6. 打开 WUXING：
   - 首次启动允许「本地网络」（访问 192.168.x.x:8723 必需）；
   - 填写壳服务地址（例如 `http://192.168.1.5:8723`）与 `WUXING_SHELL_TOKEN`；
   - 令牌留空 = 沿用 Keychain 已保存值。

**免费签名限制**：7 天有效期、最多 3 个自签 App、每个 Apple ID 每周最多 10 个 App ID；到期用 Sideloadly 重新安装即可（重新签名会保留应用内 Keychain 令牌与 UserDefaults）。远程推送、App Store 分发不可用。

## 安全与威胁模型

- **明文 HTTP 允许**（LAN 直连台阶；overlay/隧道为加密传输）。同网可嗅探 `?token=` 首次换发请求——与 Android/鸿蒙薄壳同一威胁模型；生产建议 overlay/隧道 + 远程鉴权档。
- `NSAllowsArbitraryLoads=true` 仅因用户可以填写任意 LAN 地址；不用于公网服务。
- 令牌只存 **Keychain**（`kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly`），不写 UserDefaults、不写日志；Keychain 异常在配置页显式提示，不降级明文。
- WebView 导航白名单 = 连接 origin；外部链接交系统浏览器；`file:` 拒绝。
- 原生桥只接受主框架 + 同源 `securityOrigin` 的 `notify` / `copy` 消息。

## 功能与限制

- 配置屏（URL + 令牌；令牌留空沿用；错误可见）。
- WKWebView 承载：同源白名单、错误层（重试 / 连接设置）、右滑返回、可后退时显示返回箭头。
- 原生导航栏：标题 WUXING；右侧菜单「重新加载 / 连接设置」。
- 原生桥：`window.WuxingNative.notify(title, body)`、`.copy(text)`。
- 通知：本地通知（`UNUserNotificationCenter`）；Web 端现有挂起通知走 Web Notification API，WKWebView 不支持该 API，因此桥暂为同构预留面。
- 不做：App Store、远程推送、后台常驻、iPad 专属布局、旧 iOS 兼容。

## 故障排查

| 现象 | 处理 |
|---|---|
| 安装后提示「未受信任的开发者」 | 设置 → 通用 → VPN 与设备管理 → 信任 |
| 打开后一直「无法连接」 | 检查手机与电脑同一局域网、地址/端口、令牌；确认壳服务以 `--host 0.0.0.0`（或 LAN 地址）启动并配置了 token |
| 本地网络权限被拒 | 设置 → WUXING → 本地网络 → 打开；或删除重装触发提示 |
| HTTP 被拦 | 本项目已允许明文 HTTP；若使用 HTTPS 自签证书，WKWebView 仍会拒绝，需受信证书或改用隧道 |
| 7 天后打不开 | 免费签名过期；用 Sideloadly 重新签装 |
| Bundle ID 冲突 | 改 `project.yml` 的 `PRODUCT_BUNDLE_IDENTIFIER` 后重新构建；Sideloadly 会按新 ID 注册 |
| `MinimumOSVersion` 高于设备 | CI 用的是最新 SDK；降低 `IPHONEOS_DEPLOYMENT_TARGET` 后重跑（不承诺旧系统兼容） |
