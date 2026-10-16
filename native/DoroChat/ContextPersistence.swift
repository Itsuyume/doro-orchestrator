import Foundation

@MainActor
final class ContextPersistence {
    let store: ContextStateStore
    let initialState: ContextState
    private(set) var loadError: String = ""

    init(store: ContextStateStore) {
        self.store = store
        do { initialState = try store.load() }
        catch { initialState = ContextState(); loadError = "초안을 읽지 못했도로. 원본 보관 후 복구할 수 있도로: \(error.localizedDescription)" }
    }

    func save(_ state: ContextState) throws {
        guard loadError.isEmpty else { throw ChatReadError.failed(loadError) }
        try store.save(state)
    }

    func recover(_ state: ContextState) throws {
        let source = store.file.path
        let attributes = try FileManager.default.attributesOfItem(atPath: source.path)
        guard attributes[.type] as? FileAttributeType == .typeRegular else {
            throw ChatReadError.failed("초안 파일이 일반 파일이 아니므로 자동으로 옮기지 않았도로.")
        }
        let backup = source.deletingPathExtension().appendingPathExtension("backup-\(UUID().uuidString).json")
        try FileManager.default.moveItem(at: source, to: backup)
        do { try store.save(state) }
        catch {
            let saveError = error
            do { try FileManager.default.moveItem(at: backup, to: source) }
            catch { throw ChatReadError.failed("복구 저장에 실패했도로. 원본 보관 위치: \(backup.path) · \(saveError.localizedDescription)") }
            throw saveError
        }
        loadError = ""
    }
}
