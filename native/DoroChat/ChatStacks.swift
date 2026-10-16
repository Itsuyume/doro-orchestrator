import Foundation

@MainActor
extension ChatController {
    func requestOfficialPet() {
        submit(session: selectedSession, text: "전용 도로 대신 원래 공식 도로로 돌아가도록 전환해줘도로.",
               checkpoint: conversation?.checkpoint_id ?? "", decision: nil)
    }

    var pinnedContexts: [ChatContext] { contexts.filter { stacks.contains($0.id) } }
    var otherContexts: [ChatContext] { contexts.filter { stacks.isListed($0.id) && !stacks.contains($0.id) } }

    func isInProgress(_ context: ChatContext) -> Bool {
        !context.finished || context.needs_input || context.queued_inputs > 0 || sendingSessions.contains(context.id)
    }

    var listedContexts: [ChatContext] {
        let visible = pinnedContexts + (historyExpanded ? otherContexts : [])
        return visible.filter { isInProgress($0) } + visible.filter { !isInProgress($0) }
    }

    var completedBoundaryID: String? {
        let rows = listedContexts
        guard let first = rows.first, isInProgress(first) else { return nil }
        return rows.first { !isInProgress($0) }?.id
    }

    func openContext(_ id: String) {
        guard contexts.contains(where: { $0.id == id }) else { return }
        guard switchSession(id, openingStack: true) else { return }
        showingNewTask = false
        showingTasks = false
        collapsed = false
        revealPanel()
        refresh()
    }

    func minimizeCurrent() {
        if !showingTasks { stacks.open(selectedSession) }
        if display == .panel { hidePanel() }
        collapsed = true
    }

    func collapseToDock() {
        if !showingTasks { stacks.open(selectedSession) }
        collapsed = true
    }

    func hidePanel() {
        display = .hidden
        approvals.dismiss()
        onDisplay?(.hidden)
    }

    func requestStop() {
        guard canQuit else { readError = "메시지 전달을 확인한 뒤 종료해줘도로."; return }
        guard prepareToStop() else { return }
        onStop?()
    }

    func closeStack(_ id: String) {
        stacks.close(id)
        if showingTasks { onStackLayout?(); return }
        if id == selectedSession { collapsed = true }
        else { onStackLayout?() }
        if display == .panel && (id == selectedSession || pinnedContexts.isEmpty) { hidePanel() }
    }

    func toggleChat() {
        if !collapsed { minimizeCurrent(); return }
        if !showingTasks && !stacks.contains(selectedSession) {
            if let first = pinnedContexts.first { openContext(first.id); return }
            showingTasks = true
        }
        collapsed = false
        revealPanel()
    }

    func showTasks() { showingNewTask = false; showingTasks = true; collapsed = false; revealPanel() }

    private func revealPanel() {
        guard display == .hidden else { return }
        display = .panel
        onDisplay?(.panel)
        refresh()
    }

    func synchronizeStacks(_ contexts: [ChatContext]) throws {
        let previous = pinnedContexts.count
        var next = stacks
        next.synchronize(contexts, selected: selectedSession)
        let undo = lastRemoved.intersection(next.removed)
        if next.removed != stacks.removed {
            try saveHistory(StackHistorySnapshot(removed: next.removed, undo: undo))
        }
        stacks = next
        lastRemoved = undo
        if previous != pinnedContexts.count { onStackLayout?() }
    }
}
