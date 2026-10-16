import AppKit

@MainActor
final class OutsideCollapse: NSObject {
    private weak var controller: ChatController?
    private var mouseMonitor: Any?

    init(controller: ChatController) throws {
        self.controller = controller
        super.init()
        NotificationCenter.default.addObserver(self, selector: #selector(applicationDeactivated),
            name: NSApplication.didResignActiveNotification, object: NSApp)
        // Global monitors exclude this app's settings and approval windows.
        mouseMonitor = NSEvent.addGlobalMonitorForEvents(matching: [.leftMouseDown, .rightMouseDown]) { [weak self] _ in
            Task { @MainActor [weak self] in self?.applicationDeactivated() }
        }
        guard mouseMonitor != nil else { throw ChatReadError.failed("바깥 클릭 자동 접기를 등록하지 못했도로.") }
    }

    @objc private func applicationDeactivated() {
        guard mouseMonitor != nil, let controller, controller.display == .panel, !controller.collapsed else { return }
        controller.collapseToDock()
    }

    func stop() {
        NotificationCenter.default.removeObserver(self)
        if let mouseMonitor { NSEvent.removeMonitor(mouseMonitor) }
        mouseMonitor = nil
    }
}
