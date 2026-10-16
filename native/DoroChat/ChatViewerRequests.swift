import Foundation

@MainActor
extension ChatController {
    func applyRequest() throws { try applyViewerRequest(readViewerRequest()) }

    func applyViewerRequest(_ request: ViewerRequest) throws {
        guard request.request_id != appliedRequestID else { return }
        if request.display == .stop {
            guard canQuit else { return }
            guard prepareToStop() else { throw ChatReadError.failed(storageError) }
            try acknowledgeViewerRequest(request)
            appliedRequestID = request.request_id
            onStop?()
            return
        }
        if let intent = request.intent, intent != .open {
            capabilities = request.tokens
            display = .hidden
            approvals.dismiss()
            if intent == .minimize { collapsed = true }
            onDisplay?(display)
            try acknowledgeViewerRequest(request)
            appliedRequestID = request.request_id
            return
        }
        guard request.tokens[request.session_id] != nil else {
            throw ChatReadError.failed("등록된 작업 연결이 없도로. 작업 목록을 다시 열어줘도로.")
        }
        capabilities = request.tokens
        let target = request.show_tasks == true && request.tokens[selectedSession] != nil ? selectedSession : request.session_id
        guard switchSession(target) else { throw ChatReadError.failed(storageError) }
        if request.show_tasks != true { stacks.open(target) }
        showingTasks = request.show_tasks ?? false
        display = request.display
        approvals.dismiss()
        collapsed = false
        onDisplay?(display)
        try acknowledgeViewerRequest(request)
        appliedRequestID = request.request_id
    }
}
