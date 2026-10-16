import AppKit
import Carbon

private let doroOpenNotification = Notification.Name("local.doro.open-task-window")
private let doroShortcutSignature: OSType = 0x446F726F

private func doroShortcutEvent(_ call: EventHandlerCallRef?, _ event: EventRef?, _ raw: UnsafeMutableRawPointer?) -> OSStatus {
    guard let event else { return OSStatus(eventNotHandledErr) }
    var identity = EventHotKeyID()
    let result = GetEventParameter(event, EventParamName(kEventParamDirectObject), EventParamType(typeEventHotKeyID),
                                  nil, MemoryLayout<EventHotKeyID>.size, nil, &identity)
    guard result == noErr, identity.signature == doroShortcutSignature, identity.id == 1 else { return OSStatus(eventNotHandledErr) }
    NotificationCenter.default.post(name: doroOpenNotification, object: nil)
    return noErr
}

@MainActor
final class GlobalShortcut {
    private let onPress: () -> Void
    private var handler: EventHandlerRef?
    private var key: EventHotKeyRef?
    private var observer: (any NSObjectProtocol)?

    init(onPress: @escaping () -> Void) throws {
        self.onPress = onPress
        var kind = EventTypeSpec(eventClass: OSType(kEventClassKeyboard), eventKind: UInt32(kEventHotKeyPressed))
        let result = InstallEventHandler(GetApplicationEventTarget(), doroShortcutEvent, 1, &kind,
                                         nil, &handler)
        guard result == noErr else { throw ChatReadError.failed("단축키 연결 실패 (\(result))") }
        let identity = EventHotKeyID(signature: doroShortcutSignature, id: 1)
        let registered = RegisterEventHotKey(UInt32(kVK_Return), UInt32(controlKey | optionKey), identity,
                                             GetApplicationEventTarget(), 0, &key)
        guard registered == noErr else {
            stop()
            if registered == eventHotKeyExistsErr {
                throw ChatReadError.failed("⌃⌥Enter를 다른 앱에서 사용 중이도로. 메뉴 막대나 바로가기로 열어줘도로.")
            }
            throw ChatReadError.failed("⌃⌥Enter 단축키를 등록하지 못했도로 (\(registered)).")
        }
        observer = NotificationCenter.default.addObserver(forName: doroOpenNotification, object: nil, queue: .main) { [weak self] _ in
            Task { @MainActor [weak self] in self?.onPress() }
        }
    }

    func stop() {
        if let observer { NotificationCenter.default.removeObserver(observer) }
        if let key { UnregisterEventHotKey(key) }
        if let handler { RemoveEventHandler(handler) }
        key = nil
        handler = nil
        observer = nil
    }
}
