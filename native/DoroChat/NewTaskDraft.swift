import Foundation

struct NewTaskDraft: Codable, Equatable {
    var text = ""
    var id: String?
    var sourceSession: String?
    var queued = false
    var status = ""
    var retryable = false
    var creationFailed = false

    func validate() throws {
        guard text.utf8.count <= 200_000, status.utf8.count <= 20_000,
              id.map({ UUID(uuidString: $0) != nil }) ?? true,
              sourceSession.map({ UUID(uuidString: $0) != nil }) ?? true,
              !queued || (id != nil && sourceSession != nil) else {
            throw ChatReadError.failed("새 작업 초안의 저장 형식을 확인해줘도로.")
        }
    }
}

struct NewTaskDelivery: Decodable {
    let state: String
    let error: String
}

struct NewTaskRecord: Decodable {
    let id: String
    let state: String
    let session_id: String
    let thread_id: String
    let error: String
    let token: String?
    let delivery: NewTaskDelivery?
}

struct NewTaskReceipt: Decodable {
    let request: NewTaskRecord
    let delivery: NewTaskDelivery
}
