import { webview } from '@kit.ArkWeb';
import { common } from '@kit.AbilityKit';
import { WebBridge } from '../service/WebBridge';

@Component
export struct WebViewPage {
  @Prop connectUrl: string = '';
  @Prop origin: string = '';
  onSettings: () => void = (): void => {};
  @State private errorText: string = '';
  private controller: webview.WebviewController = new webview.WebviewController();
  private bridge: WebBridge =
    new WebBridge(getContext(this) as common.UIAbilityContext);

  private isInternal(url: string): boolean {
    return url === this.origin || url.startsWith(this.origin + '/');
  }

  build() {
    Column() {
      if (this.errorText.length > 0) {
        Row({ space: 8 }) {
          Text(this.errorText)
            .fontSize(12)
            .layoutWeight(1)
          Button('重试')
            .height(36)
            .onClick(() => {
              this.errorText = '';
              this.controller.refresh();
            })
          Button('设置')
            .height(36)
            .onClick(() => {
              this.onSettings();
            })
        }
        .padding({ left: 12, right: 12, top: 6, bottom: 6 })
        .backgroundColor('#EFE7DB')
        .id('web-error')
      }
      Web({ src: this.connectUrl, controller: this.controller })
        .javaScriptAccess(true)
        .domStorageAccess(true)
        .fileAccess(false)
        .mixedMode(MixedMode.None)
        .javaScriptProxy({
          object: this.bridge,
          name: 'WuxingNative',
          methodList: ['notify', 'copy'],
          controller: this.controller
        })
        .onLoadIntercept((event) => {
          const target: string = event.data.getRequestUrl();
          if (this.isInternal(target)) {
            return false;
          }
          console.info(`[wuxing] blocked external navigation: ${target}`);
          return true;
        })
        .onErrorReceive((event) => {
          this.errorText = '无法连接：' + event.error.getErrorInfo();
        })
        .width('100%')
        .layoutWeight(1)
    }
    .width('100%')
    .height('100%')
  }
}
