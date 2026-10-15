import Combine
import Foundation

@MainActor
final class ChatController: ObservableObject {
    @Published var conversation: Conversation?
    @Published var contexts: [ChatContext] = []
    @Published var selectedSession: String
    @Published var display = ViewerDisplay.hidden
    @Published var readError = ""
    @Published var followLatest = true
    @Published var expandedMessages: Set<String> = []
    @Published var scrollTarget: String?
    private(set) var requestedScrollTarget: String?
    @Published var collapsed = false {
        didSet { if collapsed { approvals.dismiss() }; onCollapse?(collapsed) }
    }
    @Published var stacks = StackCatalog()
    @Published var showingTasks = false
    @Published var approvals = ApprovalPresentation() {
        didSet {
            if oldValue.seen != approvals.seen {
                UserDefaults(suiteName: "local.doro.approvals")?.set(Array(approvals.seen), forKey: "seen")
            }
            onApprovalChange?()
        }
    }
    var requestedApprovalSession: String?
    var onApprovalChange: (() -> Void)?
    var onApprovalOpen: (() -> Void)?
    @Published var inputText = ""
    @Published var inputStatus = "입력은 이 스택에만 전달되도로."
    @Published private var sendingSessions: Set<String> = []
    @Published private var seen: [String: Int] = [:]
    var onCollapse: ((Bool) -> Void)?
    var onDisplay: ((ViewerDisplay) -> Void)?
    var onStop: (() -> Void)?
    var onStackLayout: (() -> Void)?
    private let command: [String]
    private var memories: [String: ContextMemory] = [:]
    private var snapshots: [String: Conversation] = [:]
    private var capabilities: [String: String] = [:]
    private var timer: Timer?
    private var loading = false
    private var requestID = ""
    private var generation = 0
    var sending: Bool { sendingSessions.contains(selectedSession) }
    var approvalCount: Int { contexts.filter(\.needs_input).count }
    var currentLabel: String { contexts.first { $0.id == selectedSession }?.label ?? "도로 협업" }

    init(command: [String]) {
        self.command = command
        selectedSession = command[command.count - 2]
        approvals = ApprovalPresentation(seen: Set(UserDefaults(suiteName: "local.doro.approvals")?.stringArray(forKey: "seen") ?? []))
    }

    func start() {
        refresh()
        let poll = Timer(timeInterval: 0.75, repeats: true) { [weak self] _ in
            Task { @MainActor [weak self] in self?.refresh() }
        }
        timer = poll
        RunLoop.main.add(poll, forMode: .common)
    }

    func stop() { timer?.invalidate(); timer = nil }
    func unread(_ context: ChatContext) -> Int { max(0, context.event_count - (seen[context.id] ?? context.event_count)) }

    func selectContext(_ id: String) {
        guard id != selectedSession, contexts.contains(where: { $0.id == id }) else { return }
        saveMemory()
        approvals.dismiss()
        selectedSession = id
        generation += 1
        let memory = memories[id] ?? ContextMemory()
        inputText = memory.text
        inputStatus = memory.status
        expandedMessages = memory.expanded
        scrollTarget = memory.scrollTarget
        requestedScrollTarget = memory.scrollTarget
        followLatest = memory.scrollTarget == nil
        conversation = snapshots[id]
        readError = ""
        refresh()
    }

    private func saveMemory() {
        var memory = memories[selectedSession] ?? ContextMemory()
        memory.text = inputText
        memory.status = inputStatus
        memory.expanded = expandedMessages
        memory.scrollTarget = scrollTarget
        memories[selectedSession] = memory
    }

    private func applyRequest() throws {
        let request = try readViewerRequest()
        guard request.request_id != requestID else { return }
        if request.display == .stop && !sendingSessions.isEmpty { return }
        requestID = request.request_id
        capabilities = request.tokens
        if request.display == .integrated || request.display == .panel {
            stacks.open(request.session_id)
            showingTasks = false
        }
        if request.session_id != selectedSession {
            saveMemory()
            selectedSession = request.session_id
            generation += 1
            let memory = memories[selectedSession] ?? ContextMemory()
            inputText = memory.text
            inputStatus = memory.status
            expandedMessages = memory.expanded
            scrollTarget = memory.scrollTarget
            requestedScrollTarget = memory.scrollTarget
            followLatest = memory.scrollTarget == nil
            conversation = snapshots[selectedSession]
        }
        display = request.display
        approvals.dismiss()
        collapsed = false
        onDisplay?(display)
        try acknowledgeViewerRequest(request)
        if display == .stop { onStop?() }
    }

    func refresh() {
        do { try applyRequest() }
        catch { readError = "연결 갱신 실패: \(error.localizedDescription)"; return }
        guard !loading, display != .hidden, display != .stop else { return }
        loading = true
        let id = selectedSession
        let epoch = generation
        let source = sessionCommand(id)
        Task {
            defer { loading = false; if selectedSession != id { refresh() } }
            do {
                let value = try await Task.detached { try readConversation(source) }.value
                snapshots[id] = value
                if contexts.isEmpty { for item in value.contexts { seen[item.id] = item.event_count } }
                contexts = value.contexts
                synchronizeStacks(value.contexts)
                guard selectedSession == id, epoch == generation else { return }
                conversation = value
                synchronizeApproval(value)
                if !collapsed { seen[id] = contexts.first { $0.id == id }?.event_count ?? 0 }
                readError = ""
            } catch {
                if requestedApprovalSession == id { requestedApprovalSession = nil }
                if selectedSession == id { readError = "대화 갱신 실패: \(error.localizedDescription)" }
            }
        }
    }

    private func sessionCommand(_ id: String) -> [String] { Array(command.dropLast(2)) + [id, "--json"] }

    func submitInput() {
        submit(session: selectedSession, text: inputText, checkpoint: conversation?.checkpoint_id ?? "", decision: nil)
    }

    func changeModel(_ model: String, effort: String, session: String) async throws {
        guard let token = capabilities[session] else { throw ChatReadError.failed("스택 연결을 다시 열어줘도로.") }
        let command = Array(sessionCommand(session).dropLast()) + ["--set-model"]
        let data = try JSONSerialization.data(withJSONObject: ["model": model, "effort": effort])
        _ = try await Task.detached { try localCommand(command, input: data, capability: token) }.value
        refresh()
    }

    func submit(session: String, text: String, checkpoint: String, decision: ApprovalDecision?) {
        guard !sending, let view = conversation, view.session_id == session, selectedSession == session, view.input_enabled,
              !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
            inputStatus = "전달 확인 실패: 전송 중이거나 이 작업의 입력 연결이 바뀌었도로. 내용을 보존했도로."
            refresh(); return
        }
        guard let token = capabilities[selectedSession] else {
            inputStatus = "스택 연결을 새로 열어줘도로. 입력 내용은 보존돼 있도로."; return
        }
        saveMemory()
        let id = session
        var memory = memories[id] ?? ContextMemory()
        let clientID = memory.submissions.begin(SubmissionKey(text: text, checkpoint: checkpoint, decision: decision))
        memories[id] = memory
        let source = sessionCommand(id)
        sendingSessions.insert(id)
        Task {
            defer { sendingSessions.remove(id) }
            do {
                try await Task.detached {
                    try postInput(source, text: text, checkpoint: checkpoint, id: clientID, decision: decision?.rawValue ?? "", token: token)
                }.value
                recordSent(id: id, clientID: clientID, text: text, decision: decision)
                if let decision { approvals.markSent(session: id, checkpoint: checkpoint, decision: decision) }
                refresh()
            } catch {
                let status = "전달 확인 실패: \(error.localizedDescription) · 입력은 보존했도로."
                var saved = memories[id] ?? ContextMemory()
                saved.status = status
                memories[id] = saved
                if selectedSession == id { inputStatus = status }
                refresh()
            }
        }
    }

    private func recordSent(id: String, clientID: String, text: String, decision: ApprovalDecision?) {
        var saved = memories[id] ?? ContextMemory()
        if decision == nil && saved.text == text { saved.text = "" }
        saved.status = "Work 수신 대기 · 외부 모델 자동 전달 없음"
        saved.submissions.confirmed(clientID)
        memories[id] = saved
        if selectedSession == id {
            if decision == nil { followLatest = true }
            if decision == nil && inputText == text { inputText = "" }
            inputStatus = saved.status
        }
    }

}
