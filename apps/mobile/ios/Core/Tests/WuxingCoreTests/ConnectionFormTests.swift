import XCTest
@testable import WuxingCore

final class ConnectionFormTests: XCTestCase {
    func testResolvesURLAndToken() throws {
        let result = ConnectionForm.resolve(
            rawURL: "192.168.1.5:8723", rawToken: " abc ", savedToken: nil
        )
        let value = try result.get()
        XCTAssertEqual(value.connection.baseURL, "http://192.168.1.5:8723")
        XCTAssertEqual(value.token, "abc")
    }

    func testEmptyTokenUsesSavedToken() throws {
        let result = ConnectionForm.resolve(
            rawURL: "http://h:8723", rawToken: "  ", savedToken: " saved "
        )
        let value = try result.get()
        XCTAssertEqual(value.token, "saved")
    }

    func testInvalidURL() {
        XCTAssertEqual(
            ConnectionForm.resolve(rawURL: "ftp://x", rawToken: "t", savedToken: nil),
            .failure(.invalidURL)
        )
    }

    func testMissingToken() {
        XCTAssertEqual(
            ConnectionForm.resolve(rawURL: "http://h:8723", rawToken: " ", savedToken: " "),
            .failure(.missingToken)
        )
    }
}
