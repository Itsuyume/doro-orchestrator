import Foundation

struct StackHistoryStore {
    let path: URL

    func load() throws -> StackHistorySnapshot {
        guard let data = try NativeStateFile(path: path, maxBytes: 200_000).read() else { return StackHistorySnapshot() }
        let value = try JSONDecoder().decode(StackHistorySnapshot.self, from: data)
        try validateSnapshot(value)
        return value
    }

    func save(_ history: StackHistorySnapshot) throws {
        try validateSnapshot(history)
        let data = try JSONEncoder().encode(history)
        try NativeStateFile(path: path, maxBytes: 200_000).write(data)
    }

    private func validateSnapshot(_ value: StackHistorySnapshot) throws {
        let ids = value.removed.union(value.undo)
        guard ids.count <= 5000, ids.allSatisfy({ UUID(uuidString: $0) != nil }), value.undo.isSubset(of: value.removed) else {
            throw ChatReadError.failed("목록 저장 형식을 확인해줘도로.")
        }
    }

}
