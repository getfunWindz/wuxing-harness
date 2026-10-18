import UIKit

/// 纸墨主题（与 Web 壳 `theme/ink.css` 对齐）。
enum Theme {
    static let paper = UIColor(red: 244.0 / 255.0, green: 241.0 / 255.0, blue: 234.0 / 255.0, alpha: 1)
    static let paperDeep = UIColor(red: 236.0 / 255.0, green: 231.0 / 255.0, blue: 220.0 / 255.0, alpha: 1)
    static let ink = UIColor(red: 35.0 / 255.0, green: 33.0 / 255.0, blue: 30.0 / 255.0, alpha: 1)
    static let inkSoft = UIColor(red: 90.0 / 255.0, green: 84.0 / 255.0, blue: 76.0 / 255.0, alpha: 1)
    static let cinnabar = UIColor(red: 165.0 / 255.0, green: 63.0 / 255.0, blue: 51.0 / 255.0, alpha: 1)
    static let jade = UIColor(red: 31.0 / 255.0, green: 79.0 / 255.0, blue: 69.0 / 255.0, alpha: 1)
    static let line = UIColor(red: 35.0 / 255.0, green: 33.0 / 255.0, blue: 30.0 / 255.0, alpha: 0.14)

    static func navigationBarAppearance() -> UINavigationBarAppearance {
        let appearance = UINavigationBarAppearance()
        appearance.configureWithOpaqueBackground()
        appearance.backgroundColor = paper
        appearance.shadowColor = line
        appearance.titleTextAttributes = [.foregroundColor: ink]
        return appearance
    }

    static func primaryButton(title: String) -> UIButton {
        let button = UIButton(type: .system)
        button.setTitle(title, for: .normal)
        button.setTitleColor(.white, for: .normal)
        button.titleLabel?.font = .systemFont(ofSize: 16, weight: .semibold)
        button.backgroundColor = cinnabar
        button.layer.cornerRadius = 8
        button.contentEdgeInsets = UIEdgeInsets(top: 12, left: 16, bottom: 12, right: 16)
        button.translatesAutoresizingMaskIntoConstraints = false
        button.heightAnchor.constraint(greaterThanOrEqualToConstant: 48).isActive = true
        return button
    }
}
