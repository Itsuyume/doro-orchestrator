import Foundation

@main
struct MotionChecks {
    static func main() {
        let directions: [(Double, Double, Int, Int)] = [
            (0, 100, 9, 0), (100, 0, 9, 4), (0, -100, 10, 0), (-100, 0, 10, 4),
            (0, 0, 0, 0)
        ]
        for (x, y, row, column) in directions {
            let frame = PetAnimation.look(x: x, y: y)
            precondition(frame.row == row && frame.column == column, "Gaze must face the pointer")
        }
        for activity in [PetAnimation.idle, .working, .waiting, .failed] {
            precondition(activity.steps.allSatisfy { $0.row == 0 },
                         "Default face must stay neutral, with the original round body")
        }
        for activity in [PetAnimation.idle, .working, .waiting, .completed, .failed, .movingRight, .movingLeft] {
            precondition(!activity.steps.isEmpty)
            precondition(activity.steps.allSatisfy { $0.seconds > 0 && $0.column >= 0 && $0.column < 8
                && $0.row >= 0 && $0.row < 11 && $0.row != 6 && $0.row != 7 },
                "No out-of-atlas or extra-arm gesture frame may be played")
        }
        print("Native motion checks passed: gaze cardinals, neutral default, original frames, no extra-arm rows")
    }
}
