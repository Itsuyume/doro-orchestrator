import Foundation

@main
struct StateChecks {
    static func view(_ id: String, message: ChatMessage? = nil) -> Conversation {
        Conversation(version: 1, session_id: id, title: "Local", status: "waiting", usage: "",
            messages: message.map { [$0] } ?? [], reply_hint: "", input_enabled: true, checkpoint_id: "", label: "Local",
            contexts: [], claude_enabled: true, agy_enabled: false, approval: nil, model_selection: nil, input_limit: 2000)
    }

    @MainActor static func restart(_ directory: URL) throws {
        let store = ContextStateStore(file: NativeStateFile(path: directory.appendingPathComponent("state.json"), maxBytes: 2_000_000))
        let a = UUID().uuidString, b = UUID().uuidString
        let controller = ChatController(command: ["/usr/bin/false", "chat", a, "--json"], persistState: store.save)
        controller.inputText = "Draft A"
        controller.scrollTarget = "turn-2"
        var memory = ContextMemory()
        let key = SubmissionKey(text: "Draft A", checkpoint: "", decision: nil)
        let pending = memory.submissions.begin(key)
        memory.lastInputID = pending
        controller.memories[a] = memory
        precondition(controller.saveMemory())
        precondition(controller.switchSession(b))
        controller.inputText = "Draft B"
        controller.requestStop()
        let restored = ChatController(command: ["/usr/bin/false", "chat", a, "--json"],
                                      state: try store.load(), persistState: store.save)
        precondition(restored.selectedSession == b && restored.inputText == "Draft B")
        precondition(restored.switchSession(a) && restored.inputText == "Draft A" && restored.scrollTarget == "turn-2")
        var retry = restored.memories[a]!.submissions
        precondition(retry.begin(key) == pending, "Restart must retain an uncertain attempt's client ID")
        let message = ChatMessage(id: pending, sender: "나", phase: "개입 메시지", text: "Draft A",
            state: "도로 확인", incoming: "", main: false, from_user: true, retryable: false)
        let snapshot = view(a, message: message)
        restored.conversation = snapshot
        restored.synchronizeInputStatus(snapshot)
        precondition(restored.inputText.isEmpty && restored.inputStatus == "도로 확인")
        let state = try store.load()
        precondition(state.memories[b]?.text == "Draft B" && state.memories[a]?.submissions.contains(pending) == false)
        restored.followLatest = false
        restored.inputText = "Draft A"
        let updated = view(a, message: ChatMessage(id: pending, sender: "나", phase: "개입 메시지", text: "Draft A",
            state: "갱신된 상태", incoming: "", main: false, from_user: true, retryable: false))
        restored.synchronizeInputStatus(updated)
        precondition(!restored.followLatest && restored.inputText == "Draft A",
                     "Later status changes cannot clear a newly typed identical draft or move the reading position")
        let permissions = try FileManager.default.attributesOfItem(atPath: store.file.path.path)[.posixPermissions] as? NSNumber
        precondition(permissions?.intValue == 0o600)
    }

    @MainActor static func failure(_ directory: URL) throws {
        let file = NativeStateFile(path: directory.appendingPathComponent("corrupt.json"), maxBytes: 2_000_000)
        try Data("broken".utf8).write(to: file.path)
        do { _ = try ContextStateStore(file: file).load(); preconditionFailure("Corrupt state must fail visibly") }
        catch { precondition(error is DecodingError) }
        let preserved = try Data(contentsOf: file.path)
        precondition(preserved == Data("broken".utf8))
        let dangling = directory.appendingPathComponent("dangling.json")
        try FileManager.default.createSymbolicLink(at: dangling, withDestinationURL: directory.appendingPathComponent("absent"))
        do { try NativeStateFile(path: dangling, maxBytes: 20).write(Data()); preconditionFailure("Dangling symlink must be rejected") }
        catch { precondition(error is ChatReadError) }
        let bad = ContextStateStore(file: NativeStateFile(path: directory.appendingPathComponent("absent/state"), maxBytes: 2000))
        let controller = ChatController(command: ["/usr/bin/false", "chat", UUID().uuidString, "--json"], persistState: bad.save)
        controller.inputText = "Keep local text"
        var quits = 0; controller.onStop = { quits += 1 }
        controller.requestStop()
        precondition(quits == 0 && !controller.storageError.isEmpty && controller.inputText == "Keep local text")
        let recovery = ContextPersistence(store: ContextStateStore(file: file))
        precondition(!recovery.loadError.isEmpty)
        let empty = ChatController(command: ["/usr/bin/false", "chat", UUID().uuidString, "--json"],
                                   state: recovery.initialState, persistState: recovery.save)
        var emptyStops = 0; empty.onStop = { emptyStops += 1 }
        empty.requestStop()
        precondition(emptyStops == 1, "An unreadable saved file cannot trap an empty live window")
        let afterEmptyStop = try Data(contentsOf: file.path)
        precondition(afterEmptyStop == preserved)
        do { try recovery.recover(ContextState(version: 9)); preconditionFailure("Invalid recovery must fail") }
        catch { precondition(error is ChatReadError) }
        let afterFailure = try Data(contentsOf: file.path)
        precondition(afterFailure == preserved, "Failed recovery must restore the original bytes")
        try recovery.recover(ContextState())
        let backups = try FileManager.default.contentsOfDirectory(at: directory, includingPropertiesForKeys: nil)
            .filter { $0.lastPathComponent.hasPrefix("corrupt.backup-") }
        precondition(backups.count == 1 && recovery.loadError.isEmpty)
        let backup = try Data(contentsOf: backups[0])
        precondition(backup == preserved)
    }

    @MainActor static func preSendFailure(_ directory: URL) async throws {
        let active = directory.appendingPathComponent("active")
        try FileManager.default.createDirectory(at: active, withIntermediateDirectories: false)
        let store = ContextStateStore(file: NativeStateFile(path: active.appendingPathComponent("state.json"), maxBytes: 2000))
        let called = directory.appendingPathComponent("called")
        let script = directory.appendingPathComponent("send.py")
        try Data("import sys\nfrom pathlib import Path\nPath(sys.argv[1]).touch()\n".utf8).write(to: script)
        let id = UUID().uuidString
        var writes = 0
        let controller = ChatController(command: ["/usr/bin/python3", script.path, called.path, "chat", id, "--json"],
            persistState: { state in
                try store.save(state)
                writes += 1
                if writes == 1 { try FileManager.default.moveItem(at: active, to: directory.appendingPathComponent("moved")) }
            })
        controller.conversation = view(id)
        controller.capabilities[id] = "fixture"
        controller.inputText = "Keep this draft"
        controller.submitInput()
        try await Task.sleep(for: .milliseconds(100))
        precondition(!controller.sending && !FileManager.default.fileExists(atPath: called.path))
        precondition(controller.inputText == "Keep this draft" && controller.inputStatus.hasSuffix("보내지 않았도로."))
        precondition(!controller.storageError.isEmpty && controller.memories[id]?.lastInputID != nil)
    }

    @MainActor static func acknowledgement(_ directory: URL) throws {
        setenv("DORO_CHAT_REQUEST", directory.appendingPathComponent("request.json").path, 1)
        let ack = directory.appendingPathComponent("viewer-ack.json")
        try FileManager.default.createDirectory(at: ack, withIntermediateDirectories: false)
        let id = UUID().uuidString
        let controller = ChatController(command: ["/usr/bin/false", "chat", id, "--json"])
        let request = ViewerRequest(version: 1, request_id: UUID().uuidString, session_id: id,
                                    display: .stop, tokens: [:], show_tasks: false, intent: .open)
        var stops = 0; controller.onStop = { stops += 1 }
        do { try controller.applyViewerRequest(request); preconditionFailure("Ack write must fail") }
        catch { precondition(controller.appliedRequestID.isEmpty && stops == 0) }
        try FileManager.default.removeItem(at: ack)
        try controller.applyViewerRequest(request)
        try controller.applyViewerRequest(request)
        precondition(stops == 1 && controller.appliedRequestID == request.request_id)
        let unknown = ViewerRequest(version: 1, request_id: UUID().uuidString, session_id: UUID().uuidString,
                                    display: .panel, tokens: [:], show_tasks: false, intent: .open)
        do { try controller.applyViewerRequest(unknown); preconditionFailure("Unregistered context must be rejected") }
        catch { precondition(controller.selectedSession == id) }
    }

    @MainActor static func inputLimits() {
        let id = UUID().uuidString
        let controller = ChatController(command: ["/usr/bin/false", "chat", id, "--json"])
        controller.conversation = view(id)
        controller.inputText = String(repeating: "🇰🇷", count: 1000)
        precondition(controller.canSendInput)
        controller.inputText += "x"
        precondition(!controller.canSendInput)
        controller.submitInput()
        precondition(controller.memories[id]?.lastInputID == nil && !controller.inputStatus.isEmpty)
        controller.inputStatus = ""
        controller.submit(session: id, text: "  \n", checkpoint: "", decision: nil)
        precondition(controller.inputStatus.isEmpty, "Empty input must not show a connection error")
        precondition(controller.inputProblem("\0") != nil)
    }

    @MainActor static func sendFailure() async throws {
        let controller = ChatController(command: ["/usr/bin/false", "chat", "A", "--json"])
        controller.conversation = view("A")
        controller.capabilities["A"] = "fixture"
        let draft = String(repeating: "한글 초안 🇰🇷\n", count: 20)
        controller.inputText = draft
        controller.submitInput()
        for _ in 0..<100 {
            if !controller.sending { break }
            try await Task.sleep(for: .milliseconds(10))
        }
        precondition(!controller.sending && controller.inputText == draft && controller.memories["A"]?.text == draft,
                     "An external send failure cannot clear a multiline Korean draft")
        precondition(controller.inputStatus.hasPrefix("전달 확인 실패:") && controller.memories["A"]?.lastInputID != nil,
                     "Failure stays visible and keeps the same uncertain submission ID")
    }

    @MainActor static func main() async throws {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: false)
        defer { try? FileManager.default.removeItem(at: directory) }
        try restart(directory)
        try failure(directory)
        try await preSendFailure(directory)
        try await sendFailure()
        try acknowledgement(directory)
        inputLimits()
        print("State checks passed: private drafts/restart, uncertain IDs, receipt reconciliation, write failure, corrupt/symlink safety, ack retry, Unicode/empty input")
    }
}
