import UIKit
import WebKit
import WuxingCore

/// WebView 原生桥（最小集）：通知 + 剪贴板。
/// Web 侧以 window.WuxingNative 特性探测；安全边界由同源白名单 + securityOrigin 校验保证。
final class NativeBridge: NSObject, WKScriptMessageHandler {
    static let handlerName = "wuxingNative"

    static let shimSource = """
    (function() {
      if (!window.webkit || !window.webkit.messageHandlers || !window.webkit.messageHandlers.wuxingNative) return;
      var h = window.webkit.messageHandlers.wuxingNative;
      window.WuxingNative = {
        notify: function(title, body) {
          h.postMessage({
            op: "notify",
            title: String(title == null ? "" : title),
            body: String(body == null ? "" : body)
          });
          return true;
        },
        copy: function(text) {
          h.postMessage({ op: "copy", text: String(text == null ? "" : text) });
          return true;
        }
      };
    })();
    """

    private let connection: Connection
    private let notifications: NotificationService

    init(connection: Connection, notifications: NotificationService = .shared) {
        self.connection = connection
        self.notifications = notifications
        super.init()
    }

    func userContentController(_ userContentController: WKUserContentController,
                               didReceive message: WKScriptMessage) {
        guard message.name == Self.handlerName, message.frameInfo.isMainFrame else {
            return
        }
        guard originMatches(message.frameInfo.securityOrigin) else {
            return
        }
        guard let body = message.body as? [String: Any],
              let op = body["op"] as? String else {
            return
        }
        switch op {
        case "notify":
            notifications.notify(
                title: body["title"] as? String ?? "",
                body: body["body"] as? String ?? ""
            )
        case "copy":
            UIPasteboard.general.string = body["text"] as? String ?? ""
        default:
            break
        }
    }

    private func originMatches(_ origin: WKSecurityOrigin) -> Bool {
        var components = URLComponents()
        components.scheme = origin.`protocol`
        var host = origin.host
        if host.contains(":") && !host.hasPrefix("[") {
            host = "[\(host)]"
        }
        components.host = host
        if origin.port != 0 {
            components.port = origin.port
        }
        guard let url = components.url else {
            return false
        }
        return connection.isInternal(url.absoluteString)
    }
}
