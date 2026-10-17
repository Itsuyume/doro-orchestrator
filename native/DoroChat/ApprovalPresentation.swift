import Foundation

struct ApprovalTarget: Equatable, Identifiable {
    let sessionID: String
    let label: String
    let approval: ChatApproval
    var id: String { sessionID + ":" + approval.checkpoint_id }
}

struct ApprovalPresentation {
    var presented: ApprovalTarget?
    private var sent: [String: ApprovalDecision] = [:]

    mutating func synchronize(_ view: Conversation, automatic: Bool) {
        guard let approval = view.approval else { presented = nil; return }
        let target = ApprovalTarget(sessionID: view.session_id, label: view.label, approval: approval)
        presented = automatic && !responsePending(target) ? target : nil
    }

    mutating func dismiss() { presented = nil }
    mutating func markSent(session: String, checkpoint: String, decision: ApprovalDecision) {
        let id = session + ":" + checkpoint
        sent[id] = decision
        if presented?.id == id { presented = nil }
    }
    func responsePending(_ target: ApprovalTarget) -> Bool { target.approval.response_pending || sent[target.id] != nil }
    func responseDecision(_ target: ApprovalTarget) -> ApprovalDecision? {
        ApprovalDecision(rawValue: target.approval.response_decision ?? "") ?? sent[target.id]
    }

    func canSubmit(_ target: ApprovalTarget, current: Conversation?) -> Bool {
        guard let current, current.input_enabled, current.session_id == target.sessionID,
              current.approval == target.approval,
              current.approval?.response_pending == false, presented?.id == target.id else { return false }
        return !responsePending(target)
    }
}
