import Foundation

struct SubmissionKey: Codable, Hashable {
    let text: String
    let checkpoint: String
    let decision: ApprovalDecision?
}

struct SubmissionLedger: Codable {
    private var attempts: [SubmissionKey: String] = [:]

    mutating func begin(_ key: SubmissionKey) -> String {
        if let existing = attempts[key] { return existing }
        let id = UUID().uuidString.lowercased()
        attempts[key] = id
        return id
    }

    mutating func confirmed(_ id: String) {
        attempts = attempts.filter { $0.value != id }
    }

    func contains(_ id: String) -> Bool { attempts.values.contains(id) }
    var isEmpty: Bool { attempts.isEmpty }

    func validate() throws {
        guard Set(attempts.values).count == attempts.count,
              attempts.allSatisfy({ key, id in UUID(uuidString: id) != nil && key.text.utf8.count <= 20_000
                  && (key.checkpoint.isEmpty || UUID(uuidString: key.checkpoint) != nil) }) else {
            throw ChatReadError.failed("전송 기록 형식이 올바르지 않도로.")
        }
    }
}
