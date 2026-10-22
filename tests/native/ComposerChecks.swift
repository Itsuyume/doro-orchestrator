import AppKit

@main
struct ComposerChecks {
    @MainActor static func event(_ flags: NSEvent.ModifierFlags = [], key: UInt16 = 36, repeatKey: Bool = false) -> NSEvent {
        NSEvent.keyEvent(with: .keyDown, location: .zero, modifierFlags: flags, timestamp: 0,
            windowNumber: 0, context: nil, characters: "\r", charactersIgnoringModifiers: "\r",
            isARepeat: repeatKey, keyCode: key)!
    }

    @MainActor static func main() {
        _ = NSApplication.shared
        let editor = ComposerTextView(frame: NSRect(x: 0, y: 0, width: 300, height: 60))
        let window = NSWindow(contentRect: editor.frame, styleMask: .borderless, backing: .buffered, defer: false)
        window.contentView = editor
        precondition(window.makeFirstResponder(editor))
        editor.isRichText = false
        editor.string = "첫 줄 🇰🇷"
        editor.setSelectedRange(NSRange(location: (editor.string as NSString).length, length: 0))
        var submissions = 0
        editor.onSubmit = { submissions += 1 }
        editor.keyDown(with: event())
        precondition(submissions == 1 && editor.string == "첫 줄 🇰🇷", "Enter submits without inserting a line break")
        editor.keyDown(with: event(.shift))
        precondition(submissions == 1 && editor.string.hasSuffix("\n"), "Shift+Enter edits without sending")
        editor.keyDown(with: event(repeatKey: true))
        editor.isEditable = false
        editor.keyDown(with: event())
        precondition(submissions == 1, "A held Enter or disabled editor cannot send")
        editor.isEditable = true
        precondition(window.firstResponder === editor, "Temporarily disabling input must preserve the keyboard responder")
        for flags: NSEvent.ModifierFlags in [.shift, .option, .control, .command] {
            precondition(!ComposerTextView.sends(event(flags), composing: false))
        }
        precondition(ComposerTextView.sends(event(.capsLock), composing: false))
        precondition(ComposerTextView.sends(event(.numericPad, key: 76), composing: false))
        precondition(!ComposerTextView.sends(event([], key: 0), composing: false))
        editor.setMarkedText("한", selectedRange: NSRange(location: 1, length: 0),
                             replacementRange: NSRange(location: NSNotFound, length: 0))
        precondition(editor.hasMarkedText())
        editor.keyDown(with: event())
        precondition(submissions == 1, "Confirming an IME composition cannot submit")
        checkMeasuredHeight()
        print("Composer checks passed: Enter submits, Shift+Enter newline, IME confirmation does not submit, modifier/keypad boundaries")
    }

    @MainActor static func checkMeasuredHeight() {
        let editor = ComposerTextView(frame: NSRect(x: 0, y: 0, width: 300, height: 34))
        editor.font = .systemFont(ofSize: 13)
        editor.textContainerInset = NSSize(width: 4, height: 4)
        precondition(editor.fittingHeight(width: 300) == 34)
        editor.string = "가\n나\n다\n라"
        let multiple = editor.fittingHeight(width: 300)
        precondition(multiple > 34 && multiple < 120, "New lines grow the composer before scrolling is needed")
        editor.string = String(repeating: "가나다라 ", count: 12)
        editor.setSelectedRange(NSRange(location: 4, length: 2))
        let wide = editor.fittingHeight(width: 500)
        let narrow = editor.fittingHeight(width: 120)
        precondition(narrow > wide, "Actual wrapping, not only newline count, determines input height")
        precondition(editor.selectedRange() == NSRange(location: 4, length: 2), "Measuring cannot move the caret or selection")
        editor.string = String(repeating: "줄\n", count: 30)
        precondition(editor.fittingHeight(width: 300) == 120, "Long input is capped so conversation space remains")
        editor.setMarkedText("한", selectedRange: NSRange(location: 1, length: 0),
            replacementRange: NSRange(location: 0, length: (editor.string as NSString).length))
        precondition(editor.hasMarkedText() && editor.fittingHeight(width: 300) == 120,
                     "IME composition cannot shrink the editor unexpectedly")
        editor.unmarkText()
        precondition(editor.fittingHeight(width: 300) == 34)
        editor.string = ""
        precondition(editor.fittingHeight(width: 300) == 34 && editor.fittingHeight(width: 0) == 34)
    }
}
