import Foundation

@main
struct HistoryChecks {
    static func context(_ id: String, finished: Bool = true, approval: Bool = false, queued: Int = 0) -> ChatContext {
        ChatContext(session_id: id, label: id, status: "test", needs_input: approval,
                    event_count: 1, queued_inputs: queued, finished: finished)
    }

    @MainActor static func main() throws {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: false)
        defer { try? FileManager.default.removeItem(at: directory) }
        let store = StackHistoryStore(path: directory.appendingPathComponent("history.json"))
        let a = UUID().uuidString, b = UUID().uuidString, active = UUID().uuidString, pending = UUID().uuidString
        let values = [context(a), context(b), context(active, finished: false), context(pending, approval: true)]
        let controller = ChatController(command: ["/usr/bin/false", "chat", active, "--json"], saveHistory: store.save)
        controller.contexts = values
        try controller.synchronizeStacks(values)
        controller.closeStack(active)
        controller.closeStack(pending)
        controller.removeHistory([a, active, pending])
        precondition(!controller.stacks.isListed(a) && controller.stacks.isListed(active) && controller.stacks.isListed(pending))
        try controller.synchronizeStacks([])
        try controller.synchronizeStacks(values)
        precondition(!controller.stacks.isListed(a), "Polling cannot resurrect removed history")
        let reloaded = try store.load()
        precondition(reloaded.removed == [a] && reloaded.undo == [a], "Removal and undo survive reopening")
        controller.removeHistory([b])
        controller.undoHistoryRemoval()
        precondition(!controller.stacks.isListed(a) && controller.stacks.isListed(b), "Undo restores only the latest batch")
        controller.removeHistory([b])
        controller.openContext(b)
        precondition(controller.lastRemoved.isEmpty && !controller.stacks.removed.contains(b))
        let attention = [context(a, finished: false, approval: true), context(b)]
        controller.contexts = attention
        try controller.synchronizeStacks(attention)
        precondition(controller.stacks.contains(a) && controller.approvalCount == 1, "A new approval restores its task")
        let restored = try store.load()
        precondition(restored.removed.isEmpty)

        let failingStore = StackHistoryStore(path: directory.appendingPathComponent("missing/history.json"))
        let failing = ChatController(command: ["/usr/bin/false", "chat", active, "--json"], saveHistory: failingStore.save)
        failing.contexts = [context(a)]
        failing.removeHistory([a])
        precondition(failing.stacks.isListed(a) && !failing.readError.isEmpty, "Failed persistence cannot hide a task")
        try Data("broken".utf8).write(to: store.path)
        do { _ = try store.load(); preconditionFailure("Corrupt history must fail visibly") }
        catch { precondition(error is DecodingError) }
        let corrupt = try Data(contentsOf: store.path)
        precondition(corrupt == Data("broken".utf8))
        do { try store.save(StackHistorySnapshot(removed: ["invalid"])); preconditionFailure("Invalid IDs must not be written") }
        catch { precondition(error is ChatReadError) }
        let preserved = try Data(contentsOf: store.path)
        precondition(preserved == corrupt)
        precondition(taskListHeight(content: -1) == 200 && taskListHeight(content: 0) == 200)
        precondition(taskListHeight(content: 200) == 285 && taskListHeight(content: 10000) == 620)
        print("History checks passed: single/batch removal, restart, undo, new approval, write failure, corruption and size bounds")
    }
}
