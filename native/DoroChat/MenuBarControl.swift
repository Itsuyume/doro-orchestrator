import AppKit

func menuPanelOrigin(anchor: NSRect, size: NSSize, visible: NSRect) -> NSPoint {
    clampedPanelOrigin(NSPoint(x: anchor.midX - size.width / 2, y: anchor.minY - size.height - 6),
                       size: size, visible: visible)
}

@MainActor
final class MenuBarControl: NSObject, NSMenuItemValidation {
    private let item = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
    private let onToggle: () -> Void
    private let onOpen: () -> Void
    private let onHide: () -> Void
    private let onQuit: () -> Void
    private let canQuit: () -> Bool
    var onReady: (() -> Void)?

    init(onToggle: @escaping () -> Void, onOpen: @escaping () -> Void,
         onHide: @escaping () -> Void, canQuit: @escaping () -> Bool, onQuit: @escaping () -> Void) {
        self.onToggle = onToggle
        self.onOpen = onOpen
        self.onHide = onHide
        self.onQuit = onQuit
        self.canQuit = canQuit
        super.init()
        item.button?.image = NSImage(systemSymbolName: "bubble.left", accessibilityDescription: "도로협업")
        item.button?.toolTip = "도로협업 · ⌃⌥D"
        item.button?.target = self
        item.button?.action = #selector(toggle)
        item.button?.sendAction(on: [.leftMouseUp, .rightMouseUp])
        if let window = item.button?.window {
            NotificationCenter.default.addObserver(self, selector: #selector(anchorReady),
                name: NSWindow.didMoveNotification, object: window)
        }
    }

    func place(_ window: NSWindow) throws {
        guard let button = item.button, let barWindow = button.window, let screen = barWindow.screen else {
            throw ChatReadError.failed("메뉴 막대 위치를 확인하지 못했도로.")
        }
        guard barWindow.frame.height > 0 else { throw ChatReadError.failed("메뉴 아이콘을 배치하는 중이도로.") }
        let anchor = barWindow.convertToScreen(button.convert(button.bounds, to: nil))
        window.setFrameOrigin(menuPanelOrigin(anchor: anchor, size: window.frame.size, visible: screen.visibleFrame))
    }

    func stop() { NotificationCenter.default.removeObserver(self); NSStatusBar.system.removeStatusItem(item) }

    func update(approvals: Int) {
        let title = approvals > 0 ? " \(approvals)" : ""
        if item.button?.title != title { item.button?.title = title }
    }

    func validateMenuItem(_ menuItem: NSMenuItem) -> Bool { menuItem.action != #selector(quit) || canQuit() }

    @objc private func anchorReady() { onReady?() }

    @objc private func toggle() {
        guard let event = NSApp.currentEvent,
              event.type == .rightMouseUp || event.modifierFlags.contains(.control), let button = item.button else {
            onToggle(); return
        }
        let menu = NSMenu()
        for (title, action) in [("작업 목록", #selector(open)), ("창 숨기기", #selector(hide)), ("종료", #selector(quit))] {
            let entry = menu.addItem(withTitle: title, action: action, keyEquivalent: "")
            entry.target = self
        }
        NSMenu.popUpContextMenu(menu, with: event, for: button)
    }

    @objc private func open() { onOpen() }
    @objc private func hide() { onHide() }
    @objc private func quit() { onQuit() }
}
