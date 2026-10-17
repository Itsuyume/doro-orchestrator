import Foundation

@MainActor
extension ChatController {
    func submitApproval(_ decision: ApprovalDecision, target: ApprovalTarget) {
        guard approvals.canSubmit(target, current: conversation), selectedSession == target.sessionID else {
            inputStatus = "전달 확인 실패: 질문이 바뀌었거나 답변이 접수됐도로. 현재 상태를 다시 확인하겠도로."
            refresh(); return
        }
        guard readError.isEmpty else { inputStatus = readError; refresh(); return }
        submit(session: target.sessionID,
               text: decision == .approve ? "이 스택의 범위 승인해도로" : "이 스택의 범위 거절해도로",
               checkpoint: target.approval.checkpoint_id, decision: decision)
    }

    func synchronizeApproval(_ view: Conversation) {
        let visible = display != .hidden && display != .stop && !collapsed && !showingTasks && !showingNewTask
        approvals.synchronize(view, automatic: visible)
        let requested = requestedApprovalSession
        requestedApprovalSession = nil
        if visible && requested == view.session_id && approvals.presented != nil { onApprovalOpen?() }
    }

    func openApproval(_ session: String) {
        guard contexts.contains(where: { $0.id == session && $0.needs_input }) else { return }
        requestedApprovalSession = session
        openContext(session)
        if selectedSession != session || showingTasks || collapsed || display == .hidden {
            requestedApprovalSession = nil
        }
    }
}
