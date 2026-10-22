import AppKit
import SwiftUI

@MainActor
final class ComposerTextView: NSTextView {
    var onSubmit: (() -> Void)?
    private var lastFittedHeight: CGFloat = 34

    func fittingHeight(width: CGFloat) -> CGFloat {
        guard width > 0, width.isFinite, let font else {
            return lastFittedHeight
        }
        let container = NSTextContainer(containerSize: NSSize(width: max(1, width - textContainerInset.width * 2),
            height: CGFloat.greatestFiniteMagnitude))
        container.lineFragmentPadding = textContainer?.lineFragmentPadding ?? 5
        let layout = NSLayoutManager()
        layout.addTextContainer(container)
        let storage = NSTextStorage(attributedString: attributedString())
        storage.addLayoutManager(layout)
        layout.ensureLayout(for: container)
        let contentHeight = max(layout.usedRect(for: container).maxY, layout.extraLineFragmentRect.maxY,
                                layout.defaultLineHeight(for: font))
        let fitted = min(120, max(34, ceil(contentHeight + textContainerInset.height * 2)))
        lastFittedHeight = hasMarkedText() ? max(lastFittedHeight, fitted) : fitted
        return lastFittedHeight
    }

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
    var growsWithText = false
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

    func sizeThatFits(_ proposal: ProposedViewSize, nsView scroll: NSScrollView, context: Context) -> CGSize? {
        guard growsWithText, let width = proposal.width, width > 0, width.isFinite,
              let editor = scroll.documentView as? ComposerTextView else { return nil }
        let content = NSScrollView.contentSize(forFrameSize: NSSize(width: width, height: 120),
            horizontalScrollerClass: nil, verticalScrollerClass: NSScroller.self, borderType: scroll.borderType,
            controlSize: scroll.verticalScroller?.controlSize ?? .regular, scrollerStyle: scroll.scrollerStyle)
        return CGSize(width: width, height: editor.fittingHeight(width: content.width))
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
