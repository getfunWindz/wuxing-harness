import UIKit
import WuxingCore

final class SceneDelegate: UIResponder, UIWindowSceneDelegate {
    var window: UIWindow?

    func scene(_ scene: UIScene,
               willConnectTo session: UISceneSession,
               options connectionOptions: UIScene.ConnectionOptions) {
        guard let windowScene = scene as? UIWindowScene else {
            return
        }
        let window = UIWindow(windowScene: windowScene)
        window.overrideUserInterfaceStyle = .light

        let navigation = UINavigationController()
        let appearance = Theme.navigationBarAppearance()
        navigation.navigationBar.standardAppearance = appearance
        navigation.navigationBar.scrollEdgeAppearance = appearance
        navigation.navigationBar.compactAppearance = appearance
        navigation.navigationBar.tintColor = Theme.cinnabar

        let tokenStore = KeychainTokenStore()
        let connectionStore = ConnectionStore()
        let savedURL = connectionStore.loadURL()
        let savedToken = (try? tokenStore.load()) ?? nil

        if let savedURL,
           let connection = Connection(raw: savedURL),
           let savedToken,
           !savedToken.isEmpty {
            let web = WebViewController(
                connection: connection,
                token: savedToken,
                store: tokenStore,
                connectionStore: connectionStore
            )
            navigation.setViewControllers([web], animated: false)
        } else {
            let config = ConfigViewController(
                store: tokenStore,
                connectionStore: connectionStore,
                initialURL: savedURL ?? ""
            )
            navigation.setViewControllers([config], animated: false)
        }

        window.rootViewController = navigation
        window.makeKeyAndVisible()
        self.window = window
    }
}
