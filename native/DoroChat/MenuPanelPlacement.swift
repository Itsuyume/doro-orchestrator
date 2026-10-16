import AppKit

private func menuReference(anchor: NSRect, size: NSSize) -> NSPoint {
    NSPoint(x: anchor.midX - size.width / 2, y: anchor.minY - size.height - 6)
}

func menuPanelOrigin(anchor: NSRect, size: NSSize, visible: NSRect, offset: NSPoint = .zero) -> NSPoint {
    let reference = menuReference(anchor: anchor, size: size)
    return clampedPanelOrigin(NSPoint(x: reference.x + offset.x, y: reference.y + offset.y),
                              size: size, visible: visible)
}

struct MenuPanelPlacement {
    private var offset = NSPoint.zero
    private var displayID: UInt32?

    mutating func remember(origin: NSPoint, anchor: NSRect, size: NSSize, display: UInt32) {
        let reference = menuReference(anchor: anchor, size: size)
        offset = NSPoint(x: origin.x - reference.x, y: origin.y - reference.y)
        displayID = display
    }

    mutating func frame(anchor: NSRect, size: NSSize, visible: NSRect, display: UInt32, reset: Bool = false) -> NSRect {
        if reset || displayID != display { offset = .zero }
        displayID = display
        let fitted = NSSize(width: min(size.width, visible.width), height: min(size.height, visible.height))
        return NSRect(origin: menuPanelOrigin(anchor: anchor, size: fitted, visible: visible, offset: offset), size: fitted)
    }
}
