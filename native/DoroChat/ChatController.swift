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
    @Published var showingTasks = false { didSet { onStackLayout?() } }
    @Published var historyExpanded = false { didSet { onStackLayout?() } }
    @Published var lastRemoved: Set<String> = []
    @Published var taskContentHeight = 0.0 { didSet { if abs(oldValue - taskContentHeight) > 1 { onStackLayout?() } } }
    let saveHistory: (StackHistorySnapshot) throws -> Void
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
    @Published var inputStatus = ""
    @Published var sendingSessions: Set<String> = []
    @Published private var seen: [String: Int] = [:]
    var onCollapse: ((Bool) -> Void)?
    var onDisplay: ((ViewerDisplay) -> Void)?
    var onStop: (() -> Void)?
    var onStackLayout: (() -> Void)?
    private let command: [String]
    var memories: [String: ContextMemory] = [:]
    private var snapshots: [String: Conversation] = [:]
    var capabilities: [String: String] = [:]
    private var timer: Timer?
    private var loading = false
    private var requestID = ""
    private var generation = 0
    var sending: Bool { sendingSessions.contains(selectedSession) }
    var approvalCount: Int { contexts.filter(\.needs_input).count }
    var currentLabel: String { contexts.first { $0.id == selectedSession }?.label ?? "도로 협업" }

    init(command: [String], history: StackHistorySnapshot = StackHistorySnapshot(),
         saveHistory: @escaping (StackHistorySnapshot) throws -> Void = { _ in }) {
        self.command = command
        self.saveHistory = saveHistory
        stacks = StackCatalog(removed: history.removed)
        lastRemoved = history.undo
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

    func saveMemory() {
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
            if request.show_tasks != true { stacks.open(request.session_id) }
            showingTasks = request.show_tasks ?? false
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
                try synchronizeStacks(value.contexts)
                guard selectedSession == id, epoch == generation else { return }
                conversation = value
                synchronizeInputStatus(value)
                synchronizeApproval(value)
                if !collapsed { seen[id] = contexts.first { $0.id == id }?.event_count ?? 0 }
                readError = ""
            } catch {
                if requestedApprovalSession == id { requestedApprovalSession = nil }
                if selectedSession == id { readError = "대화 갱신 실패: \(error.localizedDescription)" }
            }
        }
    }

    func sessionCommand(_ id: String) -> [String] { Array(command.dropLast(2)) + [id, "--json"] }

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

}
