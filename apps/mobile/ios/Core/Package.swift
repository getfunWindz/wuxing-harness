// swift-tools-version:5.9
import PackageDescription

let package = Package(
    name: "WuxingCore",
    platforms: [.iOS(.v15), .macOS(.v12)],
    products: [.library(name: "WuxingCore", targets: ["WuxingCore"])],
    targets: [
        .target(name: "WuxingCore"),
        .testTarget(name: "WuxingCoreTests", dependencies: ["WuxingCore"]),
    ]
)
