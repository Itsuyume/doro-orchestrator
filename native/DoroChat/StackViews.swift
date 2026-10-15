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
        VStack(alignment: .leading, spacing: 4) {
            ForEach(controller.pinnedContexts.prefix(3)) { context in
                HStack(spacing: 0) {
                    HStack(spacing: 5) {
                        Image(systemName: context.needs_input ? "exclamationmark.circle.fill" : "bubble.left")
                            .foregroundStyle(context.needs_input ? Color.orange : Color.secondary)
                        Text(context.label).lineLimit(1).truncationMode(.tail)
                        Spacer(minLength: 0)
                        if controller.unread(context) > 0 { Circle().fill(Color.orange).frame(width: 5, height: 5) }
                    }.padding(.leading, 8).padding(.vertical, 6)
                        .overlay { WindowDragHandle(label: context.label + " · 클릭해서 열기 · 드래그해서 이동",
                                                    onTap: { controller.openContext(context.id) }) }
                    Button { controller.closeStack(context.id) } label: {
                        Image(systemName: "xmark").frame(width: 26, height: 26).contentShape(Rectangle())
                    }.buttonStyle(.plain).accessibilityLabel(context.label + " 닫기")
                }.font(.system(size: 11, weight: .medium))
                    .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 9))
            }
            if controller.pinnedContexts.count > 3 {
                Button("+\(controller.pinnedContexts.count - 3)개 작업") { controller.showTasks() }
                    .buttonStyle(.plain).font(.system(size: 10))
            }
        }.frame(width: controller.display == .panel ? 220 : 156)
    }
}

struct TaskManager: View {
    @ObservedObject var controller: ChatController

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 14) {
                Text("열린 작업").font(.system(size: 13, weight: .semibold))
                if controller.pinnedContexts.isEmpty {
                    Text("열어 둔 대화가 없도로.").font(.system(size: 12)).foregroundStyle(.secondary)
                }
                ForEach(controller.pinnedContexts) { row($0, pinned: true) }
                if !controller.otherContexts.isEmpty {
                    DisclosureGroup("닫힌 작업과 지난 대화 · \(controller.otherContexts.count)") {
                        ForEach(controller.otherContexts) { row($0, pinned: false).padding(.top, 10) }
                    }.font(.system(size: 12))
                }
                Text("대화를 닫아도 작업과 승인 요청은 남아 있도로.")
                    .font(.system(size: 11)).foregroundStyle(.secondary).padding(.top, 6)
            }.padding(14).frame(maxWidth: .infinity, alignment: .leading)
        }.background(.regularMaterial, in: RoundedRectangle(cornerRadius: 14))
    }

    private func row(_ context: ChatContext, pinned: Bool) -> some View {
        HStack(spacing: 8) {
            VStack(alignment: .leading, spacing: 3) {
                Text(context.label).font(.system(size: 12, weight: .medium)).lineLimit(2)
                Text(context.needs_input ? "승인 필요" : context.status)
                    .font(.system(size: 10)).foregroundStyle(.secondary)
            }.frame(maxWidth: .infinity, alignment: .leading)
            Button(pinned ? "열기" : "다시 열기") { controller.openContext(context.id) }
            if pinned {
                Button { controller.closeStack(context.id) } label: { Image(systemName: "xmark") }
                    .help("대화 목록에서 닫기 · 작업은 계속")
            }
        }.font(.system(size: 11))
    }
}
