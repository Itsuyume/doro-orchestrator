import SwiftUI

struct ToolbarStatus: View {
    let text: String
    let active: Bool
    @Environment(\.accessibilityReduceMotion) private var reducedMotion
    @Environment(\.controlActiveState) private var controlActiveState
    @State private var contentWidth = 0.0
    @State private var viewportWidth = 0.0
    @State private var started = Date()
    @State private var pausedAt: Date?

    private var windowActive: Bool { active && controlActiveState != .inactive }
    private var moving: Bool {
        windowActive && !reducedMotion && viewportWidth > 0
            && contentWidth > viewportWidth + InterfaceMotion.statusOverflowTolerance
    }
    private var label: some View { Text(verbatim: text).font(.system(size: 11)).foregroundStyle(.secondary) }

    var body: some View {
        TimelineView(.animation(minimumInterval: 1.0 / 30, paused: !moving || pausedAt != nil)) { timeline in
            WindowDragHandle(label: text.isEmpty ? "대화창 이동" : text + " · 드래그하여 창 이동")
                .overlay(alignment: .leading) {
                    label.fixedSize(horizontal: true, vertical: false)
                        .onGeometryChange(for: Double.self) { Double($0.size.width) } action: { contentWidth = $0 }
                        .hidden().allowsHitTesting(false).accessibilityHidden(true)
                }
                .overlay(alignment: .leading) {
                    visibleLabel(at: pausedAt ?? timeline.date)
                        .allowsHitTesting(false).accessibilityHidden(true)
                }.clipped().frame(height: 24)
                .onGeometryChange(for: Double.self) { Double($0.size.width) } action: { viewportWidth = $0; restart() }
        }.help(text)
            .onHover { hovering in
                if hovering { pausedAt = Date(); return }
                guard let pausedAt else { return }
                started = started.addingTimeInterval(Date().timeIntervalSince(pausedAt))
                self.pausedAt = nil
            }
            .onChange(of: text) { _, _ in restart() }
            .onChange(of: windowActive) { _, isActive in
                if !isActive { pausedAt = nil }
                restart()
            }
            .onChange(of: reducedMotion) { _, _ in restart() }
    }

    @ViewBuilder private func visibleLabel(at date: Date) -> some View {
        if moving {
            HStack(spacing: InterfaceMotion.statusGap) {
                label
                label
            }.fixedSize(horizontal: true, vertical: false)
                .offset(x: InterfaceMotion.statusOffset(elapsed: date.timeIntervalSince(started),
                    contentWidth: contentWidth, viewportWidth: viewportWidth, reduced: reducedMotion))
        } else {
            label.lineLimit(1).truncationMode(.tail).frame(maxWidth: .infinity, alignment: .leading)
        }
    }

    private func restart() {
        started = Date()
        if pausedAt != nil { pausedAt = started }
    }
}
