import AppKit
import SwiftUI

@MainActor
final class ApprovalWindow: NSObject, NSWindowDelegate {
    private let controller: ChatController
    private let panel: NSPanel
    private var shown: ApprovalTarget?

    init(controller: ChatController) {
        self.controller = controller
        panel = ConversationPanel(contentRect: NSRect(x: 0, y: 0, width: 360, height: 340),
                                  styleMask: [.borderless, .nonactivatingPanel], backing: .buffered, defer: false)
        super.init()
        panel.title = "도로 · 승인 질문"
        panel.backgroundColor = .clear
        panel.isOpaque = false
        panel.hasShadow = true
        panel.hidesOnDeactivate = false
        panel.isReleasedWhenClosed = false
        panel.level = .floating
        panel.collectionBehavior = [.fullScreenAuxiliary, .canJoinAllSpaces]
        panel.delegate = self
    }

    func update(anchor: NSWindow?) {
        guard let target = controller.approvals.presented,
              controller.display != .hidden, controller.display != .stop else {
            if panel.isVisible { panel.orderOut(nil) }
            shown = nil; return
        }
        guard target != shown else { return }
        shown = target
        panel.contentView = NSHostingView(rootView: ApprovalView(controller: controller, target: target))
        if let anchor, let visible = anchor.screen?.visibleFrame {
            let right = anchor.frame.maxX
            let above = anchor.frame.minY + 96
            panel.setFrameOrigin(NSPoint(x: min(max(visible.minX, right - 360), visible.maxX - 360),
                                         y: min(max(visible.minY, above), visible.maxY - 340)))
        }
        panel.orderFront(nil) // Show once without activating the app or capturing keyboard focus.
    }

    func windowShouldClose(_ sender: NSWindow) -> Bool { controller.approvals.dismiss(); return false }

    func focusCurrent() {
        guard controller.approvals.presented != nil, panel.isVisible else { return }
        panel.makeKeyAndOrderFront(nil)
    }
}
