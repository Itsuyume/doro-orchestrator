import CoreGraphics
import Darwin
import Foundation

struct CursorWindow: Codable {
    let id: Int
    let pid: Int32
}

func cursors() throws -> [CursorWindow] {
    let list = CGWindowListCopyWindowInfo([.optionOnScreenOnly, .excludeDesktopElements], kCGNullWindowID)
    guard let list = list as? [[String: Any]] else {
        throw NSError(domain: "CursorCleanup", code: 4,
                      userInfo: [NSLocalizedDescriptionKey: "Window metadata is unavailable"])
    }
    return try list.compactMap { item in
        guard item[kCGWindowOwnerName as String] as? String == "ChatGPT Computer Use" else { return nil }
        guard let name = item[kCGWindowName as String] as? String else {
            throw NSError(domain: "CursorCleanup", code: 5,
                          userInfo: [NSLocalizedDescriptionKey: "Cursor owner window names are unavailable"])
        }
        guard name == "Software Cursor",
              let id = item[kCGWindowNumber as String] as? Int,
              let pid = item[kCGWindowOwnerPID as String] as? Int32 else { return nil }
        return CursorWindow(id: id, pid: pid)
    }
}

func executable(_ pid: Int32) throws -> String {
    var bytes = [CChar](repeating: 0, count: 4 * Int(MAXPATHLEN))
    guard proc_pidpath(pid, &bytes, UInt32(bytes.count)) > 0 else {
        throw NSError(domain: NSPOSIXErrorDomain, code: Int(errno))
    }
    return String(decoding: bytes.prefix { $0 != 0 }.map { UInt8(bitPattern: $0) }, as: UTF8.self)
}

func clean(_ windows: [CursorWindow]) throws {
    let expected = FileManager.default.homeDirectoryForCurrentUser
        .appendingPathComponent(".codex/computer-use/Codex Computer Use.app/Contents/MacOS/SkyComputerUseService").path
    for pid in Set(windows.map(\.pid)) {
        guard pid > 1, try executable(pid) == expected else {
            throw NSError(domain: "CursorCleanup", code: 1,
                          userInfo: [NSLocalizedDescriptionKey: "Cursor owner executable did not match; no signal sent"])
        }
        guard kill(pid, SIGTERM) == 0 else { throw NSError(domain: NSPOSIXErrorDomain, code: Int(errno)) }
    }
    for _ in 0..<20 {
        if try cursors().isEmpty { return }
        usleep(50_000)
    }
    throw NSError(domain: "CursorCleanup", code: 2,
                  userInfo: [NSLocalizedDescriptionKey: "Cursor windows remain after normal termination"])
}

do {
    let args = Array(CommandLine.arguments.dropFirst())
    guard args == ["--inspect"] || args == ["--cleanup"] else {
        throw NSError(domain: "CursorCleanup", code: 3,
                      userInfo: [NSLocalizedDescriptionKey: "Expected --inspect or --cleanup"])
    }
    let before = try cursors()
    if args == ["--cleanup"] { try clean(before) }
    let result = try JSONEncoder().encode(cursors())
    print(String(decoding: result, as: UTF8.self))
} catch {
    fputs("Cursor cleanup: \(error.localizedDescription)\n", stderr)
    exit(1)
}
