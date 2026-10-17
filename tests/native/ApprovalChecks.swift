import Foundation

@main
struct ApprovalChecks {
    static func view(_ session: String, _ question: String, pending: Bool = false, label: String? = nil,
                     decision: String? = nil, brief: String = "Short") -> Conversation {
        Conversation(version: 1, session_id: session, title: "Task", status: "waiting", usage: "", messages: [],
                     reply_hint: "", input_enabled: true, checkpoint_id: question, label: label ?? session, contexts: [],
                     claude_enabled: true, agy_enabled: false,
                     approval: question.isEmpty ? nil : ChatApproval(checkpoint_id: question, kind: "Apply", brief: brief,
                                                                     details: "Full detail", response_pending: pending,
                                                                     response_decision: decision),
                     model_selection: nil)
    }

    static func main() {
        let a = view("A", "one"), b = view("B", "two")
        var state = ApprovalPresentation()
        state.synchronize(a, automatic: false)
        precondition(state.presented == nil, "Collapsed polling must not expose an inline question")
        state.synchronize(a, automatic: true)
        let target = state.presented!
        precondition(state.canSubmit(target, current: a))
        precondition(state.canSubmit(target, current: view("A", "one", label: "New label")))
        precondition(!state.canSubmit(target, current: b), "A's approval cannot target B")
        precondition(!state.canSubmit(target, current: view("A", "replacement")), "Stale checkpoint rejected")
        precondition(!state.canSubmit(target, current: view("A", "one", brief: "Changed impact")),
                     "Same ID with changed question content rejects a stale click")
        state.dismiss()
        state.synchronize(a, automatic: true)
        precondition(state.presented?.id == target.id, "Expanded chat must keep the unanswered inline question accessible")
        var restored = ApprovalPresentation()
        restored.synchronize(a, automatic: true)
        precondition(restored.presented?.id == target.id, "Restarted expanded chat must display its unanswered inline actions")
        restored.synchronize(a, automatic: true)
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
        restored.synchronize(view("A", "one", pending: true, decision: "reject"), automatic: true)
        precondition(restored.presented == nil, "An answered question cannot reopen as an approval dialog")
        let queued = ApprovalTarget(sessionID: "A", label: "A", approval: view("A", "one", pending: true, decision: "reject").approval!)
        precondition(restored.responseDecision(queued) == .reject, "Persisted receipt overrides optimistic state")
        var refreshed = ApprovalPresentation()
        refreshed.synchronize(a, automatic: true)
        refreshed.synchronize(view("A", "one", pending: true), automatic: true)
        precondition(refreshed.presented == nil, "A committed write with a lost response closes after receipt refresh")
        refreshed.synchronize(b, automatic: true)
        refreshed.markSent(session: "A", checkpoint: "one", decision: .approve)
        precondition(refreshed.presented?.sessionID == "B", "A late result from A must not close B's question")
        refreshed.synchronize(b, automatic: true)
        precondition(refreshed.canSubmit(refreshed.presented!, current: b), "Unconfirmed writes remain visible and retryable")
        var rejected = ApprovalPresentation()
        rejected.synchronize(a, automatic: true)
        rejected.markSent(session: "A", checkpoint: "one", decision: .reject)
        rejected.synchronize(a, automatic: true)
        precondition(rejected.presented == nil && rejected.responseDecision(target) == .reject,
                     "Reject must hide inline actions immediately and preserve the actual decision")
        print("Approval checks passed: inline visibility, receipt closes, rejection, stale poll, failure, cross-session, restart")
    }
}
