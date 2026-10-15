import Foundation

struct StackHistorySnapshot: Codable {
    var removed: Set<String> = []
    var undo: Set<String> = []
}

struct StackCatalog {
    private var presentation: [String: Bool] = [:]
    private(set) var removed: Set<String>

    init(removed: Set<String> = []) { self.removed = removed }

    func isListed(_ id: String) -> Bool { !removed.contains(id) }
    func contains(_ id: String) -> Bool { isListed(id) && presentation[id] == true }

    mutating func synchronize(_ contexts: [ChatContext], selected: String) {
        for context in contexts where context.needs_input && removed.contains(context.id) {
            removed.remove(context.id)
            presentation[context.id] = true
        }
        let ids = Set(contexts.map(\.id))
        presentation = presentation.filter { ids.contains($0.key) }
        for context in contexts where isListed(context.id) && presentation[context.id] == nil {
            presentation[context.id] = context.id == selected || !context.finished
        }
    }

    mutating func open(_ id: String) { removed.remove(id); presentation[id] = true }
    mutating func close(_ id: String) { presentation[id] = false }

    func removableIDs(_ contexts: [ChatContext], busy: Set<String> = []) -> Set<String> {
        Set(contexts.filter { isListed($0.id) && !contains($0.id) && $0.finished && !$0.needs_input
            && $0.queued_inputs == 0 && !busy.contains($0.id) }.map(\.id))
    }

    mutating func remove(_ ids: Set<String>, contexts: [ChatContext], busy: Set<String> = []) -> Set<String> {
        let accepted = ids.intersection(removableIDs(contexts, busy: busy))
        removed.formUnion(accepted)
        for id in accepted { presentation.removeValue(forKey: id) }
        return accepted
    }

    mutating func restore(_ ids: Set<String>) {
        removed.subtract(ids)
        for id in ids { presentation[id] = false }
    }
}
