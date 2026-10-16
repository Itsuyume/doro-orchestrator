import AppKit
import SwiftUI

struct WindowDragState {
    private var start: NSPoint?
    private var origin = NSPoint.zero
    private(set) var moved = false

    mutating func begin(at point: NSPoint, origin: NSPoint) {
        start = point
        self.origin = origin
        moved = false
    }

    mutating func move(to point: NSPoint) -> NSPoint? {
        guard let start else { return nil }
        let dx = point.x - start.x, dy = point.y - start.y
        guard moved || hypot(dx, dy) >= 4 else { return nil }
        moved = true
        return NSPoint(x: origin.x + dx, y: origin.y + dy)
    }

    mutating func finish() -> Bool {
        let clicked = start != nil && !moved
        start = nil
        return clicked
    }
}

@MainActor
final class ConversationPanel: NSPanel {
    var onUserMove: (() -> Void)?
    override var canBecomeKey: Bool { true }
    override var canBecomeMain: Bool { true }

    func moveFromUser(to origin: NSPoint) {
        setFrameOrigin(origin)
        onUserMove?()
    }
}

@MainActor
final class WindowDragView: NSView {
    var onTap: (() -> Void)?
    private var drag = WindowDragState()
    override var mouseDownCanMoveWindow: Bool { false }
    override func acceptsFirstMouse(for event: NSEvent?) -> Bool { true }
    override func draw(_ dirtyRect: NSRect) {
        NSColor.black.withAlphaComponent(0.01).setFill()
        dirtyRect.fill()
    }

    override func mouseDown(with event: NSEvent) {
        guard let window = window as? ConversationPanel else { return }
        drag.begin(at: window.convertPoint(toScreen: event.locationInWindow), origin: window.frame.origin)
    }

    override func mouseDragged(with event: NSEvent) {
        guard let window = window as? ConversationPanel else { return }
        let point = window.convertPoint(toScreen: event.locationInWindow)
        guard let origin = drag.move(to: point) else { return }
        let area = (NSScreen.screens.first { $0.frame.contains(point) } ?? window.screen)?.visibleFrame
        if let area { window.moveFromUser(to: clampedPanelOrigin(origin, size: window.frame.size, visible: area)) }
    }

    override func mouseUp(with event: NSEvent) {
        if drag.finish(), event.clickCount <= 1 { onTap?() }
    }

    override func accessibilityPerformPress() -> Bool {
        guard let onTap else { return false }
        onTap(); return true
    }
}

struct WindowDragHandle: NSViewRepresentable {
    var label = "대화창 이동"
    var onTap: (() -> Void)?

    func makeNSView(context: Context) -> WindowDragView { WindowDragView(frame: .zero) }

    func updateNSView(_ view: WindowDragView, context: Context) {
        view.onTap = onTap
        view.toolTip = nil
        view.setAccessibilityElement(true)
        view.setAccessibilityRole(onTap == nil ? .group : .button)
        view.setAccessibilityLabel(label)
    }
}
