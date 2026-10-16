import AppKit

enum TaskListLayout {
    static let rowHeight = 56.0
    static let controlHeight = 28.0
    static let verticalInset = 8.0

    static func contentHeight(open: Int, history: Int, historyExpanded: Bool,
                              selecting: Bool, undo: Bool) -> Double {
        var height = verticalInset * 2 + Double(max(0, open)) * rowHeight
        if open == 0 && history == 0 { height += rowHeight }
        if history > 0 {
            height += controlHeight
            if historyExpanded { height += Double(history) * rowHeight + (selecting ? controlHeight : 0) }
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
