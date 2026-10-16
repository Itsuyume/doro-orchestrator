import Foundation

@main
struct PersistenceBoundaryChecks {
    enum StorageFailure: Error { case unavailable }

    @MainActor static func check(_ condition: Bool, _ message: String) {
        guard !condition else { return }
        FileHandle.standardError.write(Data((message + "\n").utf8))
        exit(1)
    }

    static func context(_ id: String, approval: Bool = false) -> ChatContext {
        ChatContext(session_id: id, label: id, status: "waiting", needs_input: approval,
                    event_count: 2, queued_inputs: 0, finished: !approval)
    }

    @MainActor static func transitionFailures() {
        let a = UUID().uuidString, b = UUID().uuidString
        var writes = 0
        let failedDraft = ChatController(command: ["/usr/bin/false", "chat", a, "--json"],
            history: StackHistorySnapshot(removed: [b], undo: [b]), saveHistory: { _ in writes += 1 },
            persistState: { _ in throw StorageFailure.unavailable })
        failedDraft.contexts = [context(a), context(b)]
        failedDraft.stacks.open(a)
        failedDraft.lastRemoved = [b]
        failedDraft.showingTasks = true
        failedDraft.display = .panel
        failedDraft.inputText = "Keep this draft"
        failedDraft.scrollTarget = "earlier"
        failedDraft.openContext(b)
        check(failedDraft.selectedSession == a && failedDraft.showingTasks && failedDraft.display == .panel,
              "Draft failure must keep the current selection and task list")
        check(failedDraft.stacks.removed == [b] && !failedDraft.stacks.contains(b)
              && failedDraft.lastRemoved == [b] && writes == 0, "Draft failure cannot restore history or undo state")
        check(failedDraft.inputText == "Keep this draft" && failedDraft.scrollTarget == "earlier"
              && !failedDraft.storageError.isEmpty, "Draft and reading position survive with a visible error")

        var draftWrites = 0
        let failedHistory = ChatController(command: ["/usr/bin/false", "chat", a, "--json"],
            history: StackHistorySnapshot(removed: [b], undo: [b]),
            saveHistory: { _ in throw StorageFailure.unavailable }, persistState: { _ in draftWrites += 1 })
        failedHistory.contexts = [context(a), context(b)]
        failedHistory.showingTasks = true
        failedHistory.display = .hidden
        failedHistory.collapsed = true
        failedHistory.inputText = "Keep this draft"
        failedHistory.openContext(b)
        check(failedHistory.selectedSession == a && failedHistory.showingTasks && failedHistory.collapsed
              && failedHistory.display == .hidden, "History failure cannot reveal or switch the window")
        check(failedHistory.stacks.removed == [b] && !failedHistory.stacks.contains(b) && draftWrites == 1,
              "History failure preserves membership and saves the draft exactly once")
        check(!failedHistory.controlError.isEmpty && failedHistory.storageError.isEmpty,
              "History errors must be visible without masquerading as draft errors")
    }

    @MainActor static func transitionSuccess() {
        let a = UUID().uuidString, b = UUID().uuidString
        var drafts: [ContextState] = [], history: [StackHistorySnapshot] = []
        let controller = ChatController(command: ["/usr/bin/false", "chat", a, "--json"],
            history: StackHistorySnapshot(removed: [b], undo: [b]), saveHistory: { history.append($0) },
            persistState: { drafts.append($0) })
        controller.contexts = [context(a), context(b)]
        controller.inputText = "Draft A"
        controller.memories[b] = ContextMemory(text: "Draft B")
        controller.showingTasks = true
        controller.display = .panel
        controller.openContext(b)
        check(controller.selectedSession == b && controller.inputText == "Draft B" && !controller.showingTasks,
              "Successful navigation restores the target draft and opens the transcript")
        check(controller.stacks.contains(b) && controller.lastRemoved.isEmpty && history.count == 1
              && history[0].removed.isEmpty, "History commits once before the visible transition")
        check(drafts.count == 1 && drafts[0].memories[a]?.text == "Draft A", "No second draft save can fail after history commits")
    }

    @MainActor static func reopenWithoutSwitching() {
        let id = UUID().uuidString
        var writes = 0
        let controller = ChatController(command: ["/usr/bin/false", "chat", id, "--json"],
            persistState: { _ in writes += 1; throw StorageFailure.unavailable })
        controller.contexts = [context(id)]
        controller.showingTasks = true
        controller.collapsed = true
        controller.inputText = "Keep this draft"
        controller.openContext(id)
        check(controller.display == .panel && !controller.collapsed && controller.stacks.contains(id),
              "Reopening the same listed context must work even when draft storage is unavailable")
        check(writes == 0 && controller.inputText == "Keep this draft", "Reopening cannot add unnecessary writes")
    }

    static func snapshot(_ id: String) -> String {
        """
        {"version":1,"session_id":"\(id)","title":"Fresh","status":"fresh","usage":"","messages":[],"reply_hint":"","input_enabled":true,"checkpoint_id":"gate","label":"Local","contexts":[{"session_id":"\(id)","label":"Local","status":"waiting","needs_input":true,"event_count":2,"queued_inputs":0,"finished":false}],"claude_enabled":true,"agy_enabled":false,"approval":{"checkpoint_id":"gate","kind":"apply","brief":"Public fixture","details":"Public fixture","response_pending":false,"response_decision":null}}
        """
    }

    @MainActor static func refreshFailure(_ directory: URL) async throws {
        let id = UUID().uuidString, requestID = UUID().uuidString
        let request = directory.appendingPathComponent("request.json")
        try Data("""
        {"version":1,"request_id":"\(requestID)","session_id":"\(id)","display":"panel","tokens":{},"show_tasks":false}
        """.utf8).write(to: request)
        setenv("DORO_CHAT_REQUEST", request.path, 1)
        let data = directory.appendingPathComponent("snapshot.json")
        try Data(snapshot(id).utf8).write(to: data)
        let reader = directory.appendingPathComponent("read.py")
        try Data("from pathlib import Path\nimport sys\nsys.stdout.write(Path(sys.argv[1]).read_text())\n".utf8).write(to: reader)
        var failHistory = true
        var saved: StackHistorySnapshot?
        let controller = ChatController(command: ["/usr/bin/python3", reader.path, data.path, "chat", id, "--json"],
            history: StackHistorySnapshot(removed: [id]), saveHistory: { state in
                if failHistory { throw StorageFailure.unavailable }
                saved = state
            })
        controller.appliedRequestID = requestID
        controller.display = .panel
        controller.showingTasks = true
        controller.refresh()
        try await waitFor { controller.conversation != nil || !controller.readError.isEmpty }
        check(controller.conversation?.status == "fresh" && controller.conversation?.approval?.checkpoint_id == "gate",
              "A history write failure must not block the fresh transcript or approval")
        check(controller.approvalCount == 1 && controller.readError.isEmpty && !controller.controlError.isEmpty,
              "History persistence and transcript read errors must remain distinct")
        check(controller.stacks.removed == [id] && saved == nil, "A failed history write must not be reported as saved")
        controller.inputText = "Draft save still works"
        check(controller.saveMemory() && !controller.controlError.isEmpty, "Draft autosave cannot clear the history error")
        failHistory = false
        controller.refresh()
        try await waitFor { saved != nil }
        check(controller.stacks.contains(id) && controller.controlError.isEmpty && saved?.removed.isEmpty == true,
              "A later successful refresh retries persistence and clears only its own error")
    }

    @MainActor static func waitFor(_ condition: () -> Bool) async throws {
        let deadline = ContinuousClock.now.advanced(by: .seconds(5))
        while !condition() && ContinuousClock.now < deadline { try await Task.sleep(for: .milliseconds(20)) }
        check(condition(), "Local fixture did not complete")
    }

    @MainActor static func main() async throws {
        transitionFailures()
        transitionSuccess()
        reopenWithoutSwitching()
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: false)
        defer { try? FileManager.default.removeItem(at: directory) }
        try await refreshFailure(directory)
        print("Persistence boundary checks passed: failed/successful navigation, one draft save, fresh approval, error isolation and recovery")
    }
}
