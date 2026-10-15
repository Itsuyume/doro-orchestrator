import Foundation

@MainActor
extension ChatController {
    func synchronizeInputStatus(_ view: Conversation) {
        guard !sending, let noteID = memories[selectedSession]?.lastInputID,
              let message = view.messages.first(where: { $0.id == noteID }) else { return }
        inputStatus = message.state
        memories[selectedSession]?.status = message.state
    }

    func retryDelivery(_ noteID: String) {
        guard !sending, let token = capabilities[selectedSession] else { return }
        let id = selectedSession
        let source = Array(sessionCommand(id).dropLast()) + ["--retry-delivery"]
        sendingSessions.insert(id)
        Task {
            defer { sendingSessions.remove(id) }
            do {
                let data = try JSONSerialization.data(withJSONObject: ["input_id": noteID])
                let result = try await Task.detached { try localCommand(source, input: data, capability: token) }.value
                let receipt = try JSONDecoder().decode(DeliveryReceipt.self, from: result)
                memories[id]?.lastInputID = noteID
                memories[id]?.status = receipt.status
                if selectedSession == id { inputStatus = receipt.status }
            } catch {
                if selectedSession == id { inputStatus = "연결 실패: \(error.localizedDescription)" }
            }
            refresh()
        }
    }

    func submit(session: String, text: String, checkpoint: String, decision: ApprovalDecision?) {
        guard !sending, let view = conversation, view.session_id == session, selectedSession == session, view.input_enabled,
              !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
            inputStatus = "전달 확인 실패: 전송 중이거나 이 작업의 입력 연결이 바뀌었도로. 내용을 보존했도로."
            refresh(); return
        }
        guard let token = capabilities[selectedSession] else {
            inputStatus = "스택 연결을 새로 열어줘도로. 입력 내용은 보존돼 있도로."; return
        }
        saveMemory()
        let id = session
        var memory = memories[id] ?? ContextMemory()
        let clientID = memory.submissions.begin(SubmissionKey(text: text, checkpoint: checkpoint, decision: decision))
        memories[id] = memory
        let source = sessionCommand(id)
        sendingSessions.insert(id)
        Task {
            defer { sendingSessions.remove(id) }
            do {
                let receipt = try await Task.detached {
                    try postInput(source, text: text, checkpoint: checkpoint, id: clientID, decision: decision?.rawValue ?? "", token: token)
                }.value
                recordSent(id: id, clientID: clientID, text: text, decision: decision, status: receipt.status)
                if let decision { approvals.markSent(session: id, checkpoint: checkpoint, decision: decision) }
                refresh()
            } catch {
                let status = "전달 확인 실패: \(error.localizedDescription) · 입력은 보존했도로."
                var saved = memories[id] ?? ContextMemory()
                saved.status = status
                saved.lastInputID = nil
                memories[id] = saved
                if selectedSession == id { inputStatus = status }
                refresh()
            }
        }
    }

    private func recordSent(id: String, clientID: String, text: String, decision: ApprovalDecision?, status: String) {
        var saved = memories[id] ?? ContextMemory()
        if decision == nil && saved.text == text { saved.text = "" }
        saved.status = status
        saved.lastInputID = clientID
        saved.submissions.confirmed(clientID)
        memories[id] = saved
        if selectedSession == id {
            if decision == nil { followLatest = true }
            if decision == nil && inputText == text { inputText = "" }
            inputStatus = saved.status
        }
    }

}
