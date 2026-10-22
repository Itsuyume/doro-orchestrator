import Foundation

enum MessagePreview {
    static let lines = 6

    static func canExpand(_ text: String) -> Bool {
        text.count > 180 || text.split(omittingEmptySubsequences: false) { $0.isNewline }.count > lines
    }

    static func lineLimit(_ text: String, expanded: Bool) -> Int? {
        canExpand(text) && !expanded ? lines : nil
    }
}
