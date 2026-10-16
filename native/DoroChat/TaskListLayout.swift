import Foundation

enum TaskListLayout {
    static let rowHeight = 56.0
    static let controlHeight = 28.0
    static let verticalInset = 8.0

    static func contentHeight(open: Int, expanded: Bool, history: Int, historyExpanded: Bool,
                              selecting: Bool, undo: Bool) -> Double {
        var height = verticalInset * 2 + controlHeight
        if expanded { height += Double(max(1, open)) * rowHeight }
        if history > 0 {
            height += controlHeight
            if historyExpanded { height += Double(history) * rowHeight + (selecting ? controlHeight : 0) }
        }
        if undo { height += controlHeight }
        return height
    }
}
