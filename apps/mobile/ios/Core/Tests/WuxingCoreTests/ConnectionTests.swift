import XCTest
@testable import WuxingCore

final class ConnectionTests: XCTestCase {
    func testParseAddsHTTPAndNormalizes() throws {
        let c = try XCTUnwrap(Connection(raw: "192.168.1.5:8723"))
        XCTAssertEqual(c.origin, "http://192.168.1.5:8723")
        XCTAssertEqual(c.baseURL, "http://192.168.1.5:8723")
    }

    func testParseKeepsBasePathAndStripsTrailingSlash() throws {
        let c = try XCTUnwrap(Connection(raw: "http://Host:8723/next/"))
        XCTAssertEqual(c.origin, "http://host:8723")
        XCTAssertEqual(c.baseURL, "http://host:8723/next")
    }

    func testDefaultPortsAreOmittedButComparedEffectively() throws {
        let http = try XCTUnwrap(Connection(raw: "http://h:80"))
        XCTAssertEqual(http.origin, "http://h")
        XCTAssertTrue(http.isInternal("http://h/x"))
        let https = try XCTUnwrap(Connection(raw: "https://h"))
        XCTAssertEqual(https.origin, "https://h")
    }

    func testIPv6OriginHasBrackets() throws {
        let c = try XCTUnwrap(Connection(raw: "http://[::1]:8723"))
        XCTAssertEqual(c.origin, "http://[::1]:8723")
        XCTAssertTrue(c.isInternal("http://[::1]:8723/next/"))
    }

    func testRejectsGarbage() {
        XCTAssertNil(Connection(raw: nil))
        XCTAssertNil(Connection(raw: ""))
        XCTAssertNil(Connection(raw: "ftp://x"))
        XCTAssertNil(Connection(raw: "http://"))
        XCTAssertNil(Connection(raw: "http:///x"))
    }

    func testConnectURLEncodesToken() throws {
        let c = try XCTUnwrap(Connection(raw: "http://h:8723"))
        let url = try XCTUnwrap(c.connectURL(token: "a+b/c=d&e"))
        XCTAssertEqual(url.absoluteString, "http://h:8723/?token=a%2Bb%2Fc%3Dd%26e")
    }

    func testIsInternalComparesOriginNotPrefix() throws {
        let c = try XCTUnwrap(Connection(raw: "http://h:8723"))
        XCTAssertTrue(c.isInternal("http://h:8723/next/"))
        XCTAssertTrue(c.isInternal("http://h:8723"))
        XCTAssertTrue(c.isInternal("about:blank"))
        XCTAssertFalse(c.isInternal("http://h:8723.evil.com/x"))
        XCTAssertFalse(c.isInternal("https://h:8723/"))
        XCTAssertFalse(c.isInternal("http://h:9999/"))
        XCTAssertFalse(c.isInternal("http://h:8723@evil.com/"))
        XCTAssertFalse(c.isInternal("file:///etc/passwd"))
    }
}
