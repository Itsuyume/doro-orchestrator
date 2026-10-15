import Foundation

struct StackCatalog {
    private var presentation: [String: Bool] = [:]

    func contains(_ id: String) -> Bool { presentation[id] == true }

    mutating func synchronize(_ contexts: [ChatContext], selected: String) {
        let ids = Set(contexts.map(\.id))
        presentation = presentation.filter { ids.contains($0.key) }
        for context in contexts where presentation[context.id] == nil {
            presentation[context.id] = context.id == selected || !context.finished
        }
    }

    mutating func open(_ id: String) { presentation[id] = true }
    mutating func close(_ id: String) { presentation[id] = false }
}
