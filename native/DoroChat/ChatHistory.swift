import Foundation

@MainActor
extension ChatController {
    var removableHistoryIDs: Set<String> {
        stacks.removableIDs(contexts, busy: sendingSessions)
    }

    func removeHistory(_ requested: Set<String>) {
        var next = stacks
        let ids = next.remove(requested, contexts: contexts, busy: sendingSessions)
        guard !ids.isEmpty else { return }
        do { try saveHistory(StackHistorySnapshot(removed: next.removed, undo: ids)) }
        catch { readError = "목록을 지우지 못했도로: \(error.localizedDescription)"; return }
        stacks = next
        lastRemoved = ids
        onStackLayout?()
    }

    func undoHistoryRemoval() {
        guard !lastRemoved.isEmpty else { return }
        do { try saveHistory(StackHistorySnapshot(removed: stacks.removed.subtracting(lastRemoved))) }
        catch { readError = "목록을 복원하지 못했도로: \(error.localizedDescription)"; return }
        stacks.restore(lastRemoved)
        lastRemoved = []
        onStackLayout?()
    }

    var taskPanelHeight: Double {
        taskListHeight(content: TaskListLayout.contentHeight(open: pinnedContexts.count,
            history: otherContexts.count, historyExpanded: historyExpanded,
            selecting: historySelecting, undo: !lastRemoved.isEmpty))
    }
}

func taskListHeight(content: Double) -> Double {
    min(620, max(130, content + 87))
}
