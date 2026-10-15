import AppKit

struct Registration: Decodable {
    let version: Int
    let project_root: String
    let python_executable: String
    let launch_path: String
}

func openWindow() throws {
    let path = FileManager.default.homeDirectoryForCurrentUser
        .appendingPathComponent(".codex/skill-docs/doro-orchestration.json")
    let attributes = try FileManager.default.attributesOfItem(atPath: path.path)
    guard attributes[.type] as? FileAttributeType == .typeRegular,
          let size = attributes[.size] as? NSNumber, size.intValue <= 16_000 else {
        throw NSError(domain: "DoroOpen", code: 1, userInfo: [NSLocalizedDescriptionKey: "실행기 등록 파일을 확인해줘도로."])
    }
    let registration = try JSONDecoder().decode(Registration.self, from: Data(contentsOf: path))
    guard registration.version == 1, !registration.launch_path.isEmpty else {
        throw NSError(domain: "DoroOpen", code: 2, userInfo: [NSLocalizedDescriptionKey: "실행기 바로가기를 다시 설치해줘도로."])
    }
    let process = Process()
    process.executableURL = URL(fileURLWithPath: registration.python_executable)
    process.arguments = [URL(fileURLWithPath: registration.project_root).appendingPathComponent("doro").path, "window", "open"]
    let safe = Set(["HOME", "TMPDIR", "LANG", "LC_ALL", "LC_CTYPE", "USER", "LOGNAME", "SHELL"])
    var environment = ProcessInfo.processInfo.environment.filter { safe.contains($0.key) }
    environment["PATH"] = registration.launch_path
    process.environment = environment
    process.standardInput = FileHandle.nullDevice
    process.standardOutput = FileHandle.nullDevice
    let errors = Pipe()
    process.standardError = errors
    try process.run()
    let message = errors.fileHandleForReading.readDataToEndOfFile()
    process.waitUntilExit()
    guard process.terminationStatus == 0 else {
        throw NSError(domain: "DoroOpen", code: Int(process.terminationStatus),
                      userInfo: [NSLocalizedDescriptionKey: String(decoding: message.suffix(1500), as: UTF8.self)])
    }
}

do { try openWindow() }
catch {
    let application = NSApplication.shared
    application.setActivationPolicy(.accessory)
    application.activate(ignoringOtherApps: true)
    let alert = NSAlert()
    alert.messageText = "작업창을 열지 못했도로"
    alert.informativeText = error.localizedDescription
    alert.addButton(withTitle: "확인")
    alert.runModal()
    exit(1)
}
