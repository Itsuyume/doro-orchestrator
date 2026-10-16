import Foundation

struct NativeStateFile {
    let path: URL
    let maxBytes: Int

    func read() throws -> Data? {
        guard try validatedExists() else { return nil }
        return try Data(contentsOf: path)
    }

    func write(_ data: Data) throws {
        _ = try validatedExists()
        guard data.count <= maxBytes else { throw ChatReadError.failed("설정 저장 크기를 초과했도로.") }
        try data.write(to: path, options: .atomic)
        try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: path.path)
    }

    private func validatedExists() throws -> Bool {
        let attributes: [FileAttributeKey: Any]
        do { attributes = try FileManager.default.attributesOfItem(atPath: path.path) }
        catch let error as CocoaError where error.code == .fileReadNoSuchFile { return false }
        guard attributes[.type] as? FileAttributeType == .typeRegular,
              let size = attributes[.size] as? NSNumber, size.intValue <= maxBytes else {
            throw ChatReadError.failed("설정 파일이 일반 파일이 아니거나 너무 크도로.")
        }
        return true
    }
}
