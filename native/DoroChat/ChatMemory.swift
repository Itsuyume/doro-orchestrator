import Foundation

@MainActor
extension ChatController {
    private func captureMemory() -> ContextState {
        var memory = memories[selectedSession] ?? ContextMemory()
        memory.text = inputText
        memory.status = inputStatus
        memory.expanded = expandedMessages
        memory.scrollTarget = scrollTarget
        memories[selectedSession] = memory
        return ContextState(selectedSession: selectedSession, memories: memories)
    }

    @discardableResult func saveMemory() -> Bool {
        saveGeneration += 1
        do { try persistState(captureMemory()) }
        catch { storageError = "초안 저장 실패: \(error.localizedDescription)"; return false }
        storageError = ""
        return true
    }

    func scheduleStateSave() {
        saveGeneration += 1
        let serial = saveGeneration
        DispatchQueue.main.asyncAfter(deadline: .now() + .milliseconds(400)) { [weak self] in
            guard let self, self.saveGeneration == serial else { return }
            self.saveMemory()
        }
    }

    var canRecoverState: Bool { canQuit && !storageError.isEmpty && recoverPersistence != nil }

    func recoverState() {
        guard canRecoverState, let recoverPersistence else { return }
        saveGeneration += 1
        do { try recoverPersistence(captureMemory()) }
        catch { storageError = "초안 복구 실패: \(error.localizedDescription)"; return }
        storageError = ""
        inputStatus = "원본을 보관하고 현재 입력을 저장했도로."
        saveMemory()
        refresh()
    }

    func prepareToStop() -> Bool {
        if saveMemory() { return true }
        return memories.values.allSatisfy { $0.text.isEmpty && $0.submissions.isEmpty }
    }
}
