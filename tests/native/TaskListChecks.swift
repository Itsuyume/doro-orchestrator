import AppKit

@main
struct TaskListChecks {
    @MainActor static func main() throws {
        let two = TaskListLayout.contentHeight(open: 2, history: 3,
            historyExpanded: false, selecting: false, undo: true)
        let one = TaskListLayout.contentHeight(open: 1, history: 3,
            historyExpanded: false, selecting: false, undo: true)
        precondition(two - one == 56, "Rows alone determine the open-list height")
        let history = TaskListLayout.contentHeight(open: 1, history: 3,
            historyExpanded: true, selecting: true, undo: true)
        precondition(history - one == 2 * 56 + 28, "History shares the three-row viewport; selection stays usable")
        let empty = TaskListLayout.contentHeight(open: 0, history: 0,
            historyExpanded: false, selecting: false, undo: false)
        precondition(empty == 72 && one == 128, "No redundant open-conversation heading is reserved")
        precondition(taskListHeight(content: two) > taskListHeight(content: one))
        precondition(taskListHeight(content: 10000) == 620)
        checkThreeRowViewport()
        let controller = ChatController(command: ["/usr/bin/false", "chat", "A", "--json"])
        controller.display = .panel
        controller.showingTasks = true
        controller.stacks.open("A")
        controller.inputText = "Keep draft"
        controller.scrollTarget = "earlier"
        controller.collapseToDock()
        precondition(controller.collapsed && controller.display == .panel && controller.showingTasks,
                     "Collapse leaves one visible dock, without hiding the app or changing the active pane")
        controller.toggleChat()
        precondition(!controller.collapsed && controller.showingTasks && controller.inputText == "Keep draft"
                     && controller.scrollTarget == "earlier", "Dock reopening preserves list, draft and reading position")
        try checkListActions()
        checkWindowMotion()
        checkMouseSwipe()
        try checkOutsideCollapse()
        print("Task list checks passed: fold height, independent history, close stays open, protected records, undo, hidden motion")
    }

    static func checkThreeRowViewport() {
        let three = TaskListLayout.rowViewportHeight(open: 3, history: 0, historyExpanded: false)
        precondition(three == 3 * TaskListLayout.rowHeight + 2 * TaskListLayout.verticalInset)
        for count in [0, 1, 2, 3, 4, 50, 1000] {
            let height = TaskListLayout.rowViewportHeight(open: count, history: 0, historyExpanded: false)
            precondition(height <= three, "Four or more tasks cannot enlarge the dock list")
        }
        let mixed = TaskListLayout.rowViewportHeight(open: 2, history: 50, historyExpanded: true)
        precondition(mixed == three, "Open and past conversations share one three-row viewport")
        let controls = TaskListLayout.contentHeight(open: 50, history: 50,
            historyExpanded: true, selecting: true, undo: true)
        precondition(controls == three + 3 * TaskListLayout.controlHeight,
                     "History, selection and undo controls cannot disappear inside the scrolling rows")
    }

    static func checkMouseSwipe() {
        var swipe = RowSwipeState()
        swipe.update(x: -300, y: -400, width: 360)
        precondition(swipe.offset == 0 && !swipe.finish(width: 360), "Vertical movement never dismisses a row")
        swipe.update(x: -8, y: 0, width: 360)
        precondition(swipe.offset == 0 && !swipe.finish(width: 360), "Click jitter cannot become a flick")
        swipe.update(x: -45, y: 0, width: 360)
        precondition(!swipe.finish(width: 360) && swipe.offset == -72, "A short drag reveals the action")
        swipe.update(x: 60, y: 0, width: 360)
        precondition(!swipe.finish(width: 360) && swipe.offset == 0, "Reverse dragging closes the action")
        swipe.update(x: -90, y: 0, width: 360)
        swipe.update(x: -5, y: 0, width: 360)
        precondition(!swipe.finish(width: 360) && swipe.offset == 0, "A reversal near the start cannot delete")
        swipe.update(x: -30, y: 0, width: 360)
        precondition(!swipe.finish(width: 360) && swipe.offset == -72, "Short mouse drags only reveal, regardless of speed")
        precondition(!swipe.finish(width: 360), "Duplicate mouse-up cannot commit twice")
        swipe.reset()
        swipe.update(x: -300, y: 0, width: 360)
        precondition(swipe.finish(width: 360), "A full drag commits")
        swipe.reset()
        swipe.update(x: -60, y: 0, width: 360)
        swipe.cancel()
        precondition(swipe.offset == 0 && !swipe.dragging, "Cancelled gestures return to their resting position")
        swipe.update(x: -500, y: 0, width: 0)
        precondition(!swipe.finish(width: 0) && swipe.offset == 0)
    }

    @MainActor static func checkListActions() throws {
        let a = UUID().uuidString, b = UUID().uuidString, busy = UUID().uuidString
        let controller = ChatController(command: ["/usr/bin/false", "chat", a, "--json"])
        let contexts = [ChatContext(session_id: a, label: "A", status: "completed", needs_input: false,
                                   event_count: 1, queued_inputs: 0, finished: true),
                        ChatContext(session_id: b, label: "B", status: "waiting", needs_input: true,
                                    event_count: 1, queued_inputs: 0, finished: false),
                        ChatContext(session_id: busy, label: "queued", status: "completed", needs_input: false,
                                    event_count: 1, queued_inputs: 1, finished: true)]
        controller.contexts = contexts
        try controller.synchronizeStacks(contexts)
        precondition(controller.taskPanelHeight == taskListHeight(content: 16 + 2 * 56 + 28),
                     "The first frame uses actual rows before any view appears")
        controller.showingTasks = true
        controller.display = .panel
        controller.inputText = "Unsent draft"
        controller.scrollTarget = "earlier"
        controller.closeStack(a)
        precondition(controller.taskPanelHeight == taskListHeight(content: 16 + 56 + 28),
                     "Closing a row recalculates the next frame without a delayed view measurement")
        precondition(controller.display == .panel && controller.showingTasks && !controller.collapsed)
        precondition(!controller.stacks.contains(a), "The row closes without dismissing the entire list")
        controller.closeStack(b)
        controller.removeHistory([a, b, busy])
        precondition(!controller.stacks.isListed(a) && controller.stacks.isListed(b) && controller.stacks.isListed(busy))
        controller.undoHistoryRemoval()
        precondition(controller.stacks.isListed(a) && !controller.stacks.contains(a))
        precondition(controller.inputText == "Unsent draft" && controller.scrollTarget == "earlier")
        controller.openContext(a)
        precondition(!controller.showingTasks && controller.stacks.contains(a) && controller.display == .panel)
        precondition(controller.inputText == "Unsent draft" && controller.scrollTarget == "earlier")
    }

    @MainActor static func checkWindowMotion() {
        _ = NSApplication.shared
        let window = ConversationPanel(contentRect: NSRect(x: 100, y: 100, width: 390, height: 400),
            styleMask: [.borderless], backing: .buffered, defer: false)
        window.isReleasedWhenClosed = false
        defer { window.close() }
        let dock = NSSize(width: 224, height: 46)
        configurePanelSizing(window, collapsed: true, taskList: false, compact: dock)
        precondition(!window.styleMask.contains(.resizable) && window.minSize == dock && window.maxSize == dock,
                     "The dock cannot leave a larger invisible resize area")
        configurePanelSizing(window, collapsed: false, taskList: true, compact: dock)
        precondition(!window.styleMask.contains(.resizable) && window.minSize.height == 130)
        configurePanelSizing(window, collapsed: false, taskList: false, compact: dock)
        precondition(window.styleMask.contains(.resizable) && window.minSize.height == 400,
                     "Resizing is available only for the full conversation")
        var userMoves = 0
        window.onUserMove = { userMoves += 1 }
        let target = NSRect(x: 110, y: 120, width: 390, height: 240)
        InterfaceMotion.frame(target, for: window, animated: true)
        precondition(window.frame == target && !window.isVisible && userMoves == 0,
                     "Programmatic layout cannot reveal a hidden window or masquerade as a user drag")
        window.moveFromUser(to: NSPoint(x: 130, y: 140))
        precondition(userMoves == 1 && window.frame.origin == NSPoint(x: 130, y: 140))
    }

    @MainActor static func checkOutsideCollapse() throws {
        let controller = ChatController(command: ["/usr/bin/false", "chat", "A", "--json"])
        let focus = try OutsideCollapse(controller: controller)
        defer { focus.stop() }
        controller.display = .panel
        controller.inputText = "Preserve draft"
        controller.scrollTarget = "earlier"
        var collapses = 0
        controller.onCollapse = { _ in collapses += 1 }
        var hides = 0
        controller.onDisplay = { if $0 == .hidden { hides += 1 } }
        NotificationCenter.default.post(name: NSWindow.didResignKeyNotification, object: NSApp)
        precondition(!controller.collapsed, "A settings/approval window becoming key must not fold the conversation")
        NotificationCenter.default.post(name: NSApplication.didResignActiveNotification, object: NSApp)
        precondition(controller.collapsed && controller.display == .hidden && controller.inputText == "Preserve draft"
                     && controller.scrollTarget == "earlier", "Another app hides to the menu bar without ending work or losing input")
        NotificationCenter.default.post(name: NSApplication.didResignActiveNotification, object: NSApp)
        precondition(collapses == 1 && hides == 1, "Repeated outside events cannot trigger repeated hide or resize actions")
        controller.display = .panel
        NotificationCenter.default.post(name: NSApplication.didResignActiveNotification, object: NSApp)
        precondition(controller.display == .hidden && controller.collapsed && hides == 2,
                     "An already-collapsed dock also hides completely on an outside click")
        controller.display = .hidden
        controller.collapsed = false
        NotificationCenter.default.post(name: NSApplication.didResignActiveNotification, object: NSApp)
        precondition(!controller.collapsed && controller.display == .hidden, "Deactivation cannot reveal a hidden panel")
        focus.stop()
        controller.display = .panel
        NotificationCenter.default.post(name: NSApplication.didResignActiveNotification, object: NSApp)
        precondition(!controller.collapsed, "Stopped observers cannot collapse a new panel")
    }
}
