import AppKit

enum TaskListLayout {
    static let maxVisibleRows = 3
    static let rowHeight = 56.0
    static let controlHeight = 28.0
    static let verticalInset = 8.0

    static func rowViewportHeight(open: Int, history: Int, historyExpanded: Bool) -> Double {
        let rows = open + (historyExpanded ? history : 0)
        let visible = open == 0 && history == 0 ? 1 : min(maxVisibleRows, rows)
        return verticalInset * 2 + Double(visible) * rowHeight
    }

    static func contentHeight(open: Int, history: Int, historyExpanded: Bool,
                              selecting: Bool, undo: Bool) -> Double {
        var height = rowViewportHeight(open: open, history: history, historyExpanded: historyExpanded)
        if history > 0 {
            height += controlHeight
            if historyExpanded && selecting { height += controlHeight }
        }
        if undo { height += controlHeight }
        return height
    }
}

@MainActor func configurePanelSizing(_ window: NSWindow, collapsed: Bool, taskList: Bool, compact: NSSize) {
    if collapsed || taskList { window.styleMask.remove(.resizable) }
    else { window.styleMask.insert(.resizable) }
    if collapsed { window.minSize = compact; window.maxSize = compact }
    else {
        window.maxSize = NSSize(width: CGFloat.greatestFiniteMagnitude, height: CGFloat.greatestFiniteMagnitude)
        window.minSize = NSSize(width: 320, height: taskList ? 130 : 400)
    }
}
