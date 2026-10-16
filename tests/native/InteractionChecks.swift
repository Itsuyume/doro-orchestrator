import AppKit

@main
struct InteractionChecks {
    @MainActor static func main() throws {
        var drag = WindowDragState()
        precondition(!drag.finish(), "A mouse-up without a mouse-down must not open a chat")
        precondition(drag.move(to: NSPoint(x: 9, y: 9)) == nil)
        drag.begin(at: NSPoint(x: 100, y: 100), origin: NSPoint(x: 20, y: 30))
        precondition(drag.move(to: NSPoint(x: 102, y: 101)) == nil)
        precondition(drag.finish(), "Small pointer jitter still counts as a click")
        drag.begin(at: NSPoint(x: 100, y: 100), origin: NSPoint(x: 20, y: 30))
        precondition(drag.move(to: NSPoint(x: 104, y: 100)) == NSPoint(x: 24, y: 30))
        precondition(drag.move(to: NSPoint(x: 101, y: 100)) == NSPoint(x: 21, y: 30))
        precondition(!drag.finish(), "Dragging back inside the threshold must not open a chat")
        drag.begin(at: NSPoint(x: 100, y: 100), origin: NSPoint(x: 20, y: 30))
        precondition(drag.move(to: NSPoint(x: 80, y: 70)) == NSPoint(x: 0, y: 0))
        precondition(!drag.finish())
        let visible = NSRect(x: -1200, y: 20, width: 1200, height: 800)
        precondition(clampedPanelOrigin(NSPoint(x: -2000, y: -100), size: NSSize(width: 200, height: 46), visible: visible)
                     == NSPoint(x: -1200, y: 20))
        precondition(clampedPanelOrigin(NSPoint(x: 100, y: 900), size: NSSize(width: 200, height: 46), visible: visible)
                     == NSPoint(x: -200, y: 774))
        precondition(clampedPanelOrigin(NSPoint(x: 40, y: 50), size: NSSize(width: 2000, height: 1000), visible: visible)
                     == visible.origin)

        let controller = ChatController(command: ["/usr/bin/false", "chat", "A", "--json"])
        let context = ChatContext(session_id: "A", label: "Task", status: "waiting", needs_input: true,
                                  event_count: 1, queued_inputs: 0, finished: false)
        controller.contexts = [context]
        controller.stacks.open("A")
        controller.display = .panel
        controller.inputText = "Unsent draft"
        controller.minimizeCurrent()
        precondition(controller.collapsed && controller.stacks.contains("A") && controller.display == .hidden)
        controller.closeStack("A")
        precondition(!controller.stacks.contains("A") && controller.display == .hidden)
        precondition(controller.inputText == "Unsent draft" && controller.contexts[0].needs_input)
        try controller.synchronizeStacks([context])
        precondition(controller.display == .hidden && !controller.stacks.contains("A"), "Polling cannot reopen a closed task")
        controller.openContext("A")
        precondition(!controller.collapsed && controller.stacks.contains("A") && controller.display == .panel)
        precondition(controller.inputText == "Unsent draft", "Reopening must preserve the draft")
        var resizeRequests = 0
        controller.onCollapse = { _ in resizeRequests += 1 }
        controller.onStackLayout = { resizeRequests += 1 }
        controller.showTasks()
        controller.minimizeCurrent()
        let minimizedRequests = resizeRequests
        for _ in 0..<20 {
            try controller.synchronizeStacks([context])
            controller.minimizeCurrent()
        }
        precondition(resizeRequests == minimizedRequests, "Unchanged polling and repeated minimize cannot resize or animate the compact window")
        controller.inputText = "Keep this draft"
        controller.scrollTarget = "Earlier message"
        controller.showTasks()
        precondition(controller.showingTasks && !controller.collapsed)
        controller.openContext("A")
        precondition(!controller.showingTasks && controller.inputText == "Keep this draft"
                     && controller.scrollTarget == "Earlier message", "Back to task list and reopen must preserve the current draft and reading position")
        var quitRequests = 0
        controller.onStop = { quitRequests += 1 }
        controller.sendingSessions.insert("B")
        controller.requestStop()
        precondition(quitRequests == 0, "Quit cannot interrupt another task's local delivery")
        controller.sendingSessions.remove("B")
        controller.requestStop()
        precondition(quitRequests == 1 && controller.contexts[0].needs_input, "Quit closes the UI while retaining work and questions")
        try checkMenuEventOrdering()
        print("Interaction checks passed: click/drag threshold, drag reversal, minimize/hide/restore, draft preservation, menu/outside event ordering")
    }

    @MainActor static func checkMenuEventOrdering() throws {
        _ = NSApplication.shared
        let controller = ChatController(command: ["/usr/bin/false", "chat", "A", "--json"])
        controller.display = .panel
        controller.inputText = "Keep this draft"
        controller.scrollTarget = "Earlier message"
        var displays: [ViewerDisplay] = []
        controller.onDisplay = { displays.append($0) }
        var overMenuIcon = true
        var mouseClick = true
        let outside = try OutsideCollapse(controller: controller, isMenuInteraction: { _ in overMenuIcon }, isMouseClick: { mouseClick })
        defer { outside.stop() }
        func deactivate() { NotificationCenter.default.post(name: NSApplication.didResignActiveNotification, object: NSApp) }
        deactivate()
        precondition(controller.display == .panel && displays.isEmpty,
                     "A menu mouse-down cannot hide the panel before its own mouse-up toggles it")
        controller.toggleMenuPanel()
        deactivate()
        precondition(controller.display == .hidden && displays == [.hidden],
                     "A second menu click must hide once and stay hidden despite a delayed outside callback")
        deactivate()
        controller.toggleMenuPanel()
        deactivate()
        precondition(controller.display == .panel && displays == [.hidden, .panel],
                     "One menu click must reopen once regardless of deactivation callback ordering")
        controller.handleOutsideInteraction(overMenuIcon: false, timestamp: controller.panelShownAt - 1)
        precondition(controller.display == .panel, "A delayed click from before this reveal cannot hide the newly opened panel")
        mouseClick = false
        deactivate()
        precondition(controller.display == .hidden, "Keyboard app switching must still hide the panel with the pointer over its icon")
        controller.showTasks()
        mouseClick = true
        overMenuIcon = false
        deactivate()
        precondition(controller.display == .hidden && controller.collapsed,
                     "Clicks outside the menu must still hide both expanded and docked panels")
        controller.showTasks()
        controller.collapseToDock()
        deactivate()
        precondition(controller.display == .hidden)
        controller.display = .integrated
        controller.collapsed = false
        deactivate()
        precondition(controller.display == .integrated && !controller.collapsed,
                     "Panel outside handling cannot change the integrated pet mode")
        precondition(controller.inputText == "Keep this draft" && controller.scrollTarget == "Earlier message",
                     "Menu and outside events cannot clear drafts or the reading position")
        outside.stop()
        controller.display = .panel
        deactivate()
        precondition(controller.display == .panel, "Stopping outside monitoring must remove its notification side effects")
    }
}
