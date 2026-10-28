import AppKit
import SwiftUI

@MainActor final class ComposerSize {
    var height: CGFloat = 0
}

@main
struct ReadabilityChecks {
    @MainActor static func main() {
        _ = NSApplication.shared
        checkShortMultilineMessages()
        checkReadingPositionAndSession()
        checkListTitlePreservesSelection()
        checkComposerLayout()
        checkComposerContainer()
        checkLiveEditing()
        print("Readability checks passed: every limited preview expands; latest jump and list title preserve session/draft state")
    }

    static func checkShortMultilineMessages() {
        for text in ["", "짧은 답변", String(repeating: "가", count: 180), "가\n\n\n\n\n나"] {
            precondition(MessagePreview.lineLimit(text, expanded: false) == nil,
                         "Text without an expansion control must never be line-clipped")
        }
        for text in ["가\n나\n다\n라\n마\n바\n사", "\n\n\n\n\n\n\n",
                     String(repeating: "가", count: 181), String(repeating: "🇰🇷\n", count: 8),
                     String(repeating: "가\r\n", count: 7), String(repeating: "가\r", count: 7),
                     String(repeating: "가\u{2028}", count: 6)] {
            precondition(MessagePreview.canExpand(text), "Short multi-line content needs an expansion path")
            precondition(MessagePreview.lineLimit(text, expanded: false) == 6)
            precondition(MessagePreview.lineLimit(text, expanded: true) == nil,
                         "Expansion exposes the entire unchanged message")
        }
    }

    @MainActor static func checkReadingPositionAndSession() {
        let controller = ChatController(command: ["/usr/bin/false", "chat", "A", "--json"])
        controller.inputText = "보낼 초안 🇰🇷"
        controller.expandedMessages = ["short-multiline"]
        controller.scrollTarget = "earlier"
        controller.followLatest = false
        controller.returnToLatest()
        precondition(controller.followLatest && controller.scrollTarget == nil)
        precondition(controller.inputText == "보낼 초안 🇰🇷" && controller.selectedSession == "A")
        precondition(controller.expandedMessages == ["short-multiline"])
        precondition(controller.switchSession("B"))
        controller.inputText = "다른 초안"
        controller.scrollTarget = "B-earlier"
        controller.followLatest = false
        precondition(controller.switchSession("A"))
        precondition(controller.followLatest && controller.scrollTarget == nil && controller.inputText == "보낼 초안 🇰🇷")
        precondition(controller.switchSession("B"))
        precondition(!controller.followLatest && controller.scrollTarget == "B-earlier" && controller.inputText == "다른 초안")
    }

    @MainActor static func checkListTitlePreservesSelection() {
        let controller = ChatController(command: ["/usr/bin/false", "chat", "A", "--json"])
        controller.contexts = [ChatContext(session_id: "A", label: "첫 대화", status: "완료", needs_input: false,
            event_count: 1, queued_inputs: 0, finished: true),
            ChatContext(session_id: "B", label: "둘째 대화", status: "완료", needs_input: false,
            event_count: 1, queued_inputs: 0, finished: true)]
        controller.stacks.open("A")
        controller.inputText = "남아 있는 초안"
        controller.scrollTarget = "earlier"
        controller.inputStatus = "전달 확인 중"
        controller.showTasks()
        precondition(controller.toolbarStatus == "대화 1개")
        controller.historyExpanded = true
        precondition(controller.toolbarStatus == "대화 2개")
        precondition(controller.selectedSession == "A" && controller.inputText == "남아 있는 초안"
                     && controller.scrollTarget == "earlier", "List presentation cannot clear selection or conversation state")
        controller.showingTasks = false
        precondition(controller.toolbarStatus == "전달 확인 중 · 첫 대화")
        controller.showingNewTask = true
        precondition(controller.toolbarStatus == "새 작업")
    }

    static func conversation() -> Conversation {
        Conversation(version: 1, session_id: "A", title: "Local", status: "waiting", usage: "",
            messages: [], reply_hint: "", input_enabled: true, checkpoint_id: "", label: "Local",
            contexts: [], claude_enabled: true, agy_enabled: false, approval: nil, model_selection: nil)
    }

    @MainActor static func composerHeight(_ text: String, width: CGFloat, fullConversation: Bool = false) -> CGFloat {
        let controller = ChatController(command: ["/usr/bin/false", "chat", "A", "--json"])
        controller.inputText = text
        controller.conversation = conversation()
        controller.display = .panel
        let host = NSHostingView(rootView: Group {
            if fullConversation { ChatView(controller: controller) }
            else { OverlayComposer(controller: controller) }
        })
        let window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: width, height: 590),
            styleMask: .borderless, backing: .buffered, defer: false)
        window.isReleasedWhenClosed = false
        defer { window.close() }
        window.contentView = host
        host.layoutSubtreeIfNeeded()
        return editorScroll(in: host).bounds.height
    }

    @MainActor static func editorScroll(in host: NSView) -> NSScrollView {
        var views: [NSView] = [host]
        while let view = views.popLast() {
            if let scroll = view as? NSScrollView, scroll.documentView is ComposerTextView { return scroll }
            views.append(contentsOf: view.subviews)
        }
        preconditionFailure("The actual composer must contain its native editor")
    }

    @MainActor static func checkComposerLayout() {
        let empty = composerHeight("", width: 320)
        let multiple = composerHeight("가\n나\n다\n라", width: 320)
        let long = composerHeight(String(repeating: "가나다라 ", count: 200), width: 320)
        precondition(empty == 34 && multiple > empty && multiple < long && long == 120,
                     "The SwiftUI surface must actually fit its native editor instead of keeping an empty 120pt frame")
        for width: CGFloat in [320, 390] {
            let fullEmpty = composerHeight("", width: width, fullConversation: true)
            let fullMultiple = composerHeight("가\n나\n다\n라", width: width, fullConversation: true)
            precondition(fullEmpty == 34 && fullMultiple > fullEmpty && fullMultiple < 120,
                         "Conversation layout cannot stretch the composer into unused blank space")
        }
    }

    @MainActor static func composerContainerHeight(_ text: String) -> CGFloat {
        let controller = ChatController(command: ["/usr/bin/false", "chat", "A", "--json"])
        controller.inputText = text
        controller.conversation = conversation()
        let size = ComposerSize()
        let host = NSHostingView(rootView: VStack {
            Color.clear.frame(maxHeight: .infinity)
            OverlayComposer(controller: controller).background {
                GeometryReader { geometry in
                    Color.clear.onAppear { size.height = geometry.size.height }
                }
            }
        })
        let window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 320, height: 590),
            styleMask: .borderless, backing: .buffered, defer: false)
        window.isReleasedWhenClosed = false
        defer { window.close() }
        window.contentView = host
        host.layoutSubtreeIfNeeded()
        RunLoop.main.run(until: Date().addingTimeInterval(0.02))
        return size.height
    }

    @MainActor static func checkComposerContainer() {
        let empty = composerContainerHeight("")
        let multiple = composerContainerHeight("가\n나\n다\n라")
        let long = composerContainerHeight(String(repeating: "줄\n", count: 30))
        precondition(empty > 34 && empty < 90 && multiple > empty && multiple < long,
                     "The composer background must fit the text too, without a 120pt empty stretch")
    }

    @MainActor static func checkLiveEditing() {
        let controller = ChatController(command: ["/usr/bin/false", "chat", "A", "--json"])
        controller.conversation = conversation()
        let host = NSHostingView(rootView: OverlayComposer(controller: controller))
        let window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 320, height: 250),
            styleMask: .borderless, backing: .buffered, defer: false)
        window.isReleasedWhenClosed = false
        defer { window.close() }
        window.contentView = host
        func settle() {
            host.layoutSubtreeIfNeeded()
            RunLoop.main.run(until: Date().addingTimeInterval(0.02))
            host.layoutSubtreeIfNeeded()
        }
        settle()
        let scroll = editorScroll(in: host)
        guard let editor = scroll.documentView as? ComposerTextView else { preconditionFailure("Native composer is required") }
        window.makeFirstResponder(editor)
        editor.insertText("가\n나\n다\n라", replacementRange: NSRange(location: NSNotFound, length: 0))
        settle()
        precondition(controller.inputText == editor.string && scroll.bounds.height > 34 && scroll.bounds.height < 120,
                     "Real text edits must update the binding and resize the existing editor")
        editor.setMarkedText(String(repeating: "한글 조합 ", count: 50), selectedRange: NSRange(location: 1, length: 0),
                             replacementRange: NSRange(location: 0, length: (editor.string as NSString).length))
        settle()
        precondition(editor.hasMarkedText() && scroll.bounds.height == 120, "Marked text must invalidate layout as it grows")
        editor.unmarkText()
        editor.insertText("", replacementRange: NSRange(location: 0, length: (editor.string as NSString).length))
        settle()
        precondition(controller.inputText.isEmpty && scroll.bounds.height == 34, "Clearing a composed draft must shrink the editor")
        scroll.scrollerStyle = .legacy
        scroll.autohidesScrollers = false
        for count in 1...10 {
            controller.inputText = String(repeating: "가나다라마 ", count: count)
            settle()
            guard let layout = editor.layoutManager, let container = editor.textContainer else {
                preconditionFailure("Native text layout is required")
            }
            layout.ensureLayout(for: container)
            let needed = layout.usedRect(for: container).maxY + editor.textContainerInset.height * 2
            precondition(scroll.bounds.height == 120 || scroll.contentSize.height >= needed,
                         "Legacy scrollbars must not leave a partly hidden last line below the height cap")
        }
    }
}
