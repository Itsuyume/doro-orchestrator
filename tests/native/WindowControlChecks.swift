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
        checkMenuTracking()
        print("Window control checks passed: menu anchoring, negative screen coordinates, screen bounds, hotkey collision/release")
    }

    static func checkMenuTracking() {
        let visible = NSRect(x: 0, y: 0, width: 1200, height: 800)
        let size = NSSize(width: 390, height: 400)
        let anchor = NSRect(x: 1170, y: 800, width: 20, height: 22)
        var placement = MenuPanelPlacement()
        placement.remember(origin: NSPoint(x: 700, y: 250), anchor: anchor, size: size, display: 1)
        var frame = placement.frame(anchor: anchor, size: size, visible: visible, display: 1)
        precondition(frame.origin == NSPoint(x: 700, y: 250), "A first drag is preserved before any placement")
        let moved = anchor.offsetBy(dx: -20, dy: 0)
        frame = placement.frame(anchor: moved, size: size, visible: visible, display: 1)
        precondition(frame.origin == NSPoint(x: 680, y: 250), "Menu movement preserves the exact offset even near screen edges")
        let dock = NSRect(x: 0, y: 50, width: 1200, height: 750)
        frame = placement.frame(anchor: moved, size: size, visible: dock, display: 1)
        precondition(frame.origin == NSPoint(x: 680, y: 250), "Dock geometry alone cannot erase a manual offset")
        let second = NSRect(x: -1200, y: 0, width: 1200, height: 800)
        let secondAnchor = NSRect(x: -30, y: 800, width: 20, height: 22)
        frame = placement.frame(anchor: secondAnchor, size: size, visible: second, display: 2)
        precondition(frame.origin == menuPanelOrigin(anchor: secondAnchor, size: size, visible: second))
        placement.remember(origin: NSPoint(x: -700, y: 100), anchor: secondAnchor, size: size, display: 2)
        frame = placement.frame(anchor: secondAnchor, size: size, visible: second, display: 2, reset: true)
        precondition(frame.origin == menuPanelOrigin(anchor: secondAnchor, size: size, visible: second), "Reopen returns below the current icon")
        frame = placement.frame(anchor: anchor, size: NSSize(width: 2000, height: 1000), visible: visible, display: 1)
        precondition(frame.size == visible.size && frame.origin == visible.origin)
    }
}
