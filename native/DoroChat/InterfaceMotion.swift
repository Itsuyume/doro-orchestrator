import AppKit
import QuartzCore
import SwiftUI

enum InterfaceMotion {
    static let duration = 0.22

    static func animation(reduced: Bool) -> Animation? {
        reduced ? nil : .smooth(duration: duration, extraBounce: 0)
    }

    @MainActor static func frame(_ frame: NSRect, for window: NSWindow, animated: Bool) {
        guard window.frame != frame else { return }
        guard animated, window.isVisible, !NSWorkspace.shared.accessibilityDisplayShouldReduceMotion else {
            window.setFrame(frame, display: true)
            return
        }
        NSAnimationContext.runAnimationGroup { context in
            context.duration = duration
            context.timingFunction = CAMediaTimingFunction(controlPoints: 0.2, 0.8, 0.2, 1)
            window.animator().setFrame(frame, display: true)
        }
    }
}
