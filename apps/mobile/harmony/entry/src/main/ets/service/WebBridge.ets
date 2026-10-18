import { common } from '@kit.AbilityKit';
import { BusinessError, pasteboard } from '@kit.BasicServicesKit';
import { notificationManager } from '@kit.NotificationKit';

/**
 * WebView 原生桥（最小集）：通知 + 剪贴板。
 * Web 侧以 window.WuxingNative 特性探测；安全边界由 WebView 同源白名单控制。
 */
export class WebBridge {
  private context: common.UIAbilityContext;

  constructor(context: common.UIAbilityContext) {
    this.context = context;
  }

  notify(title: string, body: string): boolean {
    try {
      const request: notificationManager.NotificationRequest = {
        id: 1,
        content: {
          notificationContentType: notificationManager.ContentType.NOTIFICATION_CONTENT_BASIC_TEXT,
          normal: {
            title: title,
            text: body
          }
        }
      };
      notificationManager.publish(request, (err: BusinessError) => {
        if (err) {
          console.error(`[WuxingNative.notify] failed: ${err.code} ${err.message}`);
        }
      });
      return true;
    } catch (err) {
      // 通知未授权/服务不可用：返回 false（Web 侧降级）
      return false;
    }
  }

  copy(text: string): boolean {
    try {
      const data: pasteboard.PasteData =
        pasteboard.createData(pasteboard.MIMETYPE_TEXT_PLAIN, text);
      pasteboard.getSystemPasteboard().setData(data).catch((err: BusinessError) => {
        console.error(`[WuxingNative.copy] failed: ${err.code} ${err.message}`);
      });
      return true;
    } catch (err) {
      return false;
    }
  }
}
