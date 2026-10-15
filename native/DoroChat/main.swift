import AppKit
import SwiftUI
import Darwin

@MainActor
final class ChatAppDelegate: NSObject, NSApplicationDelegate, NSWindowDelegate {
    private let controller: ChatController
    private var window: NSWindow?
    private var expandedSize = NSSize(width: 390, height: 590)
    private var wasCollapsed = false
    private var approvalWindow: ApprovalWindow?
    private var statusItem: NSStatusItem?

    init(command: [String]) {
        controller = ChatController(command: command)
    }

    func applicationDidFinishLaunching(_ notification: Notification) {
        installMenu()
        installStatusMenu()
        let window = ConversationPanel(contentRect: NSRect(x: 0, y: 0, width: 390, height: 590),
                              styleMask: [.borderless, .resizable, .nonactivatingPanel],
                              backing: .buffered, defer: false)
        window.title = "도로 펫 협업"
        window.backgroundColor = .clear
        window.isOpaque = false
        window.hasShadow = false
        window.hidesOnDeactivate = false
        window.isMovableByWindowBackground = false
        window.minSize = NSSize(width: 320, height: 400)
        window.contentView = NSHostingView(rootView: ChatView(controller: controller))
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
        controller.onApprovalChange = { [weak self] in self?.approvalWindow?.update(anchor: self?.window) }
        controller.onApprovalOpen = { [weak self] in self?.approvalWindow?.focusCurrent() }
        controller.onCollapse = { [weak self] collapsed in self?.resize(collapsed: collapsed) }
        controller.onStackLayout = { [weak self] in
            guard let self else { return }
            self.resize(collapsed: self.controller.collapsed)
        }
        controller.onDisplay = { [weak self] display in self?.show(display) }
        controller.onStop = { NSApp.terminate(nil) }
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
        if display == .hidden || display == .stop { window.orderOut(nil); return }
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
    }

    private func installStatusMenu() {
        let item = NSStatusBar.system.statusItem(withLength: NSStatusItem.squareLength)
        item.button?.image = NSImage(systemSymbolName: "bubble.left", accessibilityDescription: "도로 대화")
        item.button?.toolTip = "도로 대화"
        let menu = NSMenu()
        for (title, action) in [("대화 열기", #selector(openChat)), ("작업 목록", #selector(openTasks))] {
            let entry = menu.addItem(withTitle: title, action: action, keyEquivalent: "")
            entry.target = self
        }
        menu.addItem(.separator())
        let quit = menu.addItem(withTitle: "종료", action: #selector(returnOrQuit), keyEquivalent: "")
        quit.target = self
        item.menu = menu
        statusItem = item
    }

    @objc private func openChat() { controller.openContext(controller.selectedSession) }
    @objc private func openTasks() { controller.showTasks() }

    @objc private func returnOrQuit() {
        if controller.display == .integrated { controller.requestOfficialPet() }
        else { NSApp.terminate(nil) }
    }

    private func resize(collapsed: Bool) {
        guard let window else { return }
        let previous = window.frame
        let visible = window.screen?.visibleFrame ?? previous
        if !wasCollapsed { expandedSize = previous.size }
        wasCollapsed = collapsed
        let count = controller.pinnedContexts.count
        let trayHeight = min(count, 3) * 31 + (count > 3 ? 18 : 0)
        let compactHeight = controller.display == .integrated ? max(95, trayHeight + 12) : trayHeight + 45
        let compactWidth = controller.display == .integrated ? (count == 0 ? 94 : 258) : 250
        window.minSize = NSSize(width: collapsed ? CGFloat(compactWidth) : 320,
                                height: collapsed ? CGFloat(compactHeight) : 400)
        let height = min(collapsed ? CGFloat(compactHeight) : expandedSize.height, visible.height)
        let width = min(collapsed ? CGFloat(compactWidth) : expandedSize.width, visible.width)
        let x = max(visible.minX, min(previous.maxX - width, visible.maxX - width))
        let y = max(visible.minY, min(previous.minY, visible.maxY - height))
        window.setFrame(NSRect(x: x, y: y, width: width, height: height), display: true, animate: true)
    }

    func windowShouldClose(_ sender: NSWindow) -> Bool {
        controller.closeStack(controller.selectedSession)
        return false
    }

    func applicationWillTerminate(_ notification: Notification) {
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
let delegate = ChatAppDelegate(command: command)
application.delegate = delegate
application.run()
