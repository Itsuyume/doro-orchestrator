import AppKit

@main
struct TaskListChecks {
    @MainActor static func main() throws {
        let expanded = TaskListLayout.contentHeight(open: 2, expanded: true, history: 3,
            historyExpanded: false, selecting: false, undo: true)
        let folded = TaskListLayout.contentHeight(open: 2, expanded: false, history: 3,
            historyExpanded: false, selecting: false, undo: true)
        precondition(expanded - folded == 112, "Folding affects only the open rows")
        let history = TaskListLayout.contentHeight(open: 2, expanded: false, history: 3,
            historyExpanded: true, selecting: true, undo: true)
        precondition(history - folded == 3 * 56 + 28, "History and selection remain independently usable")
        let empty = TaskListLayout.contentHeight(open: 0, expanded: false, history: 0,
            historyExpanded: false, selecting: false, undo: false)
        precondition(taskListHeight(content: empty) == 130)
        precondition(taskListHeight(content: expanded) > taskListHeight(content: folded))
        precondition(taskListHeight(content: 10000) == 620)
        try checkListActions()
        checkWindowMotion()
        checkMouseSwipe()
        print("Task list checks passed: fold height, independent history, close stays open, protected records, undo, hidden motion")
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
        controller.showingTasks = true
        controller.display = .panel
        controller.inputText = "Unsent draft"
        controller.scrollTarget = "earlier"
        controller.closeStack(a)
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
        var userMoves = 0
        window.onUserMove = { userMoves += 1 }
        let target = NSRect(x: 110, y: 120, width: 390, height: 240)
        InterfaceMotion.frame(target, for: window, animated: true)
        precondition(window.frame == target && !window.isVisible && userMoves == 0,
                     "Programmatic layout cannot reveal a hidden window or masquerade as a user drag")
        window.moveFromUser(to: NSPoint(x: 130, y: 140))
        precondition(userMoves == 1 && window.frame.origin == NSPoint(x: 130, y: 140))
    }
}
