import Foundation

@main
struct ApprovalChecks {
    static func view(_ session: String, _ question: String, pending: Bool = false, label: String? = nil,
                     decision: String? = nil) -> Conversation {
        Conversation(version: 1, session_id: session, title: "Task", status: "waiting", usage: "", messages: [],
                     reply_hint: "", input_enabled: true, checkpoint_id: question, label: label ?? session, contexts: [],
                     claude_enabled: true, agy_enabled: false,
                     approval: question.isEmpty ? nil : ChatApproval(checkpoint_id: question, kind: "Apply", brief: "Short",
                                                                     details: "Full detail", response_pending: pending,
                                                                     response_decision: decision),
                     model_selection: nil)
    }

    static func main() {
        let a = view("A", "one"), b = view("B", "two")
        var state = ApprovalPresentation()
        state.synchronize(a, automatic: false)
        precondition(state.presented == nil && state.seen.isEmpty, "Collapsed polling must not show a popup")
        state.synchronize(a, automatic: true)
        let target = state.presented!
        precondition(state.canSubmit(target, current: a))
        precondition(state.canSubmit(target, current: view("A", "one", label: "New label")))
        precondition(!state.canSubmit(target, current: b), "A's approval cannot target B")
        precondition(!state.canSubmit(target, current: view("A", "replacement")), "Stale checkpoint rejected")
        state.dismiss()
        state.synchronize(a, automatic: true)
        precondition(state.presented == nil, "Closing must not reopen on the next poll")
        var restored = ApprovalPresentation(seen: state.seen)
        restored.synchronize(a, automatic: true)
        precondition(restored.presented == nil, "Restarted viewer must preserve the once-only announcement")
        restored.open(a)
        precondition(restored.canSubmit(target, current: a), "Explicit reopen still works")
        restored.markSent(session: "A", checkpoint: "one", decision: .approve)
        precondition(restored.presented == nil, "Confirmed queue write must close the approval window immediately")
        precondition(restored.responseDecision(target) == .approve, "Show the decision actually queued")
        precondition(!restored.canSubmit(target, current: a), "Duplicate decisions blocked while Work is pending")
        restored.synchronize(a, automatic: true)
        precondition(restored.presented == nil, "A stale poll must not reopen a submitted question")
        restored.synchronize(view("A", ""), automatic: true)
        precondition(restored.presented == nil, "Resolved approval disappears, without claiming application")
        state.synchronize(view("A", "one", pending: true), automatic: true)
        precondition(state.presented == nil, "Queued decisions must not pop up as a new question")
        restored.open(view("A", "one", pending: true, decision: "reject"))
        precondition(restored.presented == nil, "An answered question cannot reopen as an approval dialog")
        let queued = ApprovalTarget(sessionID: "A", label: "A", approval: view("A", "one", pending: true, decision: "reject").approval!)
        precondition(restored.responseDecision(queued) == .reject, "Persisted receipt overrides optimistic state")
        var refreshed = ApprovalPresentation()
        refreshed.open(a)
        refreshed.synchronize(view("A", "one", pending: true), automatic: true)
        precondition(refreshed.presented == nil, "A committed write with a lost response closes after receipt refresh")
        refreshed.open(b)
        refreshed.markSent(session: "A", checkpoint: "one", decision: .approve)
        precondition(refreshed.presented?.sessionID == "B", "A late result from A must not close B's question")
        refreshed.synchronize(b, automatic: true)
        precondition(refreshed.canSubmit(refreshed.presented!, current: b), "Unconfirmed writes remain visible and retryable")
        print("Approval checks passed: receipt closes, stale poll, failed write, cross-session result, restart, exact target")
    }
}
