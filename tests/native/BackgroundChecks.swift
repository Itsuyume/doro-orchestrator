import Foundation

@main
struct BackgroundChecks {
    @MainActor static func waitFor(_ condition: () -> Bool) async throws {
        let deadline = ContinuousClock.now.advanced(by: .seconds(6))
        while !condition() && ContinuousClock.now < deadline { try await Task.sleep(for: .milliseconds(30)) }
        precondition(condition(), "Background condition did not complete")
    }

    static func writeSnapshot(_ path: URL, id: String, approval: Bool) throws {
        let packet: [String: Any] = ["version": 1, "contexts": [["session_id": id, "label": "Local task", "status": "waiting",
            "needs_input": approval, "event_count": approval ? 2 : 1, "queued_inputs": 0, "finished": false]]]
        try JSONSerialization.data(withJSONObject: packet).write(to: path, options: .atomic)
    }

    @MainActor static func main() async throws {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: false)
        defer { try? FileManager.default.removeItem(at: directory) }
        let snapshot = directory.appendingPathComponent("snapshot.json")
        let calls = directory.appendingPathComponent("calls.txt")
        let script = directory.appendingPathComponent("reader.py")
        try Data("""
        import sys
        from pathlib import Path
        if sys.argv[-1] != '--contexts-json': raise SystemExit(17)
        with open(sys.argv[2], 'a') as log: log.write(sys.argv[-1] + '\\n')
        sys.stdout.write(Path(sys.argv[1]).read_text())
        """.utf8).write(to: script)
        let id = UUID().uuidString.lowercased()
        let request = directory.appendingPathComponent("request.json")
        setenv("DORO_CHAT_REQUEST", request.path, 1)
        try JSONSerialization.data(withJSONObject: ["version": 1, "request_id": UUID().uuidString,
            "session_id": id, "display": "hidden", "tokens": [id: "fixture"], "intent": "hide"]).write(to: request)
        try writeSnapshot(snapshot, id: id, approval: false)
        let store = ContextStateStore(file: NativeStateFile(path: directory.appendingPathComponent("absent/state.json"), maxBytes: 2000))
        let controller = ChatController(command: ["/usr/bin/python3", script.path, snapshot.path, calls.path, "chat", id, "--json"],
                                        persistState: store.save)
        var shows = 0
        controller.onDisplay = { if $0 != .hidden { shows += 1 } }
        var updates = 0
        controller.onApprovalChange = { updates += 1 }
        controller.start()
        defer { controller.stop() }
        try await waitFor { controller.contexts.count == 1 }
        precondition(controller.approvalCount == 0 && controller.conversation == nil && controller.display == .hidden)
        try writeSnapshot(snapshot, id: id, approval: true)
        try await waitFor { controller.approvalCount == 1 }
        precondition(shows == 0 && updates >= 2 && controller.display == .hidden,
                     "Background approval updates cannot open the panel or an approval dialog")
        controller.inputText = "Unsaved local text"
        try JSONSerialization.data(withJSONObject: ["version": 1, "request_id": UUID().uuidString,
            "session_id": id, "display": "stop", "tokens": [id: "fixture"]]).write(to: request, options: .atomic)
        try writeSnapshot(snapshot, id: id, approval: false)
        try await waitFor { controller.approvalCount == 0 }
        precondition(!controller.requestError.isEmpty && controller.inputText == "Unsaved local text",
                     "A failed stop cannot suspend background reads or lose unsaved input")
        let reads = try String(contentsOf: calls, encoding: .utf8).split(separator: "\n")
        precondition(reads.count >= 3 && reads.count <= 4, "Hidden polling must be throttled")
        precondition(reads.allSatisfy { $0 == "--contexts-json" }, "Hidden reads cannot fetch transcript bodies")
        print("Background checks passed: metadata-only hidden refresh, approval badge updates, no popup, bounded polling")
    }
}
