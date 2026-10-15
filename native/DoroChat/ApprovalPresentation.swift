import Foundation

struct ApprovalTarget: Equatable, Identifiable {
    let sessionID: String
    let label: String
    let approval: ChatApproval
    var id: String { sessionID + ":" + approval.checkpoint_id }
}

struct ApprovalPresentation {
    var presented: ApprovalTarget?
    private(set) var seen: Set<String> = []
    private var sent: [String: ApprovalDecision] = [:]

    init(seen: Set<String> = []) { self.seen = seen }

    mutating func synchronize(_ view: Conversation, automatic: Bool) {
        guard let approval = view.approval else { presented = nil; return }
        let target = ApprovalTarget(sessionID: view.session_id, label: view.label, approval: approval)
        if let current = presented, current.id != target.id { presented = nil }
        if responsePending(target) { presented = nil; return }
        if presented?.id == target.id { presented = target; return }
        if automatic && !seen.contains(target.id) { open(view) }
    }

    mutating func open(_ view: Conversation) {
        guard let approval = view.approval else { return }
        let target = ApprovalTarget(sessionID: view.session_id, label: view.label, approval: approval)
        guard !responsePending(target) else { return }
        presented = target
        seen.insert(view.session_id + ":" + approval.checkpoint_id)
    }

    mutating func dismiss() { presented = nil }
    mutating func markSent(session: String, checkpoint: String, decision: ApprovalDecision) {
        let id = session + ":" + checkpoint
        sent[id] = decision
        seen.insert(id)
        if presented?.id == id { presented = nil }
    }
    func responsePending(_ target: ApprovalTarget) -> Bool { target.approval.response_pending || sent[target.id] != nil }
    func responseDecision(_ target: ApprovalTarget) -> ApprovalDecision? {
        ApprovalDecision(rawValue: target.approval.response_decision ?? "") ?? sent[target.id]
    }

    func canSubmit(_ target: ApprovalTarget, current: Conversation?) -> Bool {
        guard let current, current.input_enabled, current.session_id == target.sessionID,
              current.approval?.checkpoint_id == target.approval.checkpoint_id,
              current.approval?.response_pending == false, presented?.id == target.id else { return false }
        return !responsePending(target)
    }
}
