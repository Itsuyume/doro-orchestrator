import AppKit
import SwiftUI

@MainActor
final class ComposerTextView: NSTextView {
    var onSubmit: (() -> Void)?

    static func sends(_ event: NSEvent, composing: Bool) -> Bool {
        let modifiers = event.modifierFlags.intersection([.shift, .control, .option, .command])
        return (event.keyCode == 36 || event.keyCode == 76) && modifiers.isEmpty && !composing
    }

    override func keyDown(with event: NSEvent) {
        guard Self.sends(event, composing: hasMarkedText()) else { super.keyDown(with: event); return }
        guard isEditable, !event.isARepeat else { return }
        onSubmit?()
    }
}

@MainActor
struct ChatInputEditor: NSViewRepresentable {
    @Binding var text: String
    @Environment(\.isEnabled) private var isEnabled
    var label = "도로에게 보낼 내 메시지"
    let onSubmit: () -> Void

    func makeCoordinator() -> Coordinator { Coordinator(parent: self) }

    func makeNSView(context: Context) -> NSScrollView {
        let scroll = NSScrollView()
        scroll.drawsBackground = false
        scroll.hasVerticalScroller = true
        scroll.autohidesScrollers = true
        let editor = ComposerTextView()
        editor.isRichText = false
        editor.allowsUndo = true
        editor.drawsBackground = false
        editor.textColor = .textColor
        editor.insertionPointColor = .textColor
        editor.font = .systemFont(ofSize: 13)
        editor.textContainerInset = NSSize(width: 4, height: 4)
        editor.isVerticallyResizable = true
        editor.isHorizontallyResizable = false
        editor.autoresizingMask = [.width]
        editor.maxSize = NSSize(width: CGFloat.greatestFiniteMagnitude, height: CGFloat.greatestFiniteMagnitude)
        editor.textContainer?.widthTracksTextView = true
        editor.textContainer?.containerSize = NSSize(width: scroll.contentSize.width, height: CGFloat.greatestFiniteMagnitude)
        editor.setAccessibilityLabel(label)
        editor.delegate = context.coordinator
        scroll.documentView = editor
        return scroll
    }

    func updateNSView(_ scroll: NSScrollView, context: Context) {
        context.coordinator.parent = self
        guard let editor = scroll.documentView as? ComposerTextView else { return }
        editor.isEditable = isEnabled
        editor.setAccessibilityLabel(label)
        editor.onSubmit = onSubmit
        guard !editor.hasMarkedText(), editor.string != text else { return }
        editor.string = text
        editor.setSelectedRange(NSRange(location: (text as NSString).length, length: 0))
    }

    final class Coordinator: NSObject, NSTextViewDelegate {
        var parent: ChatInputEditor
        init(parent: ChatInputEditor) { self.parent = parent }

        func textDidChange(_ notification: Notification) {
            guard let editor = notification.object as? ComposerTextView, parent.text != editor.string else { return }
            parent.text = editor.string
        }
    }
}
