import Foundation

@main
struct StackChecks {
    static func main() {
        let running = ChatContext(session_id: "work-A", label: "작업 A", status: "진행 중", needs_input: false,
                                  event_count: 3, queued_inputs: 0, finished: false)
        let waiting = ChatContext(session_id: "work-B", label: "작업 B", status: "승인 대기", needs_input: true,
                                  event_count: 2, queued_inputs: 0, finished: false)
        let old = ChatContext(session_id: "old", label: "지난 검증", status: "완료", needs_input: false,
                              event_count: 5, queued_inputs: 0, finished: true)
        var catalog = StackCatalog()
        catalog.synchronize([], selected: "none")
        precondition(!catalog.contains("none"))
        catalog.synchronize([running, waiting, old], selected: running.id)
        precondition(catalog.contains(running.id) && catalog.contains(waiting.id))
        precondition(!catalog.contains(old.id), "Completed validation sessions must stay out of the open stack")
        catalog.close(waiting.id)
        catalog.synchronize([running, waiting, old], selected: running.id)
        precondition(!catalog.contains(waiting.id), "Polling must not reopen a user-closed conversation")
        precondition(waiting.needs_input, "Closing a display must preserve its approval question")
        catalog.open(waiting.id)
        precondition(catalog.contains(waiting.id))
        catalog.close(running.id)
        precondition(catalog.contains(waiting.id), "Closing one stack cannot close another")
        catalog.synchronize([old], selected: old.id)
        precondition(!catalog.contains(running.id) && !catalog.contains(waiting.id))
        catalog.open(old.id)
        precondition(catalog.contains(old.id), "History can be opened explicitly without a model call")
        print("Native stack checks passed: empty, live/history, close/reopen, approval preserved, removal")
    }
}
