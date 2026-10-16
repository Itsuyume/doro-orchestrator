import AppKit
import SwiftUI

@main
struct SurfaceChecks {
    @MainActor static func resolved(_ color: Color, in appearance: NSAppearance) -> NSColor {
        var value: NSColor?
        appearance.performAsCurrentDrawingAppearance { value = NSColor(color).usingColorSpace(.sRGB) }
        guard let value else { preconditionFailure("Surface must resolve to sRGB") }
        return value
    }

    static func luminance(_ color: NSColor) -> Double {
        func linear(_ value: CGFloat) -> Double {
            let channel = Double(value)
            return channel <= 0.04045 ? channel / 12.92 : pow((channel + 0.055) / 1.055, 2.4)
        }
        return 0.2126 * linear(color.redComponent) + 0.7152 * linear(color.greenComponent)
            + 0.0722 * linear(color.blueComponent)
    }

    @MainActor static func contrast(_ foreground: Color, on background: Color, in appearance: NSAppearance) -> Double {
        let front = resolved(foreground, in: appearance), back = resolved(background, in: appearance)
        let alpha = front.alphaComponent
        let painted = NSColor(srgbRed: front.redComponent * alpha + back.redComponent * (1 - alpha),
            green: front.greenComponent * alpha + back.greenComponent * (1 - alpha),
            blue: front.blueComponent * alpha + back.blueComponent * (1 - alpha), alpha: 1)
        let first = luminance(painted), second = luminance(back)
        return (max(first, second) + 0.05) / (min(first, second) + 0.05)
    }

    @MainActor static func main() {
        _ = NSApplication.shared
        guard let light = NSAppearance(named: .aqua), let dark = NSAppearance(named: .darkAqua) else {
            preconditionFailure("Both macOS appearances are required")
        }
        let surfaces = [ChatSurface.panel, ChatSurface.chrome, ChatSurface.aiBubble, ChatSurface.userBubble, ChatSurface.editor]
        for surface in surfaces {
            precondition(luminance(resolved(surface, in: light)) > luminance(resolved(surface, in: dark)),
                         "Each actual surface must adapt instead of remaining white in dark mode")
        }
        for appearance in [light, dark] {
            for surface in surfaces {
                precondition(contrast(Color(nsColor: .labelColor), on: surface, in: appearance) >= 4.5,
                             "Body text must remain readable on every surface in both appearances")
            }
            precondition(contrast(ChatSurface.actionText, on: ChatSurface.action, in: appearance) >= 4.5,
                         "Approval action text must remain readable in both appearances")
            precondition(contrast(Color(nsColor: .textColor), on: ChatSurface.editor, in: appearance) >= 4.5,
                         "Composer text and caret must remain readable")
        }
        let controller = ChatController(command: ["/usr/bin/false", "chat", "A", "--json"])
        controller.inputText = "Preserve this draft"
        controller.scrollTarget = "earlier"
        let host = NSHostingView(rootView: ChatView(controller: controller))
        host.appearance = light
        precondition(host.effectiveAppearance.bestMatch(from: [.aqua, .darkAqua]) == .aqua)
        host.appearance = dark
        precondition(host.effectiveAppearance.bestMatch(from: [.aqua, .darkAqua]) == .darkAqua)
        precondition(controller.inputText == "Preserve this draft" && controller.scrollTarget == "earlier",
                     "An appearance change must not recreate conversation state")
        print("Surface checks passed: light/dark adaptation, text/caret/action contrast, draft and reading position")
    }
}
