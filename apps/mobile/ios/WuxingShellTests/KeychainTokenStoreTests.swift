import XCTest
import WuxingCore
@testable import WuxingShell

final class KeychainTokenStoreTests: XCTestCase {
    func testSaveLoadClear() throws {
        let store = KeychainTokenStore(
            service: "com.wuxing.shell.tests.\(UUID().uuidString)",
            account: "token"
        )
        try store.clear()
        XCTAssertNil(try store.load())
        try store.save("abc+/=")
        XCTAssertEqual(try store.load(), "abc+/=")
        try store.clear()
        XCTAssertNil(try store.load())
    }

    func testOverwrite() throws {
        let store = KeychainTokenStore(
            service: "com.wuxing.shell.tests.\(UUID().uuidString)",
            account: "token"
        )
        try store.save("one")
        try store.save("two")
        XCTAssertEqual(try store.load(), "two")
        try store.clear()
    }
}

final class ConnectionStoreTests: XCTestCase {
    func testSaveLoadClear() {
        let suite = "wuxing.shell.tests.\(UUID().uuidString)"
        guard let defaults = UserDefaults(suiteName: suite) else {
            XCTFail("cannot create UserDefaults suite")
            return
        }
        defer { defaults.removePersistentDomain(forName: suite) }
        let store = ConnectionStore(defaults: defaults)
        XCTAssertNil(store.loadURL())
        store.saveURL("http://host:8723")
        XCTAssertEqual(store.loadURL(), "http://host:8723")
        store.clearURL()
        XCTAssertNil(store.loadURL())
    }
}
