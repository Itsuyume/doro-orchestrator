import Foundation

@MainActor
extension ChatController {
    func beginNewTask() {
        guard saveMemory() else { return }
        if newTask.sourceSession == nil { newTask.sourceSession = selectedSession }
        showingNewTask = true
        collapsed = false
        pollNewTask(force: true)
    }

    var canStartNewTask: Bool {
        !newTaskBusy && !newTask.text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            && inputProblem(newTask.text) == nil && (!newTask.queued || newTask.retryable || newTask.creationFailed)
    }

    func submitNewTask() {
        guard canStartNewTask else { return }
        if newTask.creationFailed { newTask.id = nil; newTask.queued = false; newTask.creationFailed = false }
        guard let source = newTask.sourceSession, let token = capabilities[source] else {
            newTask.status = "작업 연결을 다시 열어줘도로. 입력은 보존했도로."; return
        }
        newTask.id = newTask.id ?? UUID().uuidString.lowercased()
        newTask.queued = true
        newTask.retryable = false
        newTask.status = "새 작업 요청을 전달하는 중이도로."
        guard saveMemory(), let id = newTask.id else { return }
        let command = Array(sessionCommand(source).dropLast(3)) + ["new-task", "request", "--source-session", source]
        let text = newTask.text
        newTaskBusy = true
        Task {
            defer { newTaskBusy = false }
            do {
                let payload = try JSONSerialization.data(withJSONObject: ["text": text, "client_id": id])
                let data = try await Task.detached { try localCommand(command, input: payload, capability: token) }.value
                let receipt = try JSONDecoder().decode(NewTaskReceipt.self, from: data)
                applyNewTask(receipt.request, delivery: receipt.delivery)
            } catch { newTask.status = "전달 결과를 확인하는 중이도로: \(error.localizedDescription)" }
            saveMemory()
        }
    }

    func pollNewTask(force: Bool = false) {
        let now = ProcessInfo.processInfo.systemUptime
        guard newTask.queued, !newTaskBusy, !newTaskPolling, force || now - lastNewTaskPoll >= 3,
              let id = newTask.id, let source = newTask.sourceSession, let token = capabilities[source] else { return }
        lastNewTaskPoll = now
        newTaskPolling = true
        let command = Array(sessionCommand(source).dropLast(3)) + ["new-task", "status", id, "--source-session", source]
        Task {
            defer { newTaskPolling = false }
            do {
                let data = try await Task.detached { try localCommand(command, capability: token) }.value
                let record = try JSONDecoder().decode(NewTaskRecord.self, from: data)
                guard newTask.id == id else { return }
                let previous = newTask
                applyNewTask(record, delivery: record.delivery)
                if newTask != previous { saveMemory() }
            } catch { newTask.status = "새 작업 연결 확인 실패: \(error.localizedDescription)" }
        }
    }

    func applyNewTask(_ record: NewTaskRecord, delivery: NewTaskDelivery?) {
        guard record.id == newTask.id else { return }
        if record.state == "created" {
            guard UUID(uuidString: record.session_id) != nil, UUID(uuidString: record.thread_id) != nil,
                  let token = record.token, !token.isEmpty else {
                newTask.status = "새 대화의 연결 확인을 기다리는 중이도로."; return
            }
            capabilities[record.session_id] = token
            if showingNewTask {
                guard switchSession(record.session_id, openingStack: true) else { return }
                showingNewTask = false
                showingTasks = false
            } else {
                stacks.open(record.session_id)
            }
            newTask = NewTaskDraft()
            refresh()
            return
        }
        var next = newTask
        next.creationFailed = record.state == "failed"
        next.retryable = record.state == "not_submitted" || (record.state == "pending" && (delivery == nil || delivery?.state == "failed"))
        if !record.error.isEmpty { next.status = record.error }
        else if let delivery, !delivery.error.isEmpty { next.status = "전달 확인 필요: " + delivery.error }
        else { next.status = record.state == "creating" ? "새 GPT 대화를 만드는 중이도로." : "GPT가 새 작업 요청을 확인하는 중이도로." }
        if next != newTask { newTask = next }
    }
}
