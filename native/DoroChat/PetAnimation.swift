import Foundation

struct SpriteStep {
    let row: Int
    let column: Int
    let seconds: Double
}

enum PetAnimation {
    case idle, working, waiting, completed, failed, movingRight, movingLeft

    static func activity(_ status: String) -> PetAnimation {
        if status == "승인 대기" { return .waiting }
        if status == "완료" { return .completed }
        if status == "실패" || status == "중단" { return .failed }
        return status.isEmpty ? .idle : .working
    }

    var steps: [SpriteStep] {
        switch self {
        case .movingRight: return row(1, count: 8, seconds: 0.12)
        case .movingLeft: return row(2, count: 8, seconds: 0.12)
        case .completed: return row(4, count: 5, seconds: 0.16) + [SpriteStep(row: 0, column: 0, seconds: 1.4)]
        case .idle, .working, .waiting, .failed:
            return [SpriteStep(row: 0, column: 0, seconds: 1.6),
                    SpriteStep(row: 0, column: 1, seconds: 0.18),
                    SpriteStep(row: 0, column: 2, seconds: 0.2),
                    SpriteStep(row: 0, column: 3, seconds: 0.12),
                    SpriteStep(row: 0, column: 4, seconds: 0.2),
                    SpriteStep(row: 0, column: 5, seconds: 0.35),
                    SpriteStep(row: 0, column: 0, seconds: 1.4)]
        }
    }

    private func row(_ index: Int, count: Int, seconds: Double) -> [SpriteStep] {
        (0..<count).map { SpriteStep(row: index, column: $0, seconds: seconds) }
    }

    static func look(x: Double, y: Double) -> SpriteStep {
        if hypot(x, y) < 2 { return SpriteStep(row: 0, column: 0, seconds: 1) }
        let angle = (atan2(x, y) + Double.pi * 2).truncatingRemainder(dividingBy: Double.pi * 2)
        let direction = Int((angle / (Double.pi * 2) * 16).rounded()) % 16
        return SpriteStep(row: 9 + direction / 8, column: direction % 8, seconds: 1)
    }
}
