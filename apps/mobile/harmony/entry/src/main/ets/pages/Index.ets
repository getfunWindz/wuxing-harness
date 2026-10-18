import { common } from '@kit.AbilityKit';
import { preferences } from '@kit.ArkData';
import { BusinessError } from '@kit.BasicServicesKit';
import { notificationManager } from '@kit.NotificationKit';
import { Connection } from '../model/Connection';
import { TokenVault } from '../service/TokenVault';
import { ConfigView } from '../view/ConfigView';
import { WebViewPage } from '../view/WebViewPage';

const PREFS: string = 'wuxing_connection';
const KEY_URL: string = 'url';

/** 状态机：配置 ⇄ Web（令牌入 AssetStore；URL 入 preferences）。 */
@Entry
@Component
struct Index {
  @State mode: string = 'config';
  @State url: string = '';
  @State status: string = '';
  @State tokenSaved: boolean = false;
  @State webConnectUrl: string = '';
  @State webOrigin: string = '';
  private context: common.UIAbilityContext =
    getContext(this) as common.UIAbilityContext;

  aboutToAppear(): void {
    this.init();
  }

  private async init(): Promise<void> {
    try {
      const prefs = await preferences.getPreferences(this.context, PREFS);
      this.url = prefs.getSync(KEY_URL, '') as string;
      const token = await TokenVault.load();
      this.tokenSaved = token !== null && token.length > 0;
      const parsed = Connection.parse(this.url);
      if (parsed !== null && token !== null && token.length > 0) {
        this.webConnectUrl = parsed.connectUrl(token);
        this.webOrigin = parsed.originUrl();
        this.mode = 'web';
      }
    } catch (err) {
      this.status = '初始化失败：' + (err as BusinessError).message;
    }
    try {
      await notificationManager.requestEnableNotification(this.context);
    } catch (err) {
      // 通知未授权：桥的 notify 返回 false（不阻断主流程）
    }
  }

  private async connect(rawUrl: string, rawToken: string): Promise<void> {
    const parsed = Connection.parse(rawUrl);
    if (parsed === null) {
      this.status = '地址无效（需 http/https 主机）';
      return;
    }
    let token: string = rawToken.trim();
    if (token.length === 0) {
      const saved = await TokenVault.load();
      token = saved === null ? '' : saved;
    }
    if (token.length === 0) {
      this.status = '令牌不能为空';
      return;
    }
    try {
      await TokenVault.save(token);
    } catch (err) {
      this.status = '安全存储不可用：' + (err as BusinessError).message;
      return;
    }
    const prefs = await preferences.getPreferences(this.context, PREFS);
    await prefs.put(KEY_URL, parsed.baseUrl());
    await prefs.flush();
    this.status = '';
    this.tokenSaved = true;
    this.url = parsed.baseUrl();
    this.webConnectUrl = parsed.connectUrl(token);
    this.webOrigin = parsed.originUrl();
    this.mode = 'web';
  }

  build() {
    Column() {
      if (this.mode === 'config') {
        ConfigView({
          url: this.url,
          status: this.status,
          tokenSaved: this.tokenSaved,
          onConnect: (url: string, token: string): void => {
            this.connect(url, token);
          }
        })
      } else {
        WebViewPage({
          connectUrl: this.webConnectUrl,
          origin: this.webOrigin,
          onSettings: (): void => {
            this.mode = 'config';
          }
        })
      }
    }
    .width('100%')
    .height('100%')
    .backgroundColor('#F7F4EF')
  }
}
