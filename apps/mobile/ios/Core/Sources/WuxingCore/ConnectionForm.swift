import Foundation

/// 配置表单校验（纯逻辑）：URL 解析 + 令牌回退（留空 = 沿用已保存值）。
public enum ConnectionFormError: Error, Equatable {
    case invalidURL
    case missingToken
}

public struct ConnectionFormResult: Equatable {
    public let connection: Connection
    public let token: String

    public init(connection: Connection, token: String) {
        self.connection = connection
        self.token = token
    }
}

public enum ConnectionForm {
    public static func resolve(
        rawURL: String,
        rawToken: String,
        savedToken: String?
    ) -> Result<ConnectionFormResult, ConnectionFormError> {
        guard let connection = Connection(raw: rawURL) else {
            return .failure(.invalidURL)
        }
        let typed = rawToken.trimmingCharacters(in: .whitespacesAndNewlines)
        let saved = (savedToken ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
        let token = typed.isEmpty ? saved : typed
        guard !token.isEmpty else {
            return .failure(.missingToken)
        }
        return .success(ConnectionFormResult(connection: connection, token: token))
    }
}
