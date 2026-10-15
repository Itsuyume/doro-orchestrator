import Foundation

@main
struct SubmissionChecks {
    static func main() {
        let chat = SubmissionKey(text: "Question", checkpoint: "gate", decision: nil)
        let approval = SubmissionKey(text: "Approve", checkpoint: "gate", decision: .approve)
        let hold = SubmissionKey(text: "Hold", checkpoint: "gate", decision: .reject)
        var ledger = SubmissionLedger()
        let chatID = ledger.begin(chat), approvalID = ledger.begin(approval)
        let holdID = ledger.begin(hold)
        precondition(Set([chatID, approvalID, holdID]).count == 3)
        precondition(ledger.begin(chat) == chatID, "An ambiguous chat failure retains its UUID across approval attempts")
        precondition(ledger.begin(approval) == approvalID, "Changing a decision cannot erase an ambiguous original attempt")
        ledger.confirmed(approvalID)
        precondition(ledger.begin(chat) == chatID, "Confirming approval cannot reset unrelated chat")
        ledger.confirmed(chatID)
        precondition(ledger.begin(chat) != chatID, "An intentionally repeated, confirmed message gets a new ID")
        let newGate = SubmissionKey(text: "Approve", checkpoint: "new-gate", decision: .approve)
        precondition(ledger.begin(newGate) != approvalID, "A new question is a distinct submission")
        print("Submission checks passed: ambiguous failure, independent messages, decisions, confirmation, new question")
    }
}
