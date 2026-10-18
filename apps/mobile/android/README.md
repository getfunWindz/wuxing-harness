# WUXING Android 薄壳（O5 T4-B）

## 构建（Windows / git-bash）

前置：
- **JDK 17+ 且含 jlink**（本机：Temurin 17 → `C:/tmp/jdk/jdk-17.0.20.1+1`）。
  - 注意：DevEco Studio 的 JBR 是精简运行时（**无 jlink**）——AGP 编译 API>=31 的 JdkImageTransform 会失败。
- Android SDK：`platforms;android-36` + `build-tools;36.1.0`（本机 `C:/Users/<user>/AppData/Local/Android/Sdk`）。
- 工程路径含非 ASCII（"Pi 工作区"）——AGP/javac 对非 ASCII 路径不稳，
  统一用 **`subst X:` 映射到 ASCII 盘**后构建（`build.sh` 已封装）。

```bash
cd apps/mobile/android
./build.sh                 # = :app:assembleDebug（自动 subst + JAVA_HOME）
./build.sh :app:testDebugUnitTest
```
产物：`app/build/outputs/apk/debug/app-debug.apk`。

## 设计要点
- 零运行时依赖（平台 Activity + WebView；无 AppCompat/Material/Compose）；JUnit 仅测试。
- 令牌存 **Android Keystore（AES/GCM 密文入 prefs）**；连接＝URL + token → `?token=` 换 HttpOnly cookie。
- 导航白名单＝同源；外部链接出系统浏览器；WebView 禁文件/内容访问、禁混合内容。
- 明文 HTTP 允许（LAN 直连）；overlay/隧道为加密传输；LAN http 下 token 可被同网嗅探（已知威胁模型）。
- 计划与验收：`docs/plans/2026-10-17-wuxing-o5-android-shell.md`。

## 功能（D2-D5）
- 连接配置屏（地址 + 令牌；令牌留空 = 沿用已保存）
- WebView 承载：同源导航白名单（外链出系统浏览器）· 主框架错误层（重试/连接设置）· Chrome<105 版本门槛（可继续/退出）· 返回键先 Web 历史后退
- 原生桥：`window.WuxingNative.notify(title, body)` / `.copy(text)`（Web 侧特性探测）
- 令牌：Android Keystore AES/GCM 加密（密文存 SharedPreferences；异常显式上报）
- 图标：自适应矢量（同 Web favicon 图形）；主题 = 平台 Material Light

## 兼容注意
- **不要使用 Java 10+ 而 Android 低版本未实现的 API**——例：`URLEncoder.encode(String, Charset)` 在 API 30 运行时报 `NoSuchMethodError`（编译期不报）。用 API-1 兼容重载（`encode(String, "UTF-8")`）；改完在 API 30 模拟器上冒烟验证。
- 模拟器（AVD Nexus_5X_API_30）的 WebView 为 Chrome/83 → 会触发版本门槛（预期）；真机需 Chrome 105+。

## 模拟器冒烟
```bash
./build.sh
"$ADB" install -r app/build/outputs/apk/debug/app-debug.apk
"$ADB" shell am start -n com.wuxing.shell/.MainActivity
```
证据快照：`real_test/android_smoke/`（配置屏 / 版本门槛 / 错误层）。
