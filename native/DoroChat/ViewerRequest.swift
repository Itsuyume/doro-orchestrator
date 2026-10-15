import Foundation

enum ViewerDisplay: String, Decodable, Sendable {
    case integrated, panel, hidden, stop
}

enum ViewerIntent: String, Decodable, Sendable { case open, minimize, hide }

func acknowledgeViewerRequest(_ request: ViewerRequest) throws {
    guard let source = ProcessInfo.processInfo.environment["DORO_CHAT_REQUEST"] else {
        throw ChatReadError.failed("전용 실행기의 연결 경로가 없도로.")
    }
    let path = URL(fileURLWithPath: source).deletingLastPathComponent().appendingPathComponent("viewer-ack.json")
    let data = try JSONSerialization.data(withJSONObject: ["request_id": request.request_id,
                                                          "display": request.display.rawValue,
                                                          "intent": (request.intent ?? .open).rawValue])
    try data.write(to: path, options: .atomic)
    try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: path.path)
}

struct ViewerRequest: Decodable, Sendable {
    let version: Int
    let request_id: String
    let session_id: String
    let display: ViewerDisplay
    let tokens: [String: String]
    let show_tasks: Bool?
    let intent: ViewerIntent?
}

func readViewerRequest() throws -> ViewerRequest {
    guard let path = ProcessInfo.processInfo.environment["DORO_CHAT_REQUEST"] else {
        throw ChatReadError.failed("전용 실행기의 연결 정보가 없도로.")
    }
    let data = try Data(contentsOf: URL(fileURLWithPath: path))
    guard data.count <= 1_000_000 else { throw ChatReadError.failed("로컬 연결 정보가 너무 크도로.") }
    let request = try JSONDecoder().decode(ViewerRequest.self, from: data)
    guard request.version == 1, UUID(uuidString: request.session_id) != nil else {
        throw ChatReadError.failed("로컬 연결 형식을 확인할 수 없도로.")
    }
    return request
}

struct ContextMemory {
    var text = ""
    var status = ""
    var lastInputID: String?
    var submissions = SubmissionLedger()
    var expanded: Set<String> = []
    var scrollTarget: String?
}
