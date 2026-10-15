import AppKit
import SwiftUI
import Darwin

@MainActor
final class ChatAppDelegate: NSObject, NSApplicationDelegate, NSWindowDelegate {
    private let controller: ChatController
    private var window: NSWindow?
    private var expandedSize = NSSize(width: 390, height: 590)
    private var wasCollapsed = false
    private var wasShowingTasks = false
    private var approvalWindow: ApprovalWindow?
    private var menuBar: MenuBarControl?
    private var panelDragging: PanelDragGesture?
    private var shortcut: GlobalShortcut?
    private var waitingForMenu = false

    init(command: [String]) throws {
        guard let request = ProcessInfo.processInfo.environment["DORO_CHAT_REQUEST"] else {
            throw ChatReadError.failed("작업창 연결 경로가 없도로.")
        }
        let path = URL(fileURLWithPath: request).deletingLastPathComponent().appendingPathComponent("stack-history.json")
        let history = StackHistoryStore(path: path)
        controller = ChatController(command: command, history: try history.load(), saveHistory: history.save)
    }

    func applicationDidFinishLaunching(_ notification: Notification) {
        installMenu()
        menuBar = MenuBarControl(onToggle: { [weak self] in self?.togglePanel() },
            onOpen: { [weak self] in self?.openTasks() }, onHide: { [weak self] in self?.controller.hidePanel() },
            canQuit: { [weak self] in self?.controller.canQuit ?? false },
            onQuit: { [weak self] in self?.controller.requestStop() })
        menuBar?.onReady = { [weak self] in
            guard let self, self.waitingForMenu else { return }
            self.show(self.controller.display)
        }
        let window = ConversationPanel(contentRect: NSRect(x: 0, y: 0, width: 390, height: 590),
                              styleMask: [.borderless, .resizable, .nonactivatingPanel],
                              backing: .buffered, defer: false)
        window.title = "도로 펫 협업"
        window.backgroundColor = NSColor.black.withAlphaComponent(0.01)
        window.isOpaque = false
        window.hasShadow = false
        window.hidesOnDeactivate = false
        window.isMovableByWindowBackground = false
        window.minSize = NSSize(width: 320, height: 400)
        let host = NSHostingView(rootView: ChatView(controller: controller))
        host.sizingOptions = []
        window.contentView = host
        panelDragging = PanelDragGesture(window: window, view: host)
        window.level = .floating
        window.collectionBehavior = [.fullScreenAuxiliary, .canJoinAllSpaces]
        window.isReleasedWhenClosed = false
        window.delegate = self
        if let screen = NSScreen.main {
            let area = screen.visibleFrame
            window.setFrameOrigin(NSPoint(x: area.maxX - 410, y: max(area.minY, area.midY - 295)))
        }
        self.window = window
        approvalWindow = ApprovalWindow(controller: controller)
        controller.onApprovalChange = { [weak self] in
            guard let self else { return }
            self.approvalWindow?.update(anchor: self.window)
            self.menuBar?.update(approvals: self.controller.approvalCount)
        }
        controller.onApprovalOpen = { [weak self] in self?.approvalWindow?.focusCurrent() }
        controller.onCollapse = { [weak self] collapsed in self?.resize(collapsed: collapsed) }
        controller.onStackLayout = { [weak self] in
            guard let self else { return }
            self.resize(collapsed: self.controller.collapsed)
        }
        controller.onDisplay = { [weak self] display in self?.show(display) }
        controller.onStop = { NSApp.terminate(nil) }
        do { shortcut = try GlobalShortcut { [weak self] in self?.openTasks() } }
        catch { controller.shortcutError = error.localizedDescription }
        NotificationCenter.default.addObserver(self, selector: #selector(screenLayoutChanged),
            name: NSApplication.didChangeScreenParametersNotification, object: nil)
        controller.start()
    }

    private func installMenu() {
        let menu = NSMenu()
        let applicationItem = NSMenuItem()
        let applicationMenu = NSMenu()
        let quit = applicationMenu.addItem(withTitle: "공식 도로로 돌아가기 / 종료", action: #selector(returnOrQuit), keyEquivalent: "q")
        quit.target = self
        applicationItem.submenu = applicationMenu
        menu.addItem(applicationItem)
        let editItem = NSMenuItem(title: "편집", action: nil, keyEquivalent: "")
        let edit = NSMenu(title: "편집")
        for (title, action, key) in [("잘라내기", "cut:", "x"), ("복사", "copy:", "c"),
                                     ("붙여넣기", "paste:", "v"), ("전체 선택", "selectAll:", "a")] {
            edit.addItem(withTitle: title, action: Selector(action), keyEquivalent: key)
        }
        editItem.submenu = edit
        menu.addItem(editItem)
        NSApp.mainMenu = menu
    }

    private func show(_ display: ViewerDisplay) {
        guard let window else { return }
        approvalWindow?.update(anchor: window)
        if display == .hidden || display == .stop { waitingForMenu = false; window.orderOut(nil); return }
        if display == .panel, !placeAtMenuBar() {
            if waitingForMenu { return }
            waitingForMenu = true
            DispatchQueue.main.asyncAfter(deadline: .now() + .milliseconds(750)) { [weak self] in
                guard let self, self.waitingForMenu, let window = self.window else { return }
                _ = self.placeAtMenuBar()
                self.waitingForMenu = false
                window.makeKeyAndOrderFront(nil)
                NSApp.activate(ignoringOtherApps: true)
            }
            return
        }
        waitingForMenu = false
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
    }

    private func togglePanel() {
        if controller.display == .hidden { openTasks() }
        else { controller.hidePanel() }
    }

    @discardableResult private func placeAtMenuBar() -> Bool {
        guard let window, let menuBar, controller.display == .panel else { return false }
        do { try menuBar.place(window); controller.placementError = ""; return true }
        catch { controller.placementError = error.localizedDescription; return false }
    }

    @objc private func openTasks() { controller.showTasks(); placeAtMenuBar() }
    @objc private func screenLayoutChanged() { placeAtMenuBar() }

    @objc private func returnOrQuit() {
        if controller.display == .integrated { controller.requestOfficialPet() }
        else { controller.requestStop() }
    }

    private func resize(collapsed: Bool) {
        guard let window else { return }
        let previous = window.frame
        let visible = window.screen?.visibleFrame ?? previous
        let changedCollapse = collapsed != wasCollapsed
        let tasks = !collapsed && controller.showingTasks
        let anchorTop = controller.display == .panel || (tasks && wasShowingTasks && !wasCollapsed)
        if !wasCollapsed && !wasShowingTasks { expandedSize = previous.size }
        wasCollapsed = collapsed
        wasShowingTasks = controller.showingTasks
        let count = controller.pinnedContexts.count
        let compactHeight = controller.display == .integrated ? 95 : 46
        let compactWidth = controller.display == .integrated ? (count == 0 ? 94 : 258) : 200
        window.minSize = NSSize(width: collapsed ? CGFloat(compactWidth) : 320,
                                height: collapsed ? CGFloat(compactHeight) : tasks ? 200 : 400)
        let height = min(collapsed ? CGFloat(compactHeight) : tasks ? CGFloat(controller.taskPanelHeight) : expandedSize.height, visible.height)
        let width = min(collapsed ? CGFloat(compactWidth) : tasks ? 390 : expandedSize.width, visible.width)
        let point = NSPoint(x: previous.maxX - width, y: anchorTop ? previous.maxY - height : previous.minY)
        let origin = clampedPanelOrigin(point, size: NSSize(width: width, height: height), visible: visible)
        let target = NSRect(origin: origin, size: NSSize(width: width, height: height))
        if target != previous { window.setFrame(target, display: true, animate: changedCollapse && controller.display == .integrated) }
    }

    func windowShouldClose(_ sender: NSWindow) -> Bool {
        controller.requestStop()
        return false
    }

    func applicationWillTerminate(_ notification: Notification) {
        shortcut?.stop()
        menuBar?.stop()
        NotificationCenter.default.removeObserver(self)
        controller.stop()
    }

}

let command = Array(CommandLine.arguments.dropFirst())
guard command.count >= 3, command.last == "--json", command[command.count - 3] == "chat",
      let rawDescriptor = ProcessInfo.processInfo.environment["DORO_CHAT_LOCK_FD"],
      let descriptor = Int32(rawDescriptor), fcntl(descriptor, F_GETFD) >= 0 else {
    fputs("Launch this local viewer with doro chat <session-id>.\n", stderr)
    exit(1)
}
_ = fcntl(descriptor, F_SETFD, FD_CLOEXEC)
let application = NSApplication.shared
application.setActivationPolicy(.accessory)
let delegate: ChatAppDelegate
do { delegate = try ChatAppDelegate(command: command) }
catch { fputs("Unable to open task window: \(error.localizedDescription)\n", stderr); exit(1) }
application.delegate = delegate
application.run()
