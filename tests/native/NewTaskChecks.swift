import AppKit

@main struct NewTaskChecks {
    @MainActor static func main() throws {
        let source = UUID().uuidString.lowercased()
        let request = UUID().uuidString.lowercased()
        let target = UUID().uuidString.lowercased()
        let thread = UUID().uuidString.lowercased()
        var saved = ContextState()
        let controller = ChatController(command: ["/usr/bin/false", "chat", source, "--json"],
            persistState: { saved = $0 })
        controller.inputText = "Existing task draft"
        controller.beginNewTask()
        precondition(controller.showingNewTask && controller.inputText == "Existing task draft")
        precondition(!controller.canStartNewTask, "Empty fresh-task input cannot be submitted")
        controller.newTask.text = String(repeating: "한", count: 2001)
        precondition(!controller.canStartNewTask, "A not-yet-loaded conversation still enforces the input bound")
        controller.newTask.text = "a\0b"
        precondition(!controller.canStartNewTask)
        controller.newTask.text = "A fresh task"
        precondition(controller.canStartNewTask)
        controller.showTasks()
        precondition(!controller.showingNewTask && controller.newTask.text == "A fresh task")
        controller.saveMemory()
        precondition(saved.newTask?.text == "A fresh task" && saved.memories[source]?.text == "Existing task draft")
        let restored = ChatController(command: ["/usr/bin/false", "chat", source, "--json"], state: saved)
        precondition(restored.newTask.text == "A fresh task" && restored.inputText == "Existing task draft")
        controller.newTask.id = request
        controller.newTask.queued = true
        controller.applyNewTask(record(request, "unknown", target, thread, error: "Outcome unknown"), delivery: nil)
        precondition(!controller.canStartNewTask && controller.newTask.text == "A fresh task",
                     "Unknown creation must preserve the draft and refuse duplicate creation")
        controller.applyNewTask(record(request, "pending", target, thread),
            delivery: NewTaskDelivery(state: "failed", error: "Disconnected"))
        precondition(controller.canStartNewTask && controller.newTask.retryable)
        controller.applyNewTask(record(request, "creating", target, thread), delivery: nil)
        precondition(!controller.canStartNewTask && !controller.newTask.retryable)
        controller.applyNewTask(record(UUID().uuidString, "failed", target, thread), delivery: nil)
        precondition(!controller.newTask.creationFailed, "A stale response cannot modify a new request")
        controller.applyNewTask(record(request, "created", target, thread), delivery: nil)
        precondition(controller.selectedSession == source, "A confirmed UI token is needed before switching")
        controller.showingNewTask = true
        controller.applyNewTask(record(request, "created", target, thread, token: "confirmed-test-capability"), delivery: nil)
        precondition(controller.selectedSession == target && !controller.showingNewTask && !controller.showingTasks)
        precondition(controller.newTask.text.isEmpty && controller.memories[source]?.text == "Existing task draft")
        let waiting = ChatController(command: ["/usr/bin/false", "chat", source, "--json"])
        waiting.newTask = NewTaskDraft(text: "Keep pending", id: request, sourceSession: source, queued: true)
        waiting.showingTasks = true
        waiting.applyNewTask(record(request, "created", target, thread, token: "confirmed-test-capability"), delivery: nil)
        precondition(waiting.selectedSession == source && waiting.readyNewTask != nil,
                     "Late creation cannot take focus from a different task")
        waiting.beginNewTask()
        precondition(waiting.selectedSession == target && waiting.readyNewTask == nil)
        try checkPersistence(source: source, request: request)
        checkSaveFailure(source: source)
        print("New task checks passed: independent drafts, restart, unknown/failed outcomes, stale replies, confirmed switch, save failure")
    }

    static func record(_ id: String, _ state: String, _ session: String, _ thread: String,
                       error: String = "", token: String? = nil) -> NewTaskRecord {
        NewTaskRecord(id: id, state: state, session_id: session, thread_id: thread,
                      error: error, token: token, delivery: nil)
    }

    @MainActor static func checkSaveFailure(source: String) {
        let controller = ChatController(command: ["/usr/bin/false", "chat", source, "--json"],
            persistState: { _ in throw ChatReadError.failed("Disk is full") })
        controller.inputText = "Keep original"
        controller.beginNewTask()
        precondition(!controller.showingNewTask && controller.inputText == "Keep original")
        precondition(!controller.storageError.isEmpty && !controller.newTaskBusy)
    }

    static func checkPersistence(source: String, request: String) throws {
        let legacy = try JSONDecoder().decode(ContextState.self, from: Data("{\"version\":1,\"memories\":{}}".utf8))
        precondition(legacy.newTask == nil, "Existing state files need no migration or draft loss")
        let draft = NewTaskDraft(text: "한글\nA new task", id: request, sourceSession: source, queued: true)
        let state = ContextState(newTask: draft)
        let encoded = try JSONEncoder().encode(state)
        let restored = try JSONDecoder().decode(ContextState.self, from: encoded)
        precondition(restored.newTask?.id == request && restored.newTask?.text == draft.text)
        try restored.newTask?.validate()
        do {
            try NewTaskDraft(queued: true).validate()
            preconditionFailure("A queued request without an identity cannot be restored")
        } catch is ChatReadError { }
    }
}
