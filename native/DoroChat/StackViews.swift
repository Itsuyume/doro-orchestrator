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
            Image(systemName: "rectangle.stack")
            Text("대화")
            Spacer(minLength: 6)
            if controller.approvalCount > 0 {
                Text("\(controller.approvalCount)").foregroundStyle(Color.orange)
            } else if controller.pinnedContexts.contains(where: { controller.unread($0) > 0 }) {
                Circle().fill(Color.orange).frame(width: 5, height: 5)
            }
            Image(systemName: "chevron.up").font(.system(size: 10, weight: .semibold)).foregroundStyle(.secondary)
        }.font(.system(size: 12, weight: .medium))
            .padding(.horizontal, 12).frame(width: 176, height: 34)
            .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 10))
    }
}

struct TaskManager: View {
    @ObservedObject var controller: ChatController
    @Environment(\.accessibilityReduceMotion) private var reducedMotion
    @State private var selecting = false
    @State private var selected: Set<String> = []
    @State private var activeSwipe: String?

    private var contentHeight: Double {
        TaskListLayout.contentHeight(open: controller.pinnedContexts.count, expanded: controller.openTasksExpanded,
            history: controller.otherContexts.count, historyExpanded: controller.historyExpanded,
            selecting: selecting, undo: !controller.lastRemoved.isEmpty)
    }

    var body: some View {
        List {
            openHeader
            if controller.openTasksExpanded {
                if controller.pinnedContexts.isEmpty {
                    Text("열어 둔 대화가 없도로.").font(.system(size: 12)).foregroundStyle(.secondary)
                        .frame(height: TaskListLayout.rowHeight).listRowSeparator(.hidden)
                }
                ForEach(controller.pinnedContexts) { row($0, pinned: true) }
            }
            if !controller.otherContexts.isEmpty {
                historyHeader
                if controller.historyExpanded {
                    if selecting { selectionBar }
                    ForEach(controller.otherContexts) { row($0, pinned: false) }
                }
            }
            if !controller.lastRemoved.isEmpty {
                Button { animate { controller.undoHistoryRemoval() } } label: {
                    Label("삭제 취소", systemImage: "arrow.uturn.backward")
                }.buttonStyle(.plain).font(.system(size: 11)).foregroundStyle(.secondary)
                    .help("최근 지운 대화 \(controller.lastRemoved.count)개를 목록에 복원")
                    .frame(height: TaskListLayout.controlHeight).listRowSeparator(.hidden)
            }
        }.listStyle(.plain).scrollContentBackground(.hidden)
            .environment(\.defaultMinListRowHeight, 0)
            .contentMargins(.vertical, TaskListLayout.verticalInset, for: .scrollContent)
            .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 14))
            .clipShape(RoundedRectangle(cornerRadius: 14))
            .onAppear { controller.taskContentHeight = contentHeight }
            .onChange(of: contentHeight) { _, value in controller.taskContentHeight = value }
            .onChange(of: controller.otherContexts.map(\.id)) { _, ids in selected.formIntersection(ids) }
            .onExitCommand {
                if activeSwipe != nil { activeSwipe = nil }
                else if selecting { selecting = false; selected = [] }
            }
    }

    private var openHeader: some View {
        Button { animate { activeSwipe = nil; controller.openTasksExpanded.toggle() } } label: {
            HStack {
                Text("열어 둔 대화").font(.system(size: 12, weight: .semibold))
                Spacer()
                Image(systemName: "chevron.up")
                    .rotationEffect(.degrees(controller.openTasksExpanded ? 0 : 180))
                    .frame(width: 28, height: 24).contentShape(Rectangle())
            }.contentShape(Rectangle())
        }.buttonStyle(.plain)
            .accessibilityLabel(controller.openTasksExpanded ? "열어 둔 대화 접기" : "열어 둔 대화 펼치기")
            .help(controller.openTasksExpanded ? "대화 접기" : "대화 펼치기")
            .frame(height: TaskListLayout.controlHeight)
            .listRowInsets(EdgeInsets(top: 0, leading: 14, bottom: 0, trailing: 10)).listRowSeparator(.hidden)
    }

    private var historyHeader: some View {
        HStack {
            Button { animate { activeSwipe = nil; controller.historyExpanded.toggle() } } label: {
                Label("지난 대화 · \(controller.otherContexts.count)",
                      systemImage: controller.historyExpanded ? "chevron.down" : "chevron.right")
                    .frame(maxWidth: .infinity, alignment: .leading).contentShape(Rectangle())
            }.buttonStyle(.plain)
            Menu {
                Button(selecting ? "선택 완료" : "선택") {
                    animate { activeSwipe = nil; selecting.toggle(); selected = []; controller.historyExpanded = true }
                }
                Button("모두 지우기", role: .destructive) { animate { controller.removeHistory(controller.removableHistoryIDs) } }
                    .disabled(controller.removableHistoryIDs.isEmpty)
            } label: { Image(systemName: "ellipsis") }.menuStyle(.borderlessButton).menuIndicator(.hidden).fixedSize()
                .accessibilityLabel("지난 대화 관리")
        }.font(.system(size: 12)).frame(height: TaskListLayout.controlHeight)
            .listRowInsets(EdgeInsets(top: 0, leading: 14, bottom: 0, trailing: 10)).listRowSeparator(.hidden)
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
            .listRowSeparator(.hidden)
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
