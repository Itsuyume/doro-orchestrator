import AppKit

func clampedPanelOrigin(_ origin: NSPoint, size: NSSize, visible: NSRect) -> NSPoint {
    NSPoint(x: min(max(origin.x, visible.minX), max(visible.minX, visible.maxX - size.width)),
            y: min(max(origin.y, visible.minY), max(visible.minY, visible.maxY - size.height)))
}

@MainActor
final class PanelDragGesture: NSObject, NSGestureRecognizerDelegate {
    private weak var window: ConversationPanel?
    private var drag = WindowDragState()

    init(window: ConversationPanel, view: NSView) {
        self.window = window
        super.init()
        let pan = NSPanGestureRecognizer(target: self, action: #selector(movePanel))
        pan.buttonMask = 1
        pan.delaysPrimaryMouseButtonEvents = true
        pan.delegate = self
        view.addGestureRecognizer(pan)
    }

    func gestureRecognizer(_ gestureRecognizer: NSGestureRecognizer, shouldAttemptToRecognizeWith event: NSEvent) -> Bool {
        guard let window, let content = window.contentView else { return false }
        let location = content.superview?.convert(event.locationInWindow, from: nil) ?? event.locationInWindow
        var target = content.hitTest(location)
        while let view = target {
            if view is WindowDragView || view is NSScroller || view is NSTableView || view is NSCollectionView { return false }
            if let editor = view as? NSTextView, editor.isEditable { return false }
            target = view.superview
        }
        if event.type == .leftMouseDown {
            drag.begin(at: window.convertPoint(toScreen: event.locationInWindow), origin: window.frame.origin)
        }
        return true
    }

    @objc private func movePanel(_ gesture: NSPanGestureRecognizer) {
        guard let window else { return }
        let point = window.convertPoint(toScreen: gesture.location(in: nil))
        if gesture.state == .began || gesture.state == .changed,
           let origin = drag.move(to: point),
           let area = (NSScreen.screens.first { $0.frame.contains(point) } ?? window.screen)?.visibleFrame {
            window.moveFromUser(to: clampedPanelOrigin(origin, size: window.frame.size, visible: area))
        }
        if gesture.state == .ended || gesture.state == .cancelled || gesture.state == .failed { _ = drag.finish() }
    }
}
