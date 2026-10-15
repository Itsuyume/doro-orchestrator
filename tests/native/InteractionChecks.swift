import AppKit

@main
struct InteractionChecks {
    @MainActor static func main() {
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

        let controller = ChatController(command: ["/usr/bin/false", "chat", "A", "--json"])
        let context = ChatContext(session_id: "A", label: "Task", status: "waiting", needs_input: true,
                                  event_count: 1, queued_inputs: 0, finished: false)
        controller.contexts = [context]
        controller.stacks.open("A")
        controller.display = .panel
        controller.inputText = "Unsent draft"
        controller.minimizeCurrent()
        precondition(controller.collapsed && controller.stacks.contains("A") && controller.display == .panel)
        controller.closeStack("A")
        precondition(!controller.stacks.contains("A") && controller.display == .hidden)
        precondition(controller.inputText == "Unsent draft" && controller.contexts[0].needs_input)
        controller.synchronizeStacks([context])
        precondition(controller.display == .hidden && !controller.stacks.contains("A"), "Polling cannot reopen a closed task")
        controller.openContext("A")
        precondition(!controller.collapsed && controller.stacks.contains("A") && controller.display == .panel)
        precondition(controller.inputText == "Unsent draft", "Reopening must preserve the draft")
        print("Interaction checks passed: click/drag threshold, drag reversal, minimize, hide, restore, draft preservation")
    }
}
