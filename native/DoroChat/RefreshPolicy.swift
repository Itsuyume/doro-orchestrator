import Foundation

struct RefreshPolicy {
    private var lastRead = -Double.infinity
    private var revision: [String]?
    private var succeeded = false

    mutating func shouldRead(now: Double, revision next: [String]?, background: Bool, force: Bool) -> Bool {
        let interval = background ? 3.0 : 0.75
        guard force || now - lastRead >= (succeeded ? interval : 3) else { return false }
        guard force || !succeeded || next == nil || next != revision || now - lastRead >= 30 else { return false }
        lastRead = now
        succeeded = false
        return true
    }

    mutating func complete(revision next: [String]?) { revision = next; succeeded = true }
}

func conversationRevision(_ command: [String]) throws -> [String]? {
    guard let request = ProcessInfo.processInfo.environment["DORO_CHAT_REQUEST"] else { return nil }
    let root = URL(fileURLWithPath: request).deletingLastPathComponent().deletingLastPathComponent()
    guard FileManager.default.fileExists(atPath: root.appendingPathComponent("sessions.sqlite3").path) else { return nil }
    var paths = ["sessions.sqlite3", "sessions.sqlite3-wal", "agy/verification.json", "bin/agy"].map { root.appendingPathComponent($0) }
    if let index = command.firstIndex(of: "--config"), command.indices.contains(index + 1) {
        paths.append(URL(fileURLWithPath: command[index + 1]))
    }
    return try paths.map { path in
        do {
            let info = try FileManager.default.attributesOfItem(atPath: path.path)
            return "\(info[.systemFileNumber] ?? 0):\(info[.size] ?? 0):\((info[.modificationDate] as? Date)?.timeIntervalSince1970 ?? 0)"
        } catch CocoaError.fileReadNoSuchFile { return "missing" }
    }
}

struct ConversationCache {
    private var values: [String: Conversation] = [:]
    private var order: [String] = []
    let limit: Int
    init(limit: Int = 3) { precondition(limit > 0); self.limit = limit }
    var count: Int { values.count }

    subscript(id: String) -> Conversation? {
        get { values[id] }
        set {
            order.removeAll { $0 == id }
            values[id] = newValue
            if newValue != nil { order.append(id) }
            while order.count > limit { values.removeValue(forKey: order.removeFirst()) }
        }
    }
}
