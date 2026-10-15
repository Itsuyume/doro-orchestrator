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
            Text("작업 목록")
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
    @State private var selecting = false
    @State private var selected: Set<String> = []

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 14) {
                Text("열린 작업").font(.system(size: 13, weight: .semibold))
                if controller.pinnedContexts.isEmpty {
                    Text("열어 둔 대화가 없도로.").font(.system(size: 12)).foregroundStyle(.secondary)
                }
                ForEach(controller.pinnedContexts) { row($0, pinned: true) }
                if !controller.otherContexts.isEmpty { history }
                if !controller.lastRemoved.isEmpty {
                    Button("되돌리기 · \(controller.lastRemoved.count)개") { controller.undoHistoryRemoval() }
                        .buttonStyle(.plain).font(.system(size: 11)).foregroundStyle(.secondary)
                }
            }.padding(14).frame(maxWidth: .infinity, alignment: .leading)
                .onGeometryChange(for: Double.self) { Double($0.size.height) } action: { height in
                    if abs(height - controller.taskContentHeight) > 1 { controller.taskContentHeight = height }
                }
        }.background(.regularMaterial, in: RoundedRectangle(cornerRadius: 14))
            .onChange(of: controller.otherContexts.map(\.id)) { _, ids in selected.formIntersection(ids) }
    }

    private var history: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                Button { controller.historyExpanded.toggle() } label: {
                    Label("닫힌 작업과 지난 대화 · \(controller.otherContexts.count)",
                          systemImage: controller.historyExpanded ? "chevron.down" : "chevron.right")
                }.buttonStyle(.plain)
                Spacer(minLength: 0)
                Menu {
                    Button(selecting ? "선택 끝내기" : "선택해서 지우기") {
                        selecting.toggle(); selected = []; controller.historyExpanded = true
                    }
                    Button("모두 지우기", role: .destructive) { controller.removeHistory(controller.removableHistoryIDs) }
                        .disabled(controller.removableHistoryIDs.isEmpty)
                } label: { Image(systemName: "ellipsis") }.menuStyle(.borderlessButton).fixedSize()
                    .accessibilityLabel("지난 작업 관리")
            }.font(.system(size: 12))
            if controller.historyExpanded {
                if selecting { selectionBar }
                ForEach(controller.otherContexts) { row($0, pinned: false) }
            }
        }
    }

    private var selectionBar: some View {
        HStack {
            Button(selected == controller.removableHistoryIDs ? "선택 해제" : "전체 선택") {
                selected = selected == controller.removableHistoryIDs ? [] : controller.removableHistoryIDs
            }
            Spacer()
            Button("지우기 \(selected.count)", role: .destructive) { controller.removeHistory(selected); selected = [] }
                .disabled(selected.isEmpty)
            Button("취소") { selecting = false; selected = [] }
        }.font(.system(size: 11)).buttonStyle(.plain)
    }

    private func row(_ context: ChatContext, pinned: Bool) -> some View {
        HStack(spacing: 8) {
            if selecting && !pinned {
                Toggle("", isOn: Binding(get: { selected.contains(context.id) }, set: { value in
                    if value { selected.insert(context.id) } else { selected.remove(context.id) }
                })).toggleStyle(.checkbox).labelsHidden().accessibilityLabel(context.label + " 선택")
                    .disabled(!controller.removableHistoryIDs.contains(context.id))
            }
            VStack(alignment: .leading, spacing: 3) {
                Text(context.label).font(.system(size: 12, weight: .medium)).lineLimit(2)
                Text(context.needs_input ? "승인 필요" : context.status)
                    .font(.system(size: 10)).foregroundStyle(.secondary)
            }.frame(maxWidth: .infinity, alignment: .leading)
            if pinned || !selecting { Button(pinned ? "열기" : "다시 열기") { controller.openContext(context.id) } }
            if pinned {
                Button { controller.closeStack(context.id) } label: { Image(systemName: "xmark") }
                    .help("대화 목록에서 닫기 · 작업은 계속")
            } else if !selecting {
                Button(role: .destructive) { controller.removeHistory([context.id]) } label: { Image(systemName: "trash") }
                    .buttonStyle(.plain).accessibilityLabel(context.label + " 목록에서 지우기")
                    .help(context.finished ? "목록에서 지우기 · GPT 대화는 유지" : "진행 중인 작업은 유지")
                    .disabled(!controller.removableHistoryIDs.contains(context.id))
            }
        }.font(.system(size: 11))
    }
}
