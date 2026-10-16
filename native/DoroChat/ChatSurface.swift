import AppKit
import SwiftUI

enum ChatSurface {
    static let panel = adaptive(light: NSColor(srgbRed: 0.980, green: 0.969, blue: 0.941, alpha: 1),
                                dark: NSColor(srgbRed: 0.14, green: 0.13, blue: 0.12, alpha: 1))
    static let chrome = adaptive(light: NSColor(srgbRed: 0.937, green: 0.918, blue: 0.878, alpha: 1),
                                 dark: NSColor(srgbRed: 0.20, green: 0.19, blue: 0.18, alpha: 1))
    static let border = adaptive(light: NSColor(srgbRed: 0.67, green: 0.63, blue: 0.55, alpha: 0.6),
                                 dark: NSColor(srgbRed: 0.64, green: 0.60, blue: 0.54, alpha: 0.6))
    static let aiBubble = adaptive(light: .white, dark: NSColor(white: 0.22, alpha: 1))
    static let userBubble = adaptive(light: NSColor(white: 0.94, alpha: 1), dark: NSColor(white: 0.28, alpha: 1))
    static let editor = Color(nsColor: .textBackgroundColor)
    static let action = adaptive(light: NSColor(white: 0.20, alpha: 1), dark: NSColor(white: 0.88, alpha: 1))
    static let actionText = adaptive(light: .white, dark: NSColor(white: 0.10, alpha: 1))

    private static func adaptive(light: NSColor, dark: NSColor) -> Color {
        Color(nsColor: NSColor(name: nil) { appearance in
            appearance.bestMatch(from: [.aqua, .darkAqua]) == .darkAqua ? dark : light
        })
    }
}
