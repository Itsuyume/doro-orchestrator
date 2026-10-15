import Foundation

enum ApprovalDecision: String, Hashable, Sendable { case approve, reject }

struct ChatMessage: Decodable, Identifiable, Sendable {
    let id: String
    let sender: String
    let phase: String
    let text: String
    let state: String
    let incoming: String
    let main: Bool
    let from_user: Bool
}

struct Conversation: Decodable, Sendable {
    let version: Int
    let session_id: String
    let title: String
    let status: String
    let usage: String
    let messages: [ChatMessage]
    let reply_hint: String
    let input_enabled: Bool
    let checkpoint_id: String
    let label: String
    let contexts: [ChatContext]
    let claude_enabled: Bool
    let agy_enabled: Bool
    let approval: ChatApproval?
    let model_selection: ModelSelection?
}

struct ModelSelection: Decodable, Sendable {
    let model: String
    let effort: String
    let actual_model: String
    let models: [[String]]
    let efforts: [[String]]
}

struct ChatApproval: Decodable, Equatable, Sendable {
    let checkpoint_id: String
    let kind: String
    let brief: String
    let details: String
    let response_pending: Bool
    let response_decision: String?
}

struct ChatContext: Decodable, Identifiable, Sendable {
    let session_id: String
    let label: String
    let status: String
    let needs_input: Bool
    let event_count: Int
    let queued_inputs: Int
    let finished: Bool
    var id: String { session_id }
}

enum ChatReadError: LocalizedError {
    case failed(String)
    var errorDescription: String? {
        switch self {
        case .failed(let message): return message
        }
    }
}

func localCommand(_ command: [String], input: Data? = nil, capability: String? = nil) throws -> Data {
    let process = Process()
    process.executableURL = URL(fileURLWithPath: command[0])
    process.arguments = Array(command.dropFirst())
    if let capability {
        var environment = ProcessInfo.processInfo.environment
        environment["DORO_CHAT_CAPABILITY"] = capability
        process.environment = environment
    }
    let output = Pipe()
    let errors = Pipe()
    process.standardOutput = output
    process.standardError = errors
    let incoming = Pipe()
    process.standardInput = input == nil ? FileHandle.nullDevice : incoming
    try process.run()
    if let input {
        try incoming.fileHandleForWriting.write(contentsOf: input)
        try incoming.fileHandleForWriting.close()
    }
    let data = output.fileHandleForReading.readDataToEndOfFile()
    let errorData = errors.fileHandleForReading.readDataToEndOfFile()
    process.waitUntilExit()
    guard process.terminationStatus == 0 else {
        throw ChatReadError.failed(String(decoding: errorData, as: UTF8.self))
    }
    return data
}

func readConversation(_ command: [String]) throws -> Conversation {
    let view = try JSONDecoder().decode(Conversation.self, from: localCommand(command))
    guard view.version == 1 else { throw ChatReadError.failed("표시 형식 버전을 확인할 수 없도로.") }
    return view
}

func postInput(_ command: [String], text: String, checkpoint: String, id: String, decision: String, token: String) throws {
    let data = try JSONSerialization.data(withJSONObject: ["text": text, "checkpoint_id": checkpoint,
                                                           "client_id": id, "decision": decision])
    _ = try localCommand(Array(command.dropLast()) + ["--post"], input: data, capability: token)
}
