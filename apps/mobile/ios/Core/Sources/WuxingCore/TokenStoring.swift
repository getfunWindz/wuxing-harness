import Foundation

/// 令牌存储抽象（Core 不依赖 Security；具体 Keychain 实现放在 App 目标）。
public protocol TokenStoring {
    func load() throws -> String?
    func save(_ token: String) throws
    func clear() throws
}

/// 令牌存储错误：status = Keychain OSStatus（或调用方定义的等价码）。
public enum TokenStoreError: Error, Equatable {
    case status(Int32)
}
