import AppKit

@MainActor
final class MenuBarControl: NSObject, NSMenuItemValidation {
    private let item = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
    private let onToggle: () -> Void
    private let onOpen: () -> Void
    private let onHide: () -> Void
    private let onQuit: () -> Void
    private let canQuit: () -> Bool
    private weak var observedWindow: NSWindow?
    private var placement = MenuPanelPlacement()
    var onAnchorChange: (() -> Void)?

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
        if let button = item.button {
            button.postsFrameChangedNotifications = true
            NotificationCenter.default.addObserver(self, selector: #selector(anchorChanged),
                name: NSView.frameDidChangeNotification, object: button)
        }
    }

    private var buttonFrame: NSRect? {
        guard let button = item.button, let window = button.window else { return nil }
        return window.convertToScreen(button.convert(button.bounds, to: nil))
    }

    func contains(screenPoint: NSPoint) -> Bool { buttonFrame?.contains(screenPoint) == true }

    private func anchor() throws -> (NSRect, NSRect, UInt32) {
        guard let button = item.button, let barWindow = button.window, let screen = barWindow.screen,
              let frame = buttonFrame else {
            throw ChatReadError.failed("메뉴 막대 위치를 확인하지 못했도로.")
        }
        guard barWindow.frame.height > 0 else { throw ChatReadError.failed("메뉴 아이콘을 배치하는 중이도로.") }
        guard let number = screen.deviceDescription[NSDeviceDescriptionKey("NSScreenNumber")] as? NSNumber else {
            throw ChatReadError.failed("메뉴 막대가 있는 화면을 확인하지 못했도로.")
        }
        observeWindow(barWindow)
        return (frame, screen.visibleFrame, number.uint32Value)
    }

    private func observeWindow(_ window: NSWindow) {
        guard observedWindow !== window else { return }
        let center = NotificationCenter.default
        if let old = observedWindow {
            center.removeObserver(self, name: NSWindow.didMoveNotification, object: old)
            center.removeObserver(self, name: NSWindow.didResizeNotification, object: old)
            center.removeObserver(self, name: NSWindow.didChangeScreenNotification, object: old)
        }
        observedWindow = window
        center.addObserver(self, selector: #selector(anchorChanged), name: NSWindow.didMoveNotification, object: window)
        center.addObserver(self, selector: #selector(anchorChanged), name: NSWindow.didResizeNotification, object: window)
        center.addObserver(self, selector: #selector(anchorChanged), name: NSWindow.didChangeScreenNotification, object: window)
    }

    func place(_ window: NSWindow, size: NSSize? = nil, animated: Bool = false, resetOffset: Bool = false) throws {
        let (anchor, visible, display) = try anchor()
        let target = placement.frame(anchor: anchor, size: size ?? window.frame.size, visible: visible,
                                     display: display, reset: resetOffset)
        InterfaceMotion.frame(target, for: window, animated: animated)
    }

    func rememberOffset(_ window: NSWindow) throws {
        let (anchor, _, display) = try anchor()
        placement.remember(origin: window.frame.origin, anchor: anchor, size: window.frame.size, display: display)
    }

    func stop() { NotificationCenter.default.removeObserver(self); NSStatusBar.system.removeStatusItem(item) }

    func update(approvals: Int) {
        let title = approvals > 0 ? " \(approvals)" : ""
        if item.button?.title != title { item.button?.title = title }
    }

    func validateMenuItem(_ menuItem: NSMenuItem) -> Bool { menuItem.action != #selector(quit) || canQuit() }

    @objc private func anchorChanged() { onAnchorChange?() }

    @objc private func toggle() {
        guard let event = NSApp.currentEvent,
              event.type == .rightMouseUp || event.modifierFlags.contains(.control), let button = item.button else {
            onToggle(); return
        }
        let menu = NSMenu()
        for (title, action) in [("대화", #selector(open)), ("창 숨기기", #selector(hide)), ("종료", #selector(quit))] {
            let entry = menu.addItem(withTitle: title, action: action, keyEquivalent: "")
            entry.target = self
        }
        NSMenu.popUpContextMenu(menu, with: event, for: button)
    }

    @objc private func open() { onOpen() }
    @objc private func hide() { onHide() }
    @objc private func quit() { onQuit() }
}
