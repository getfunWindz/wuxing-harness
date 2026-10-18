import UIKit
import WuxingCore

/// 连接配置屏：地址 + 令牌（留空沿用已保存令牌）。
final class ConfigViewController: UIViewController, UITextFieldDelegate {
    private let store: TokenStoring
    private let connectionStore: ConnectionStore
    private let initialURL: String
    private let initialStatus: String?

    private let scrollView = UIScrollView()
    private let stack = UIStackView()
    private let urlField = UITextField()
    private let tokenField = UITextField()
    private let statusLabel = UILabel()
    private var keyboardObservers: [NSObjectProtocol] = []

    init(store: TokenStoring,
         connectionStore: ConnectionStore,
         initialURL: String = "",
         initialStatus: String? = nil) {
        self.store = store
        self.connectionStore = connectionStore
        self.initialURL = initialURL
        self.initialStatus = initialStatus
        super.init(nibName: nil, bundle: nil)
    }

    @available(*, unavailable)
    required init?(coder: NSCoder) {
        fatalError("init(coder:) has not been implemented")
    }

    deinit {
        keyboardObservers.forEach(NotificationCenter.default.removeObserver)
    }

    override func viewDidLoad() {
        super.viewDidLoad()
        title = "连接 WUXING"
        view.backgroundColor = Theme.paper
        setupViews()
        applyInitialValues()
        observeKeyboard()
    }

    override func viewDidAppear(_ animated: Bool) {
        super.viewDidAppear(animated)
        if urlField.text?.isEmpty ?? true {
            urlField.becomeFirstResponder()
        }
    }

    override var preferredStatusBarStyle: UIStatusBarStyle {
        .darkContent
    }

    private func setupViews() {
        scrollView.translatesAutoresizingMaskIntoConstraints = false
        scrollView.keyboardDismissMode = .interactive
        scrollView.alwaysBounceVertical = true
        view.addSubview(scrollView)

        stack.translatesAutoresizingMaskIntoConstraints = false
        stack.axis = .vertical
        stack.spacing = 12
        scrollView.addSubview(stack)

        let title = UILabel()
        title.text = "WUXING"
        title.font = .systemFont(ofSize: 28, weight: .semibold)
        title.textColor = Theme.ink

        let intro = UILabel()
        intro.text = "填写电脑上 WUXING 壳服务的地址与访问令牌。"
        intro.font = .systemFont(ofSize: 14)
        intro.textColor = Theme.inkSoft
        intro.numberOfLines = 0

        let urlLabel = UILabel()
        urlLabel.text = "地址"
        urlLabel.font = .systemFont(ofSize: 13, weight: .medium)
        urlLabel.textColor = Theme.inkSoft

        configureField(urlField, placeholder: "http://192.168.1.5:8723")
        urlField.keyboardType = .URL
        urlField.accessibilityLabel = "服务地址"
        urlField.returnKeyType = .next
        urlField.delegate = self

        let tokenLabel = UILabel()
        tokenLabel.text = "访问令牌（WUXING_SHELL_TOKEN）"
        tokenLabel.font = .systemFont(ofSize: 13, weight: .medium)
        tokenLabel.textColor = Theme.inkSoft

        configureField(tokenField, placeholder: "留空 = 沿用已保存令牌")
        tokenField.isSecureTextEntry = true
        tokenField.accessibilityLabel = "访问令牌"
        tokenField.returnKeyType = .done
        tokenField.delegate = self

        let connect = Theme.primaryButton(title: "连接")
        connect.accessibilityLabel = "连接"
        connect.addTarget(self, action: #selector(connectTapped), for: .touchUpInside)

        let note = UILabel()
        note.text = "令牌保存在系统钥匙串；地址只保存非密文。"
        note.font = .systemFont(ofSize: 12)
        note.textColor = Theme.inkSoft
        note.numberOfLines = 0

        statusLabel.font = .systemFont(ofSize: 13)
        statusLabel.textColor = Theme.cinnabar
        statusLabel.numberOfLines = 0
        statusLabel.isHidden = true

        [title, intro, urlLabel, urlField, tokenLabel, tokenField,
         connect, note, statusLabel].forEach(stack.addArrangedSubview)
        stack.setCustomSpacing(20, after: intro)
        stack.setCustomSpacing(6, after: urlLabel)
        stack.setCustomSpacing(16, after: urlField)
        stack.setCustomSpacing(6, after: tokenLabel)
        stack.setCustomSpacing(20, after: tokenField)
        stack.setCustomSpacing(16, after: connect)

        let tap = UITapGestureRecognizer(target: self, action: #selector(dismissKeyboard))
        tap.cancelsTouchesInView = false
        view.addGestureRecognizer(tap)

        let guide = view.safeAreaLayoutGuide
        NSLayoutConstraint.activate([
            scrollView.topAnchor.constraint(equalTo: guide.topAnchor),
            scrollView.leadingAnchor.constraint(equalTo: view.leadingAnchor),
            scrollView.trailingAnchor.constraint(equalTo: view.trailingAnchor),
            scrollView.bottomAnchor.constraint(equalTo: view.bottomAnchor),

            stack.topAnchor.constraint(equalTo: scrollView.contentLayoutGuide.topAnchor, constant: 24),
            stack.leadingAnchor.constraint(equalTo: scrollView.frameLayoutGuide.leadingAnchor, constant: 20),
            stack.trailingAnchor.constraint(equalTo: scrollView.frameLayoutGuide.trailingAnchor, constant: -20),
            stack.bottomAnchor.constraint(equalTo: scrollView.contentLayoutGuide.bottomAnchor, constant: -24),
        ])
    }

    private func configureField(_ field: UITextField, placeholder: String) {
        field.placeholder = placeholder
        field.borderStyle = .roundedRect
        field.backgroundColor = .white
        field.textColor = Theme.ink
        field.font = .systemFont(ofSize: 15)
        field.autocorrectionType = .no
        field.autocapitalizationType = .none
        field.spellCheckingType = .no
        field.clearButtonMode = .whileEditing
        field.translatesAutoresizingMaskIntoConstraints = false
        field.heightAnchor.constraint(greaterThanOrEqualToConstant: 44).isActive = true
    }

    private func applyInitialValues() {
        urlField.text = initialURL
        if let saved = (try? store.load()) ?? nil, !saved.isEmpty {
            tokenField.placeholder = "已保存（留空沿用）"
        }
        if let initialStatus, !initialStatus.isEmpty {
            showStatus(initialStatus)
        }
    }

    private func observeKeyboard() {
        let center = NotificationCenter.default
        let willChange = center.addObserver(
            forName: UIResponder.keyboardWillChangeFrameNotification,
            object: nil,
            queue: .main
        ) { [weak self] note in
            self?.adjustForKeyboard(note)
        }
        let willHide = center.addObserver(
            forName: UIResponder.keyboardWillHideNotification,
            object: nil,
            queue: .main
        ) { [weak self] _ in
            self?.scrollView.contentInset.bottom = 0
            self?.scrollView.verticalScrollIndicatorInsets.bottom = 0
        }
        keyboardObservers = [willChange, willHide]
    }

    private func adjustForKeyboard(_ note: Notification) {
        guard let frame = note.userInfo?[UIResponder.keyboardFrameEndUserInfoKey] as? CGRect else {
            return
        }
        let converted = view.convert(frame, from: nil)
        let overlap = max(0, view.bounds.maxY - converted.minY)
        scrollView.contentInset.bottom = overlap
        scrollView.verticalScrollIndicatorInsets.bottom = overlap
    }

    @objc private func dismissKeyboard() {
        view.endEditing(true)
    }

    @objc private func connectTapped() {
        view.endEditing(true)
        let saved = (try? store.load()) ?? nil
        let result = ConnectionForm.resolve(
            rawURL: urlField.text ?? "",
            rawToken: tokenField.text ?? "",
            savedToken: saved
        )
        switch result {
        case .failure(.invalidURL):
            showStatus("地址无效（需 http/https 主机）")
        case .failure(.missingToken):
            showStatus("令牌不能为空")
        case .success(let value):
            do {
                try store.save(value.token)
            } catch let error as TokenStoreError {
                if case .status(let code) = error {
                    showStatus("安全存储不可用（\(code)）")
                } else {
                    showStatus("安全存储不可用")
                }
                return
            } catch {
                showStatus("安全存储不可用")
                return
            }
            connectionStore.saveURL(value.connection.baseURL)
            let web = WebViewController(
                connection: value.connection,
                token: value.token,
                store: store,
                connectionStore: connectionStore
            )
            navigationController?.setViewControllers([web], animated: true)
        }
    }

    private func showStatus(_ text: String) {
        statusLabel.text = text
        statusLabel.isHidden = text.isEmpty
    }

    func textFieldShouldReturn(_ textField: UITextField) -> Bool {
        if textField === urlField {
            tokenField.becomeFirstResponder()
        } else {
            connectTapped()
        }
        return true
    }
}
