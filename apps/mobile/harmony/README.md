# WUXING 鸿蒙薄壳（HarmonyOS NEXT · ArkTS）

## 构建（Windows / git-bash）

前置：
- DevEco Studio 6.0.2（内置 hvigor/ohpm/node18）+ SDK **HarmonyOS 6.0.2 / API 22**
  （`DEVECO_SDK_HOME` 指向 `…/DevEco Studio/sdk`）
- **hvigor 要求纯 ASCII 工程路径**（`subst X:` 映射也不生效）→ `build.sh` 镜像到
  `C:\tmp\wuxing-harmony-build` 构建，再把 HAP 回拷到仓库。

```bash
cd apps/mobile/harmony
./build.sh            # = assembleHap（镜像构建 + 回拷 entry/build/outputs/）
```
产物：`entry/build/outputs/entry-default-unsigned.hap`
（**unsigned HAP 可直接装模拟器**；真机需签名，见 P2）

## 设计与安全
- 配置屏：地址 + 令牌；令牌入 **AssetStore**（`alias=wuxing.shell.token`），URL 入 preferences（非密文）
- Web 承载：`@kit.ArkWeb` Web 组件；`onLoadIntercept` 同源白名单（非同源阻断）；主框架错误条（重试/设置）
- 原生桥：`window.WuxingNative.notify(title, body)` / `.copy(text)`（`javaScriptProxy`）
- 明文 HTTP：HarmonyOS **默认允许**（`networkSecurityConfig` 默认 `cleartextTrafficPermitted=true`）——
  LAN 直连台阶；overlay/隧道为加密传输；威胁模型同 Android（同网可嗅探 token）
- SDK 兼容：`compatibleSdkVersion=5.0.0(12)` / `targetSdkVersion=6.0.2(22)`
  （本机模拟器镜像 6.0.1 可安装；target 保持 22 编译）

## 模拟器冒烟（已验证）
- HVD：`Mate 70 Pro`（Emulator 6.0.2.200，镜像 6.0.1）
- HDC：`…/DevEco Studio/sdk/default/openharmony/toolchains/hdc.exe`
- 流程：`hdc -t <target> install <hap>` → `aa start -b com.wuxing.shell -a EntryAbility`
  → `uitest dumpLayout` / `uiInput click|text` / `screenCap`
- 证据：`real_test/harmony_smoke/`（配置屏 / 连接后错误态 `ERR_UNSAFE_PORT`）

## 注意
- `getContext` 在 API 22 已弃用（警告）——P2 迁移 `this.getUIContext().getHostContext()`
- `bm clean` 需 `-c|-d`；自动化输入前先 force-stop/start 清焦点残留
- P2：真机签名/发布、图标定制、通知点击回前台、外部链接拉起浏览器
