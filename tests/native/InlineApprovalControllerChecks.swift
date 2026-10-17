import AppKit

@main
struct InlineApprovalControllerChecks {
    static func view() -> Conversation {
        Conversation(version: 1, session_id: "A", title: "Task", status: "waiting", usage: "", messages: [],
                     reply_hint: "", input_enabled: true, checkpoint_id: "one", label: "Task A", contexts: [],
                     claude_enabled: true, agy_enabled: false,
                     approval: ChatApproval(checkpoint_id: "one", kind: "Apply", brief: "Short", details: "Detail",
                                            response_pending: false, response_decision: nil), model_selection: nil)
    }

    @MainActor static func main() {
        let controller = ChatController(command: ["/usr/bin/false", "chat", "A", "--json"])
        let snapshot = view()
        controller.conversation = snapshot
        controller.display = .panel
        var focusRequests = 0
        controller.onApprovalOpen = { focusRequests += 1 }
        controller.requestedApprovalSession = "B"
        controller.synchronizeApproval(snapshot)
        precondition(controller.requestedApprovalSession == nil && focusRequests == 0,
                     "A mismatched old request is consumed without focusing another session")
        controller.display = .hidden
        controller.requestedApprovalSession = "A"
        controller.synchronizeApproval(snapshot)
        precondition(controller.approvals.presented == nil && focusRequests == 0,
                     "A hidden chat must not show actions or receive delayed focus")
        controller.display = .panel
        controller.showingTasks = true
        controller.synchronizeApproval(snapshot)
        precondition(controller.approvals.presented == nil, "Task-list polling cannot show an approval")
        controller.showingTasks = false
        controller.requestedApprovalSession = "A"
        controller.synchronizeApproval(snapshot)
        precondition(controller.approvals.presented?.sessionID == "A" && focusRequests == 1)
        controller.synchronizeApproval(snapshot)
        precondition(focusRequests == 1, "Normal polling cannot steal composer focus")
        checkFailedSwitch()
        print("Inline approval controller checks passed: stale request, hidden, task list, explicit focus, failed switch")
    }

    @MainActor static func checkFailedSwitch() {
        let controller = ChatController(command: ["/usr/bin/false", "chat", "A", "--json"],
                                        persistState: { _ in throw CocoaError(.fileWriteNoPermission) })
        controller.display = .panel
        controller.contexts = [ChatContext(session_id: "B", label: "B", status: "waiting", needs_input: true,
                                          event_count: 1, queued_inputs: 0, finished: false)]
        controller.openApproval("B")
        precondition(controller.selectedSession == "A" && controller.requestedApprovalSession == nil,
                     "An unsuccessful context switch must not leave a delayed approval-focus request")
    }
}
