import UIKit
import WebKit
import WuxingCore

/// WebView 承载屏：同源白名单 + 主框架错误层 + 原生导航（菜单/返回）。
final class WebViewController: UIViewController {
    private let connection: Connection
    private let token: String
    private let store: TokenStoring
    private let connectionStore: ConnectionStore
    private let bridge: NativeBridge

    private var webView: WKWebView!
    private let errorOverlay = UIView()
    private let errorTitle = UILabel()
    private let errorDetail = UILabel()
    private lazy var backItem = UIBarButtonItem(
        image: UIImage(systemName: "chevron.left"),
        style: .plain,
        target: self,
        action: #selector(goBack)
    )
    private var didLoad = false
    private var isMainFrameNavigation = false

    init(connection: Connection,
         token: String,
         store: TokenStoring,
         connectionStore: ConnectionStore) {
        self.connection = connection
        self.token = token
        self.store = store
        self.connectionStore = connectionStore
        self.bridge = NativeBridge(connection: connection)
        super.init(nibName: nil, bundle: nil)
    }

    @available(*, unavailable)
    required init?(coder: NSCoder) {
        fatalError("init(coder:) has not been implemented")
    }

    override func loadView() {
        let container = UIView()
        container.backgroundColor = Theme.paper
        view = container

        let configuration = makeConfiguration()
        webView = WKWebView(frame: .zero, configuration: configuration)
        webView.translatesAutoresizingMaskIntoConstraints = false
        webView.navigationDelegate = self
        webView.uiDelegate = self
        webView.allowsBackForwardNavigationGestures = true
        webView.scrollView.contentInsetAdjustmentBehavior = .never
        webView.isOpaque = false
        webView.backgroundColor = Theme.paper
        container.addSubview(webView)

        setupErrorOverlay(in: container)
        NSLayoutConstraint.activate([
            webView.topAnchor.constraint(equalTo: container.topAnchor),
            webView.leadingAnchor.constraint(equalTo: container.leadingAnchor),
            webView.trailingAnchor.constraint(equalTo: container.trailingAnchor),
            webView.bottomAnchor.constraint(equalTo: container.bottomAnchor),
        ])
    }

    override func viewDidLoad() {
        super.viewDidLoad()
        title = "WUXING"
        navigationItem.rightBarButtonItem = makeMenu()
        updateBackItem()
    }

    override func viewDidAppear(_ animated: Bool) {
        super.viewDidAppear(animated)
        if !didLoad {
            didLoad = true
            loadStartURL()
        }
    }

    override var preferredStatusBarStyle: UIStatusBarStyle {
        .darkContent
    }

    private func makeConfiguration() -> WKWebViewConfiguration {
        let configuration = WKWebViewConfiguration()
        configuration.defaultWebpagePreferences.allowsContentJavaScript = true
        configuration.preferences.javaScriptCanOpenWindowsAutomatically = false
        configuration.allowsInlineMediaPlayback = true
        configuration.mediaTypesRequiringUserActionForPlayback = .all
        configuration.websiteDataStore = .default()
        configuration.userContentController.add(bridge, name: NativeBridge.handlerName)
        configuration.userContentController.addUserScript(
            WKUserScript(
                source: NativeBridge.shimSource,
                injectionTime: .atDocumentStart,
                forMainFrameOnly: true
            )
        )
        return configuration
    }

    private func makeMenu() -> UIBarButtonItem {
        let reload = UIAction(title: "重新加载", image: UIImage(systemName: "arrow.clockwise")) { [weak self] _ in
            self?.reload()
        }
        let settings = UIAction(title: "连接设置", image: UIImage(systemName: "link")) { [weak self] _ in
            self?.openSettings()
        }
        return UIBarButtonItem(
            image: UIImage(systemName: "ellipsis.circle"),
            menu: UIMenu(children: [reload, settings])
        )
    }

    private func setupErrorOverlay(in container: UIView) {
        errorOverlay.translatesAutoresizingMaskIntoConstraints = false
        errorOverlay.backgroundColor = Theme.paper
        errorOverlay.isHidden = true
        container.addSubview(errorOverlay)

        errorTitle.text = "无法连接"
        errorTitle.font = .systemFont(ofSize: 20, weight: .semibold)
        errorTitle.textColor = Theme.ink
        errorTitle.textAlignment = .center

        errorDetail.font = .systemFont(ofSize: 14)
        errorDetail.textColor = Theme.inkSoft
        errorDetail.numberOfLines = 0
        errorDetail.textAlignment = .center

        let retry = Theme.primaryButton(title: "重试")
        retry.addTarget(self, action: #selector(retryTapped), for: .touchUpInside)
        let settings = UIButton(type: .system)
        settings.setTitle("连接设置", for: .normal)
        settings.setTitleColor(Theme.cinnabar, for: .normal)
        settings.titleLabel?.font = .systemFont(ofSize: 15, weight: .medium)
        settings.heightAnchor.constraint(greaterThanOrEqualToConstant: 48).isActive = true
        settings.addTarget(self, action: #selector(openSettings), for: .touchUpInside)

        let buttons = UIStackView(arrangedSubviews: [settings, retry])
        buttons.axis = .horizontal
        buttons.spacing = 12
        buttons.distribution = .fillEqually

        let stack = UIStackView(arrangedSubviews: [errorTitle, errorDetail, buttons])
        stack.translatesAutoresizingMaskIntoConstraints = false
        stack.axis = .vertical
        stack.spacing = 14
        errorOverlay.addSubview(stack)

        let guide = errorOverlay.safeAreaLayoutGuide
        NSLayoutConstraint.activate([
            errorOverlay.topAnchor.constraint(equalTo: container.topAnchor),
            errorOverlay.leadingAnchor.constraint(equalTo: container.leadingAnchor),
            errorOverlay.trailingAnchor.constraint(equalTo: container.trailingAnchor),
            errorOverlay.bottomAnchor.constraint(equalTo: container.bottomAnchor),

            stack.centerYAnchor.constraint(equalTo: guide.centerYAnchor),
            stack.leadingAnchor.constraint(equalTo: guide.leadingAnchor, constant: 28),
            stack.trailingAnchor.constraint(equalTo: guide.trailingAnchor, constant: -28),
            stack.widthAnchor.constraint(lessThanOrEqualToConstant: 360),
        ])
    }

    private func loadStartURL() {
        guard let url = connection.connectURL(token: token) else {
            showError("地址无效，请返回连接设置重新填写。")
            return
        }
        hideError()
        webView.load(URLRequest(url: url))
    }

    private func reload() {
        hideError()
        if webView.url == nil {
            loadStartURL()
        } else {
            webView.reload()
        }
    }

    @objc private func retryTapped() {
        reload()
    }

    @objc private func goBack() {
        webView.goBack()
    }

    @objc private func openSettings() {
        let config = ConfigViewController(
            store: store,
            connectionStore: connectionStore,
            initialURL: connection.baseURL
        )
        navigationController?.pushViewController(config, animated: true)
    }

    private func updateBackItem() {
        navigationItem.leftBarButtonItem = webView?.canGoBack == true ? backItem : nil
    }

    private func showError(_ detail: String, title: String = "无法连接") {
        errorTitle.text = title
        errorDetail.text = detail
        errorOverlay.isHidden = false
        view.bringSubviewToFront(errorOverlay)
    }

    private func hideError() {
        errorOverlay.isHidden = true
    }

    private func handleNavigationError(_ error: Error) {
        let ns = error as NSError
        if ns.domain == NSURLErrorDomain && ns.code == NSURLErrorCancelled {
            return
        }
        guard isMainFrameNavigation else {
            return
        }
        isMainFrameNavigation = false
        let detail = "\(ns.localizedDescription)（\(ns.code)）\n请确认地址/令牌、同一局域网，以及系统「本地网络」权限。"
        showError(detail)
    }
}

extension WebViewController: WKNavigationDelegate {
    func webView(_ webView: WKWebView,
                 decidePolicyFor navigationAction: WKNavigationAction,
                 decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        guard let url = navigationAction.request.url else {
            decisionHandler(.cancel)
            return
        }
        if navigationAction.targetFrame?.isMainFrame == true {
            isMainFrameNavigation = true
            if connection.isInternal(url.absoluteString) {
                decisionHandler(.allow)
                return
            }
            if let scheme = url.scheme?.lowercased(),
               ["http", "https", "mailto", "tel"].contains(scheme) {
                UIApplication.shared.open(url, options: [:], completionHandler: nil)
            }
            decisionHandler(.cancel)
            return
        }
        if url.scheme?.lowercased() == "file" {
            decisionHandler(.cancel)
        } else {
            decisionHandler(.allow)
        }
    }

    func webView(_ webView: WKWebView, didCommit navigation: WKNavigation!) {
        updateBackItem()
    }

    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        isMainFrameNavigation = false
        hideError()
        updateBackItem()
    }

    func webView(_ webView: WKWebView,
                 didFailProvisionalNavigation navigation: WKNavigation!,
                 withError error: Error) {
        handleNavigationError(error)
    }

    func webView(_ webView: WKWebView,
                 didFail navigation: WKNavigation!,
                 withError error: Error) {
        handleNavigationError(error)
    }

    func webViewWebContentProcessDidTerminate(_ webView: WKWebView) {
        showError("页面进程已终止，请重试。", title: "页面已停止")
    }
}

extension WebViewController: WKUIDelegate {
    func webView(_ webView: WKWebView,
                 createWebViewWith configuration: WKWebViewConfiguration,
                 for navigationAction: WKNavigationAction,
                 windowFeatures: WKWindowFeatures) -> WKWebView? {
        guard let url = navigationAction.request.url else {
            return nil
        }
        if connection.isInternal(url.absoluteString) {
            webView.load(URLRequest(url: url))
        } else if let scheme = url.scheme?.lowercased(),
                  ["http", "https", "mailto", "tel"].contains(scheme) {
            UIApplication.shared.open(url, options: [:], completionHandler: nil)
        }
        return nil
    }
}
