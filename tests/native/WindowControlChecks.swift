import AppKit

@main
struct WindowControlChecks {
    @MainActor static func main() throws {
        let visible = NSRect(x: -1200, y: -50, width: 1200, height: 800)
        let anchor = NSRect(x: -30, y: 750, width: 20, height: 22)
        precondition(menuPanelOrigin(anchor: anchor, size: NSSize(width: 390, height: 590), visible: visible)
                     == NSPoint(x: -390, y: 154))
        precondition(menuPanelOrigin(anchor: anchor, size: NSSize(width: 2000, height: 1000), visible: visible)
                     == visible.origin)
        let narrow = NSRect(x: 0, y: 0, width: 320, height: 700)
        precondition(menuPanelOrigin(anchor: NSRect(x: 0, y: 700, width: 20, height: 22),
                                    size: NSSize(width: 320, height: 400), visible: narrow) == NSPoint(x: 0, y: 294))
        let shortcut = try GlobalShortcut(onPress: {})
        do { _ = try GlobalShortcut(onPress: {}); preconditionFailure("A duplicate hotkey must not be stolen") }
        catch { precondition(error is ChatReadError) }
        shortcut.stop()
        shortcut.stop()
        let reopened = try GlobalShortcut(onPress: {})
        reopened.stop()
        print("Window control checks passed: menu anchoring, negative screen coordinates, screen bounds, hotkey collision/release")
    }
}
