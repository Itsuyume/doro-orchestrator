import AppKit
import SwiftUI

@MainActor
final class PetCanvas: NSView {
    var onTap: (() -> Void)?
    var onRestore: (() -> Void)?
    var image: CGImage? { didSet { frames.removeAll() } }
    var activity = PetAnimation.idle { didSet { if oldValue != activity { resetAnimation() } } }
    private var timer: Timer?
    private var drag = WindowDragState()
    private var moving: PetAnimation?
    private var look: SpriteStep?
    private var frameIndex = 0
    private var frameBegan = ProcessInfo.processInfo.systemUptime
    private var steps = PetAnimation.idle.steps
    private var frames: [Int: NSImage] = [:]
    private var lastPointer = NSEvent.mouseLocation
    private var lastPointerMoved = 0.0
    private var hoverBegan = -10.0
    override var mouseDownCanMoveWindow: Bool { false }

    override init(frame: NSRect) {
        super.init(frame: frame)
        setAccessibilityElement(true)
        setAccessibilityRole(.button)
        setAccessibilityLabel("도로 펫 · 클릭: 대화 접기 또는 펼치기 · 드래그: 함께 이동")
        toolTip = "마우스 올리기: 도로 반응 · 클릭: 접기/펼치기 · 드래그: 함께 이동"
        let menu = NSMenu()
        menu.addItem(withTitle: "대화 접기 / 펼치기", action: #selector(toggleChat), keyEquivalent: "")
        menu.addItem(.separator())
        menu.addItem(withTitle: "공식 도로로 돌아가기", action: #selector(restorePet), keyEquivalent: "")
        for item in menu.items { item.target = self }
        self.menu = menu
    }

    required init?(coder: NSCoder) { super.init(coder: coder) }

    override func updateTrackingAreas() {
        super.updateTrackingAreas()
        for area in trackingAreas { removeTrackingArea(area) }
        addTrackingArea(NSTrackingArea(rect: bounds,
            options: [.mouseEnteredAndExited, .mouseMoved, .activeAlways, .inVisibleRect],
            owner: self, userInfo: nil))
    }

    override func mouseEntered(with event: NSEvent) {
        hoverBegan = ProcessInfo.processInfo.systemUptime
        mouseMoved(with: event)
    }
    override func mouseExited(with event: NSEvent) { look = nil; resetAnimation() }
    override func mouseMoved(with event: NSEvent) {
        lastPointerMoved = ProcessInfo.processInfo.systemUptime
        updateGaze(now: lastPointerMoved)
        needsDisplay = true
    }

    private func updateGaze(now: Double) {
        guard let window else { return }
        let point = NSEvent.mouseLocation
        if hypot(point.x - lastPointer.x, point.y - lastPointer.y) > 1 {
            lastPointerMoved = now
            lastPointer = point
        }
        guard now - lastPointerMoved < 1.6 else { look = nil; return }
        let local = convert(window.convertPoint(fromScreen: point), from: nil)
        look = PetAnimation.look(x: local.x - bounds.midX, y: local.y - bounds.midY)
    }

    override func viewDidMoveToWindow() {
        timer?.invalidate()
        guard window != nil else { return }
        let animation = Timer(timeInterval: 1.0 / 60, repeats: true) { [weak self] _ in
            Task { @MainActor [weak self] in
                guard let self else { return }
                let now = ProcessInfo.processInfo.systemUptime
                updateGaze(now: now)
                if now - frameBegan >= steps[frameIndex].seconds {
                    frameBegan += steps[frameIndex].seconds
                    frameIndex = (frameIndex + 1) % steps.count
                    if now - frameBegan > 1 { frameBegan = now }
                }
                needsDisplay = true
            }
        }
        timer = animation
        RunLoop.main.add(animation, forMode: .common)
    }

    override func draw(_ dirtyRect: NSRect) {
        let now = ProcessInfo.processInfo.systemUptime
        let hoverFrames = PetAnimation.completed.steps
        let hovering = moving == nil && now - hoverBegan < 0.6
        let step = hovering ? hoverFrames[min(4, Int((now - hoverBegan) / 0.12))]
                            : moving == nil ? look ?? steps[frameIndex] : steps[frameIndex]
        guard let current = sprite(step) else { return }
        let blend = look == nil && !hovering ? min(1, max(0, (now - frameBegan - step.seconds + 0.07) / 0.07)) : 0
        let area = bounds.insetBy(dx: 1.5, dy: 1.5).offsetBy(dx: 0, dy: sin(now * 2) * 0.7)
        NSGraphicsContext.current?.imageInterpolation = .high
        NSGraphicsContext.current?.cgContext.beginTransparencyLayer(auxiliaryInfo: nil)
        current.draw(in: area, from: .zero, operation: .copy, fraction: 1 - blend)
        if blend > 0, let next = sprite(steps[(frameIndex + 1) % steps.count]) {
            next.draw(in: area, from: .zero, operation: .plusLighter, fraction: blend)
        }
        NSGraphicsContext.current?.cgContext.endTransparencyLayer()
    }

    private func sprite(_ step: SpriteStep) -> NSImage? {
        let key = step.row * 8 + step.column
        if let cached = frames[key] { return cached }
        guard let cell = image?.cropping(to: CGRect(x: step.column * 192, y: step.row * 208, width: 192, height: 208)) else { return nil }
        let value = NSImage(cgImage: cell, size: NSSize(width: 192, height: 208))
        frames[key] = value
        return value
    }

    override func mouseDown(with event: NSEvent) {
        guard let window else { return }
        drag.begin(at: window.convertPoint(toScreen: event.locationInWindow), origin: window.frame.origin)
    }

    override func mouseDragged(with event: NSEvent) {
        guard let window else { return }
        let point = window.convertPoint(toScreen: event.locationInWindow)
        guard let origin = drag.move(to: point) else { return }
        let next = origin.x >= window.frame.origin.x ? PetAnimation.movingRight : .movingLeft
        if moving != next { moving = next; resetAnimation() }
        window.setFrameOrigin(origin)
    }

    override func mouseUp(with event: NSEvent) {
        moving = nil
        resetAnimation()
        if drag.finish() { onTap?() }
    }

    private func resetAnimation() {
        steps = (moving ?? activity).steps
        frameIndex = 0
        frameBegan = ProcessInfo.processInfo.systemUptime
        needsDisplay = true
    }

    @objc private func toggleChat() { onTap?() }
    @objc private func restorePet() { onRestore?() }
    override func accessibilityPerformPress() -> Bool { onTap?(); return true }
}

struct PetHandle: NSViewRepresentable {
    @ObservedObject var controller: ChatController

    func makeNSView(context: Context) -> PetCanvas {
        let view = PetCanvas(frame: .zero)
        if let path = ProcessInfo.processInfo.environment["DORO_CHAT_PET_SPRITE"],
           let atlas = NSImage(contentsOfFile: path)?.cgImage(forProposedRect: nil, context: nil, hints: nil) {
            view.image = atlas
        }
        view.onTap = { controller.toggleChat() }
        view.onRestore = { controller.requestOfficialPet() }
        return view
    }

    func updateNSView(_ view: PetCanvas, context: Context) {
        view.activity = .activity(controller.conversation?.status ?? "")
    }
}
