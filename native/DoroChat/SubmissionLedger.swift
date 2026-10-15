import Foundation

struct SubmissionKey: Hashable {
    let text: String
    let checkpoint: String
    let decision: ApprovalDecision?
}

struct SubmissionLedger {
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
}
