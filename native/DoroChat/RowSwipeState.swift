import Foundation

struct RowSwipeState {
    private enum Axis { case undecided, horizontal, vertical }
    private var axis = Axis.undecided
    private var origin = CGFloat.zero
    private(set) var offset = CGFloat.zero
    var dragging: Bool { axis != .undecided }

    mutating func update(x: CGFloat, y: CGFloat, width: CGFloat) {
        guard width > 0 else { return }
        if axis == .undecided {
            guard max(abs(x), abs(y)) >= 12 else { return }
            axis = abs(x) > abs(y) * 1.2 ? .horizontal : .vertical
        }
        guard axis == .horizontal else { return }
        offset = min(0, max(-width, origin + x))
    }

    mutating func finish(width: CGFloat) -> Bool {
        defer { axis = .undecided }
        guard axis == .horizontal, width > 0 else { return false }
        let threshold = min(160, width * 0.55)
        if offset <= -threshold {
            offset = -width
            return true
        }
        origin = offset <= -28 ? -min(72, width) : 0
        offset = origin
        return false
    }

    mutating func cancel() { axis = .undecided; offset = origin }
    mutating func reset() { axis = .undecided; origin = 0; offset = 0 }
}
