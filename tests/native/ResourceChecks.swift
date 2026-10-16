import Foundation

@main
struct ResourceChecks {
    static func main() throws {
        checkRefreshPolicy()
        try checkRevisionBoundary()
        try checkCacheBound()
        try checkCommandDeadline()
        print("Resource checks passed: unchanged reads skipped, change latency, forced refresh, failure retry, file boundaries, bounded transcript cache")
    }

    static func checkRefreshPolicy() {
        var gate = RefreshPolicy()
        let initial = ["db-1"]
        precondition(gate.shouldRead(now: 0, revision: initial, background: false, force: false))
        gate.complete(revision: initial)
        var reads = 0
        for tick in 1...400 {
            if gate.shouldRead(now: Double(tick) * 0.75, revision: initial, background: false, force: false) {
                reads += 1
                gate.complete(revision: initial)
            }
        }
        precondition(reads == 10, "Five unchanged minutes need 10 safety reads, not 400 full CLI launches")
        precondition(gate.shouldRead(now: 301, revision: ["db-2"], background: false, force: false))
        gate.complete(revision: ["db-2"])
        precondition(gate.shouldRead(now: 301.01, revision: ["db-2"], background: false, force: true),
                     "Explicit open, send and model-save refreshes never wait for a poll")
        precondition(!gate.shouldRead(now: 301.8, revision: ["db-3"], background: false, force: false))
        precondition(gate.shouldRead(now: 304.01, revision: ["db-3"], background: false, force: false),
                     "Failed reads retry without a tight process loop")
        gate.complete(revision: ["db-3"])
        precondition(!gate.shouldRead(now: 305, revision: ["db-4"], background: true, force: false))
        precondition(gate.shouldRead(now: 307.1, revision: ["db-4"], background: true, force: false))
    }

    static func checkRevisionBoundary() throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        let native = root.appendingPathComponent("native")
        try FileManager.default.createDirectory(at: native, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: root) }
        setenv("DORO_CHAT_REQUEST", native.appendingPathComponent("viewer-request.json").path, 1)
        let database = root.appendingPathComponent("sessions.sqlite3")
        let config = root.appendingPathComponent("config.toml")
        let command = ["python3", "doro", "--config", config.path, "chat", "A", "--json"]
        let absent = try conversationRevision(command)
        precondition(absent == nil, "Unknown layouts keep the existing bounded polling behavior")
        try Data("db".utf8).write(to: database)
        try Data("config".utf8).write(to: config)
        let original = try conversationRevision(command)
        try Data("private draft".utf8).write(to: native.appendingPathComponent("context-state.json"))
        let draftOnly = try conversationRevision(command)
        precondition(draftOnly == original, "Draft autosave cannot trigger an endless refresh loop")
        let wal = root.appendingPathComponent("sessions.sqlite3-wal")
        try Data("commit".utf8).write(to: wal)
        let changed = try conversationRevision(command)
        precondition(changed != original, "WAL commits must be detected before checkpointing the main DB")
        try FileManager.default.removeItem(at: wal)
        let checkpointed = try conversationRevision(command)
        precondition(checkpointed == original, "WAL removal/checkpointing is observable")
        try Data("new config".utf8).write(to: config)
        let configured = try conversationRevision(command)
        precondition(configured != original, "Settings changes cannot leave stale provider state")
    }

    static func checkCacheBound() throws {
        var cache = ConversationCache()
        for index in 0..<500 {
            let id = "session-\(index)"
            let data = Data("""
            {"version":1,"session_id":"\(id)","title":"Fixture","status":"completed","usage":"","messages":[],"reply_hint":"","input_enabled":true,"checkpoint_id":"","label":"Fixture","contexts":[],"claude_enabled":true,"agy_enabled":false}
            """.utf8)
            cache[id] = try JSONDecoder().decode(Conversation.self, from: data)
            precondition(cache.count <= 3)
        }
        precondition(cache["session-0"] == nil && cache["session-499"] != nil)
        cache["session-499"] = nil
        precondition(cache.count == 2)
    }

    static func checkCommandDeadline() throws {
        let clock = ContinuousClock()
        let start = clock.now
        do {
            _ = try localCommand(["/usr/bin/python3", "-c",
                "import signal,sys,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); sys.stderr.write('x'*100000); sys.stderr.flush(); time.sleep(20)"], timeout: 0.2)
            preconditionFailure("A stuck local helper must not keep settings permanently busy")
        } catch {
            precondition(error is ChatReadError && start.duration(to: clock.now) < .seconds(3))
        }
        let output = try localCommand(["/usr/bin/printf", "ready"], timeout: 1)
        precondition(output == Data("ready".utf8), "A timed-out helper cannot break the next normal command")
    }
}
