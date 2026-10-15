import Foundation

@MainActor
extension ChatController {
    func requestOfficialPet() {
        submit(session: selectedSession, text: "전용 도로 대신 원래 공식 도로로 돌아가도록 전환해줘도로.",
               checkpoint: conversation?.checkpoint_id ?? "", decision: nil)
    }

    var pinnedContexts: [ChatContext] { contexts.filter { stacks.contains($0.id) } }
    var otherContexts: [ChatContext] { contexts.filter { !stacks.contains($0.id) } }

    func openContext(_ id: String) {
        guard contexts.contains(where: { $0.id == id }) else { return }
        stacks.open(id)
        showingTasks = false
        selectContext(id)
        collapsed = false
        revealPanel()
    }

    func minimizeCurrent() {
        if !showingTasks { stacks.open(selectedSession) }
        collapsed = true
    }

    func closeStack(_ id: String) {
        stacks.close(id)
        if id == selectedSession { collapsed = true }
        else { onStackLayout?() }
        if pinnedContexts.isEmpty && display == .panel {
            display = .hidden
            approvals.dismiss()
            onDisplay?(.hidden)
        }
    }

    func toggleChat() {
        if !collapsed { minimizeCurrent(); return }
        if stacks.contains(selectedSession) { showingTasks = false }
        else if let first = pinnedContexts.first { openContext(first.id); return }
        else { showingTasks = true }
        collapsed = false
    }

    func showTasks() { showingTasks = true; collapsed = false; revealPanel() }

    private func revealPanel() {
        guard display == .hidden else { return }
        display = .panel
        onDisplay?(.panel)
        refresh()
    }

    func synchronizeStacks(_ contexts: [ChatContext]) {
        let previous = pinnedContexts.count
        stacks.synchronize(contexts, selected: selectedSession)
        if previous != pinnedContexts.count { onStackLayout?() }
    }
}
