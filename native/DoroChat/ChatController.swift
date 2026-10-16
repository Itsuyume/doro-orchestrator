import Combine
import Foundation

@MainActor
final class ChatController: ObservableObject {
    @Published var conversation: Conversation?
    @Published var contexts: [ChatContext] = []
    @Published var selectedSession: String
    @Published var display = ViewerDisplay.hidden
    @Published var readError = ""
    @Published var shortcutError = ""
    @Published var placementError = ""
    @Published var storageError = ""
    @Published var historyError = ""
    @Published var requestError = ""
    var controlError: String { [shortcutError, placementError, storageError, historyError, requestError].filter { !$0.isEmpty }.joined(separator: "\n") }
    @Published var followLatest = true
    @Published var expandedMessages: Set<String> = [] { didSet { scheduleStateSave() } }
    @Published var scrollTarget: String? { didSet { scheduleStateSave() } }
    @Published var collapsed = false {
        didSet {
            guard oldValue != collapsed else { return }
            if collapsed { approvals.dismiss() }
            onCollapse?(collapsed)
        }
    }
    @Published var stacks = StackCatalog()
    @Published var showingTasks = false { didSet { if oldValue != showingTasks { onStackLayout?() } } }
    @Published var openTasksExpanded = true
    @Published var historyExpanded = false { didSet { if oldValue != historyExpanded { onStackLayout?() } } }
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
    @Published var inputText = "" { didSet { scheduleStateSave() } }
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
    var appliedRequestID = ""
    private var generation = 0
    var saveGeneration = 0
    private var lastBackgroundRead = -Double.infinity
    let persistState: (ContextState) throws -> Void
    let recoverPersistence: ((ContextState) throws -> Void)?
    var sending: Bool { sendingSessions.contains(selectedSession) }
    var canQuit: Bool { sendingSessions.isEmpty }
    var approvalCount: Int { contexts.filter(\.needs_input).count }
    var currentLabel: String { contexts.first { $0.id == selectedSession }?.label ?? "도로 협업" }

    init(command: [String], history: StackHistorySnapshot = StackHistorySnapshot(),
         saveHistory: @escaping (StackHistorySnapshot) throws -> Void = { _ in },
         state: ContextState = ContextState(), persistState: @escaping (ContextState) throws -> Void = { _ in },
         recoverPersistence: ((ContextState) throws -> Void)? = nil) {
        self.command = command
        self.saveHistory = saveHistory
        self.persistState = persistState
        self.recoverPersistence = recoverPersistence
        memories = state.memories
        stacks = StackCatalog(removed: history.removed)
        lastRemoved = history.undo
        selectedSession = state.selectedSession ?? command[command.count - 2]
        approvals = ApprovalPresentation(seen: Set(UserDefaults(suiteName: "local.doro.approvals")?.stringArray(forKey: "seen") ?? []))
        restoreMemory()
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

    @discardableResult func switchSession(_ id: String, openingStack: Bool = false) -> Bool {
        let restoreHistory = openingStack && !stacks.isListed(id)
        if id != selectedSession || restoreHistory {
            guard saveMemory() else { return false }
        }
        if restoreHistory {
            do {
                try saveHistory(StackHistorySnapshot(removed: stacks.removed.subtracting([id]),
                                                     undo: lastRemoved.subtracting([id])))
                historyError = ""
            } catch { historyError = "목록을 복원하지 못했도로: \(error.localizedDescription)"; return false }
        }
        if openingStack { stacks.open(id); lastRemoved.remove(id) }
        guard id != selectedSession else { readError = ""; return true }
        approvals.dismiss()
        selectedSession = id
        generation += 1
        restoreMemory()
        conversation = snapshots[id]
        readError = ""
        return true
    }

    private func restoreMemory() {
        let memory = memories[selectedSession] ?? ContextMemory()
        inputText = memory.text
        inputStatus = memory.status
        expandedMessages = memory.expanded
        scrollTarget = memory.scrollTarget
        followLatest = memory.scrollTarget == nil
    }

    func refresh() {
        do { try applyRequest(); requestError = "" }
        catch { requestError = "연결 갱신 실패: \(error.localizedDescription)" }
        guard !loading, display != .stop else { return }
        if display == .hidden {
            guard ProcessInfo.processInfo.systemUptime - lastBackgroundRead >= 3 else { return }
            lastBackgroundRead = ProcessInfo.processInfo.systemUptime
            loading = true
            let source = Array(sessionCommand(selectedSession).dropLast()) + ["--contexts-json"]
            Task {
                defer { loading = false }
                do {
                    let value = try await Task.detached { try readContextSnapshot(source) }.value
                    updateContexts(value.contexts)
                    readError = ""
                } catch { readError = "작업 목록 갱신 실패: \(error.localizedDescription)" }
            }
            return
        }
        loading = true
        let id = selectedSession
        let epoch = generation
        let source = sessionCommand(id)
        Task {
            defer { loading = false; if selectedSession != id { refresh() } }
            do {
                let value = try await Task.detached { try readConversation(source) }.value
                snapshots[id] = value
                updateContexts(value.contexts)
                guard selectedSession == id, epoch == generation else { return }
                conversation = value
                synchronizeInputStatus(value)
                synchronizeApproval(value)
                if !collapsed && display != .hidden { seen[id] = contexts.first { $0.id == id }?.event_count ?? 0 }
                readError = ""
            } catch {
                if requestedApprovalSession == id { requestedApprovalSession = nil }
                if selectedSession == id { readError = "대화 갱신 실패: \(error.localizedDescription)" }
            }
        }
    }

    private func updateContexts(_ values: [ChatContext]) {
        if contexts.isEmpty { for item in values { seen[item.id] = item.event_count } }
        contexts = values
        do { try synchronizeStacks(values); historyError = "" }
        catch { historyError = "목록 이력을 저장하지 못했도로: \(error.localizedDescription)" }
        onApprovalChange?()
    }

    func sessionCommand(_ id: String) -> [String] { Array(command.dropLast(2)) + [id, "--json"] }

    func submitInput() {
        submit(session: selectedSession, text: inputText, checkpoint: conversation?.checkpoint_id ?? "", decision: nil)
    }

    func changeModel(_ model: String, effort: String, session: String, provider: String = "claude", enabled: Bool = true) async throws {
        guard let token = capabilities[session] else { throw ChatReadError.failed("스택 연결을 다시 열어줘도로.") }
        let command = Array(sessionCommand(session).dropLast()) + ["--set-model"]
        let data = try JSONSerialization.data(withJSONObject: ["model": model, "effort": effort, "provider": provider, "enabled": enabled])
        _ = try await Task.detached { try localCommand(command, input: data, capability: token) }.value
        refresh()
    }

}
