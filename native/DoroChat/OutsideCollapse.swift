import AppKit

@MainActor
final class OutsideCollapse: NSObject {
    private weak var controller: ChatController?
    private var mouseMonitor: Any?
    private let isMenuInteraction: (NSPoint) -> Bool
    private let isMouseClick: () -> Bool

    init(controller: ChatController, isMenuInteraction: @escaping (NSPoint) -> Bool, isMouseClick: @escaping () -> Bool) throws {
        self.controller = controller
        self.isMenuInteraction = isMenuInteraction
        self.isMouseClick = isMouseClick
        super.init()
        NotificationCenter.default.addObserver(self, selector: #selector(applicationDeactivated),
            name: NSApplication.didResignActiveNotification, object: NSApp)
        // Global monitors exclude this app's settings and approval windows.
        mouseMonitor = NSEvent.addGlobalMonitorForEvents(matching: [.leftMouseDown, .rightMouseDown]) { [weak self] event in
            let point = NSEvent.mouseLocation
            let timestamp = event.timestamp
            Task { @MainActor [weak self] in self?.collapse(at: point, mouseClick: true, timestamp: timestamp) }
        }
        guard mouseMonitor != nil else { throw ChatReadError.failed("바깥 클릭 자동 접기를 등록하지 못했도로.") }
    }

    @objc private func applicationDeactivated() {
        collapse(at: NSEvent.mouseLocation, mouseClick: isMouseClick(), timestamp: ProcessInfo.processInfo.systemUptime)
    }

    private func collapse(at point: NSPoint, mouseClick: Bool, timestamp: TimeInterval) {
        guard mouseMonitor != nil, let controller else { return }
        controller.handleOutsideInteraction(overMenuIcon: mouseClick && isMenuInteraction(point), timestamp: timestamp)
    }

    func stop() {
        NotificationCenter.default.removeObserver(self)
        if let mouseMonitor { NSEvent.removeMonitor(mouseMonitor) }
        mouseMonitor = nil
    }
}
