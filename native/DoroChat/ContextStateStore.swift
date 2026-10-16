import Foundation

struct ContextState: Codable {
    var version = 1
    var selectedSession: String?
    var memories: [String: ContextMemory] = [:]
}

struct ContextStateStore {
    let file: NativeStateFile

    func load() throws -> ContextState {
        guard let data = try file.read() else { return ContextState() }
        let state = try JSONDecoder().decode(ContextState.self, from: data)
        try validate(state)
        return state
    }

    func save(_ state: ContextState) throws {
        try validate(state)
        try file.write(JSONEncoder().encode(state))
    }

    private func validate(_ state: ContextState) throws {
        guard state.version == 1, state.memories.count <= 5000,
              state.selectedSession.map({ UUID(uuidString: $0) != nil }) ?? true else {
            throw ChatReadError.failed("초안 저장 형식을 확인해줘도로.")
        }
        for (id, memory) in state.memories {
            guard UUID(uuidString: id) != nil, memory.text.utf8.count <= 200_000,
                  memory.status.utf8.count <= 20_000, memory.expanded.count <= 5000,
                  memory.expanded.allSatisfy({ $0.utf8.count <= 128 }),
                  (memory.scrollTarget?.utf8.count ?? 0) <= 128,
                  memory.lastInputID.map({ UUID(uuidString: $0) != nil }) ?? true else {
                throw ChatReadError.failed("저장된 작업 초안이 올바르지 않도로.")
            }
            try memory.submissions.validate()
        }
    }
}
