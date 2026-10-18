import Foundation

/// 连接模型（纯 Foundation，可在 Linux/CI 单测）：
/// URL 规范化 + origin + 令牌换发 URL + 同源白名单。
///
/// 约定（与 Android 薄壳对齐）：
/// - base = scheme://host[:port][/path]（无尾斜杠）；
/// - origin = scheme://host[:port]（默认端口省略；IPv6 加方括号）；
/// - 同源判断按 scheme + host + 有效端口，不按字符串前缀。
public struct Connection: Equatable {
    public let scheme: String
    public let host: String
    public let port: Int
    public let path: String

    /// 解析用户输入（允许省略 scheme，默认 http）；非法 → nil。
    public init?(raw: String?) {
        guard let text = raw?.trimmingCharacters(in: .whitespacesAndNewlines),
              !text.isEmpty else {
            return nil
        }
        let candidate = text.contains("://") ? text : "http://" + text
        guard let components = URLComponents(string: candidate) else {
            return nil
        }
        let scheme = (components.scheme ?? "").lowercased()
        guard scheme == "http" || scheme == "https" else {
            return nil
        }
        guard var host = components.host?.lowercased(), !host.isEmpty else {
            return nil
        }
        if host.hasPrefix("["), host.hasSuffix("]") {
            host = String(host.dropFirst().dropLast())
        }
        let effectivePort: Int
        if let explicit = components.port {
            guard explicit > 0, explicit <= 65535 else {
                return nil
            }
            effectivePort = explicit
        } else {
            effectivePort = scheme == "https" ? 443 : 80
        }
        var path = components.percentEncodedPath
        while path.hasSuffix("/") {
            path.removeLast()
        }
        self.scheme = scheme
        self.host = host
        self.port = effectivePort
        self.path = path
    }

    /// scheme://host[:port]（默认端口省略；IPv6 加方括号）。
    public var origin: String {
        let hostPart = host.contains(":") ? "[\(host)]" : host
        let defaultPort = scheme == "https" ? 443 : 80
        let portPart = port == defaultPort ? "" : ":\(port)"
        return "\(scheme)://\(hostPart)\(portPart)"
    }

    /// origin + path（无尾斜杠）。
    public var baseURL: String {
        origin + path
    }

    /// 首次访问 URL：`<base>/?token=...`（服务端 302 换 HttpOnly cookie）。
    /// token 按 RFC3986 unreserved 编码，`+ / = &` 等全部百分号转义。
    public func connectURL(token: String) -> URL? {
        let encoded = token.addingPercentEncoding(
            withAllowedCharacters: Connection.unreserved
        ) ?? ""
        return URL(string: baseURL + "/?token=" + encoded)
    }

    /// 导航白名单：about:blank 或同源（scheme + host + 有效端口）。
    public func isInternal(_ raw: String?) -> Bool {
        guard let text = raw?.trimmingCharacters(in: .whitespacesAndNewlines),
              !text.isEmpty else {
            return false
        }
        if text.lowercased() == "about:blank" {
            return true
        }
        guard let components = URLComponents(string: text) else {
            return false
        }
        let scheme = (components.scheme ?? "").lowercased()
        guard scheme == self.scheme else {
            return false
        }
        guard var host = components.host?.lowercased(), !host.isEmpty else {
            return false
        }
        if host.hasPrefix("["), host.hasSuffix("]") {
            host = String(host.dropFirst().dropLast())
        }
        guard host == self.host else {
            return false
        }
        let effectivePort: Int
        if let explicit = components.port {
            guard explicit > 0, explicit <= 65535 else {
                return false
            }
            effectivePort = explicit
        } else {
            effectivePort = scheme == "https" ? 443 : 80
        }
        return effectivePort == port
    }

    private static let unreserved = CharacterSet(
        charactersIn: "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~"
    )
}
