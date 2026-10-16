import SwiftUI

struct ProviderLight: View {
    let name: String
    let enabled: Bool?

    var body: some View {
        HStack(spacing: 4) {
            Circle().fill(enabled == true ? Color.green : Color.gray.opacity(0.55)).frame(width: 7, height: 7)
            Text(name).foregroundStyle(.secondary)
        }.font(.system(size: 11))
            .accessibilityElement(children: .ignore)
            .accessibilityLabel(name + (enabled == true ? " 켜짐" : enabled == false ? " 꺼짐" : " 확인 중"))
            .help(name + (enabled == true ? " · 협업 참여 켜짐" : enabled == false ? " · 협업 참여 꺼짐" : " · 읽는 중"))
    }
}

struct StackTray: View {
    @ObservedObject var controller: ChatController

    var body: some View {
        HStack(spacing: 8) {
            HStack(spacing: 6) {
                Image(systemName: "rectangle.stack")
                Text("대화").lineLimit(1).fixedSize()
                Spacer(minLength: 0)
            }.overlay { WindowDragHandle(label: "대화 펼치기", onTap: { controller.toggleChat() }) }
            if controller.approvalCount > 0 {
                Text(controller.approvalCount > 99 ? "99+" : "\(controller.approvalCount)").foregroundStyle(Color.orange)
                    .monospacedDigit().lineLimit(1).fixedSize()
                    .accessibilityLabel("승인 대기 \(controller.approvalCount)개")
            } else if controller.pinnedContexts.contains(where: { controller.unread($0) > 0 }) {
                Circle().fill(Color.orange).frame(width: 5, height: 5)
            }
            Button { controller.toggleChat() } label: {
                Image(systemName: "chevron.down").frame(width: 24, height: 24).contentShape(Rectangle())
            }.buttonStyle(.plain).help("대화 펼치기").accessibilityLabel("대화 펼치기")
            Button { controller.minimizeCurrent() } label: {
                Image(systemName: "chevron.up").frame(width: 24, height: 24).contentShape(Rectangle())
            }.buttonStyle(.plain).help("메뉴 막대로 숨기기").accessibilityLabel("메뉴 막대로 숨기기 · 협업 유지")
        }.font(.system(size: 12, weight: .medium))
            .padding(.horizontal, 10).frame(width: 212, height: 34)
            .background(ChatSurface.panel, in: RoundedRectangle(cornerRadius: 10))
            .overlay { RoundedRectangle(cornerRadius: 10).strokeBorder(ChatSurface.border, lineWidth: 0.75) }
    }
}

struct TaskManager: View {
    @ObservedObject var controller: ChatController
    @Environment(\.accessibilityReduceMotion) private var reducedMotion
    private var selecting: Bool {
        get { controller.historySelecting }
        nonmutating set { controller.historySelecting = newValue }
    }
    @State private var selected: Set<String> = []
    @State private var activeSwipe: String?

    var body: some View {
        VStack(spacing: 0) {
            conversations
            if !controller.otherContexts.isEmpty {
                historyHeader
                if controller.historyExpanded && selecting { selectionBar }
            }
            if !controller.lastRemoved.isEmpty {
                Button { animate { controller.undoHistoryRemoval() } } label: {
                    Label("삭제 취소", systemImage: "arrow.uturn.backward")
                }.buttonStyle(.plain).font(.system(size: 11)).foregroundStyle(.secondary)
                    .help("최근 지운 대화 \(controller.lastRemoved.count)개를 목록에 복원")
                    .frame(maxWidth: .infinity, alignment: .leading).frame(height: TaskListLayout.controlHeight)
                    .padding(.horizontal, 14)
            }
        }.background(ChatSurface.panel, in: RoundedRectangle(cornerRadius: 14))
            .clipShape(RoundedRectangle(cornerRadius: 14))
            .onChange(of: controller.otherContexts.map(\.id)) { _, ids in
                selected.formIntersection(ids)
                if ids.isEmpty { selecting = false }
            }
            .onExitCommand {
                if activeSwipe != nil { activeSwipe = nil }
                else if selecting { selecting = false; selected = [] }
            }
    }

    private var conversations: some View {
        ScrollViewReader { proxy in
            let boundary = controller.completedBoundaryID
            List {
                if controller.pinnedContexts.isEmpty && controller.otherContexts.isEmpty {
                    Text("대화가 없도로.").font(.system(size: 12)).foregroundStyle(.secondary)
                        .frame(height: TaskListLayout.rowHeight).listRowSeparator(.hidden).listRowBackground(Color.clear)
                }
                ForEach(controller.listedContexts) { context in
                    row(context, pinned: controller.stacks.contains(context.id)).id(context.id)
                        .overlay(alignment: .top) {
                            if context.id == boundary { Divider().padding(.horizontal, 8).accessibilityHidden(true) }
                        }
                }
            }.listStyle(.plain).scrollContentBackground(.hidden)
                .environment(\.defaultMinListRowHeight, 1)
                .contentMargins(.vertical, 0, for: .scrollContent)
                .scrollIndicators(.visible, axes: .vertical).scrollBounceBehavior(.basedOnSize)
                .frame(height: TaskListLayout.rowViewportHeight(open: controller.pinnedContexts.count,
                    history: controller.otherContexts.count, historyExpanded: controller.historyExpanded)
                    - 2 * TaskListLayout.verticalInset)
                .padding(.vertical, TaskListLayout.verticalInset)
                .onScrollPhaseChange { _, phase in if phase != .idle { activeSwipe = nil } }
                .onChange(of: controller.historyExpanded) { _, expanded in
                    guard expanded, let first = controller.otherContexts.first else { return }
                    DispatchQueue.main.async { proxy.scrollTo(first.id, anchor: .top) }
                }
        }
    }

    private var historyHeader: some View {
        HStack {
            Button { animate { activeSwipe = nil; controller.historyExpanded.toggle() } } label: {
                Label("지난 대화 · \(controller.otherContexts.count)",
                      systemImage: controller.historyExpanded ? "chevron.up" : "chevron.down")
                    .frame(maxWidth: .infinity, alignment: .leading).contentShape(Rectangle())
            }.buttonStyle(.plain)
                .help(controller.historyExpanded ? "지난 대화 접기" : "지난 대화 펼치기")
                .accessibilityValue(controller.historyExpanded ? "펼쳐짐" : "접힘")
            Menu {
                Button(selecting ? "선택 완료" : "선택") {
                    animate { activeSwipe = nil; selecting.toggle(); selected = []; controller.historyExpanded = true }
                }
                Button("모두 지우기", role: .destructive) { animate { controller.removeHistory(controller.removableHistoryIDs) } }
                    .disabled(controller.removableHistoryIDs.isEmpty)
            } label: { Image(systemName: "ellipsis") }.menuStyle(.borderlessButton).menuIndicator(.hidden).fixedSize()
                .accessibilityLabel("지난 대화 관리")
        }.font(.system(size: 12)).frame(height: TaskListLayout.controlHeight)
            .padding(.leading, 14).padding(.trailing, 10)
    }

    private var selectionBar: some View {
        HStack {
            Button(selected == controller.removableHistoryIDs ? "선택 해제" : "전체 선택") {
                selected = selected == controller.removableHistoryIDs ? [] : controller.removableHistoryIDs
            }
            Spacer()
            Button("지우기 \(selected.count)", role: .destructive) { animate { controller.removeHistory(selected); selected = [] } }
                .disabled(selected.isEmpty)
            Button("취소") { selecting = false; selected = [] }
        }.font(.system(size: 11)).buttonStyle(.plain).frame(height: TaskListLayout.controlHeight)
            .padding(.horizontal, 14)
    }

    private func row(_ context: ChatContext, pinned: Bool) -> some View {
        TaskRow(context: context, pinned: pinned, selecting: selecting && !pinned,
            selected: selected.contains(context.id), removable: controller.removableHistoryIDs.contains(context.id),
            onOpen: { controller.openContext(context.id) },
            onClose: {
                animate { if pinned { controller.closeStack(context.id) } else { controller.removeHistory([context.id]) } }
                return pinned ? !controller.stacks.contains(context.id) : !controller.stacks.isListed(context.id)
            },
            onSelect: { if selected.contains(context.id) { selected.remove(context.id) } else { selected.insert(context.id) } },
            activeSwipe: $activeSwipe)
    }

    private func animate(_ change: () -> Void) { withAnimation(InterfaceMotion.animation(reduced: reducedMotion), change) }
}
