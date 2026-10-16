import SwiftUI

struct TaskRow: View {
    let context: ChatContext
    let pinned: Bool
    let selecting: Bool
    let selected: Bool
    let removable: Bool
    let onOpen: () -> Void
    let onClose: () -> Bool
    let onSelect: () -> Void
    @Binding var activeSwipe: String?
    @Environment(\.accessibilityReduceMotion) private var reducedMotion
    @GestureState private var dragging = false
    @State private var swipe = RowSwipeState()
    @State private var rowWidth = CGFloat.zero
    private var canSwipe: Bool { !selecting && (pinned || removable) }

    var body: some View {
        ZStack(alignment: .trailing) {
            if canSwipe {
                Button { close() } label: {
                    Label(pinned ? "닫기" : "지우기", systemImage: pinned ? "xmark" : "trash")
                        .font(.system(size: 11)).labelStyle(.titleAndIcon).frame(width: 72, height: TaskListLayout.rowHeight)
                        .background(pinned ? Color.gray.opacity(0.16) : Color.red.opacity(0.15))
                }.buttonStyle(.plain)
                    .mask(alignment: .trailing) { Rectangle().frame(width: max(0, -swipe.offset)) }
                    .allowsHitTesting(swipe.offset < 0).accessibilityHidden(swipe.offset == 0)
            }
            content.offset(x: swipe.offset)
        }.frame(height: TaskListLayout.rowHeight).clipped()
            .onGeometryChange(for: CGFloat.self) { $0.size.width } action: { rowWidth = $0 }
            .highPriorityGesture(mouseSwipe, including: canSwipe ? .all : .subviews)
            .onChange(of: dragging) { _, active in
                if !active && swipe.dragging { withAnimation(InterfaceMotion.animation(reduced: reducedMotion)) { swipe.cancel() } }
            }
            .onChange(of: canSwipe) { _, _ in swipe.reset() }
            .onChange(of: pinned) { _, _ in resetSwipe() }
            .onChange(of: activeSwipe) { _, value in if value != context.id { resetSwipe() } }
            .onHover { inside in if inside && activeSwipe != context.id { activeSwipe = nil } }
            .onExitCommand { activeSwipe = nil; resetSwipe() }
            .listRowInsets(EdgeInsets(top: 0, leading: 6, bottom: 0, trailing: 6))
            .listRowSeparator(.hidden)
            .swipeActions(edge: .trailing, allowsFullSwipe: true) {
                if canSwipe {
                    Button(role: pinned ? nil : .destructive) { _ = onClose() } label: {
                        Label(pinned ? "닫기" : "지우기", systemImage: pinned ? "xmark" : "trash")
                    }.tint(pinned ? .gray : .red)
                }
            }
    }

    private var content: some View {
        HStack(spacing: 4) {
            if selecting {
                Toggle("", isOn: Binding(get: { selected }, set: { _ in onSelect() }))
                    .toggleStyle(.checkbox).labelsHidden().accessibilityLabel(context.label + " 선택")
                    .disabled(!removable)
            }
            Button(action: activate) {
                VStack(alignment: .leading, spacing: 2) {
                    Text(context.label).font(.system(size: 13, weight: .medium)).lineLimit(2)
                    Text(context.needs_input ? "승인 필요" : context.status)
                        .font(.system(size: 11)).foregroundStyle(.secondary)
                }.frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .leading)
                    .padding(.horizontal, 8).contentShape(Rectangle())
            }.buttonStyle(TaskRowButtonStyle())
                .disabled(selecting && !removable)
                .accessibilityLabel(context.label + " · " + (context.needs_input ? "승인 필요" : context.status))
                .accessibilityHint(selecting ? "선택 전환" : "대화 열기")
            if !selecting {
                Button { _ = onClose() } label: { Image(systemName: pinned ? "xmark" : "trash").frame(width: 28, height: 28) }
                    .buttonStyle(.borderless)
                    .accessibilityLabel(context.label + (pinned ? " 닫기" : " 목록에서 지우기"))
                    .help(pinned ? "대화 닫기 · 작업은 계속" : "목록에서 지우기 · GPT 대화는 유지")
                    .disabled(!pinned && !removable)
                    .opacity(swipe.offset == 0 ? 1 : 0).allowsHitTesting(swipe.offset == 0)
                    .accessibilityHidden(swipe.offset != 0)
            }
        }.frame(height: TaskListLayout.rowHeight)
    }

    private var mouseSwipe: some Gesture {
        DragGesture(minimumDistance: 12)
            .updating($dragging) { _, active, _ in active = true }
            .onChanged { value in
                swipe.update(x: value.translation.width, y: value.translation.height, width: rowWidth)
                if swipe.offset < 0 && activeSwipe != context.id { activeSwipe = context.id }
            }
            .onEnded { _ in
                withAnimation(InterfaceMotion.animation(reduced: reducedMotion)) {
                    if swipe.finish(width: rowWidth) { close() }
                }
            }
    }

    private func close() {
        if !onClose() { resetSwipe() }
    }

    private func activate() {
        if swipe.offset < 0 { activeSwipe = nil; resetSwipe(); return }
        if selecting { onSelect() } else { onOpen() }
    }

    private func resetSwipe() {
        withAnimation(InterfaceMotion.animation(reduced: reducedMotion)) { swipe.reset() }
    }
}

private struct TaskRowButtonStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .background(configuration.isPressed ? Color.primary.opacity(0.065) : .clear,
                        in: RoundedRectangle(cornerRadius: 7))
    }
}
