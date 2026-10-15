import Foundation

struct StackHistoryStore {
    let path: URL

    func load() throws -> StackHistorySnapshot {
        guard FileManager.default.fileExists(atPath: path.path) else { return StackHistorySnapshot() }
        try validateFile()
        let value = try JSONDecoder().decode(StackHistorySnapshot.self, from: Data(contentsOf: path))
        try validateSnapshot(value)
        return value
    }

    func save(_ history: StackHistorySnapshot) throws {
        try validateSnapshot(history)
        if FileManager.default.fileExists(atPath: path.path) { try validateFile() }
        let data = try JSONEncoder().encode(history)
        guard data.count <= 200_000 else { throw ChatReadError.failed("목록 저장 크기를 초과했도로.") }
        try data.write(to: path, options: .atomic)
        try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: path.path)
    }

    private func validateSnapshot(_ value: StackHistorySnapshot) throws {
        let ids = value.removed.union(value.undo)
        guard ids.count <= 5000, ids.allSatisfy({ UUID(uuidString: $0) != nil }), value.undo.isSubset(of: value.removed) else {
            throw ChatReadError.failed("목록 저장 형식을 확인해줘도로.")
        }
    }

    private func validateFile() throws {
        let attributes = try FileManager.default.attributesOfItem(atPath: path.path)
        guard attributes[.type] as? FileAttributeType == .typeRegular,
              let size = attributes[.size] as? NSNumber, size.intValue <= 200_000 else {
            throw ChatReadError.failed("목록 저장 파일이 일반 파일이 아니거나 너무 크도로.")
        }
    }
}
