import AppKit
import QuartzCore
import SwiftUI

enum InterfaceMotion {
    static let duration = 0.22
    static let statusOverflowTolerance = 2.0

    static func animation(reduced: Bool) -> Animation? {
        reduced ? nil : .smooth(duration: duration, extraBounce: 0)
    }

    static func statusOffset(elapsed: TimeInterval, contentWidth: Double, viewportWidth: Double, reduced: Bool) -> Double {
        guard !reduced, viewportWidth > 0, contentWidth > viewportWidth + statusOverflowTolerance, elapsed >= 0 else { return 0 }
        let distance = contentWidth - viewportWidth
        let pause = 1.6
        let speed = 26.0
        let travel = distance / speed
        let phase = elapsed.truncatingRemainder(dividingBy: 2 * (travel + pause))
        if phase <= pause { return 0 }
        if phase < pause + travel { return -(phase - pause) * speed }
        if phase <= 2 * pause + travel { return -distance }
        return min(0, -distance + (phase - 2 * pause - travel) * speed)
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
