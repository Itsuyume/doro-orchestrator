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
        print("Composer checks passed: Enter submits, Shift+Enter newline, IME confirmation does not submit, modifier/keypad boundaries")
    }
}
