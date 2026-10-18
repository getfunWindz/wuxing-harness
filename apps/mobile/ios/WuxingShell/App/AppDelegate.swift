import UIKit

@main
final class AppDelegate: UIResponder, UIApplicationDelegate {
    func application(_ application: UIApplication,
                     didFinishLaunchingWithOptions launchOptions: [UIApplication.LaunchOptionsKey: Any]?) -> Bool {
        NotificationService.shared.configure()
        // 单元测试宿主不弹系统授权框；正常运行时启动即请求（与 Android/鸿蒙同口径）
        if ProcessInfo.processInfo.environment["XCTestConfigurationFilePath"] == nil {
            NotificationService.shared.requestAuthorizationIfNeeded()
        }
        return true
    }
}
