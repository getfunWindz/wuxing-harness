import Foundation

/// 连接 URL 的本地持久化（非密文；令牌只进 Keychain）。
struct ConnectionStore {
    private static let urlKey = "wuxing.connection.url"
    private let defaults: UserDefaults

    init(defaults: UserDefaults = .standard) {
        self.defaults = defaults
    }

    func loadURL() -> String? {
        defaults.string(forKey: Self.urlKey)
    }

    func saveURL(_ value: String) {
        defaults.set(value, forKey: Self.urlKey)
    }

    func clearURL() {
        defaults.removeObject(forKey: Self.urlKey)
    }
}
