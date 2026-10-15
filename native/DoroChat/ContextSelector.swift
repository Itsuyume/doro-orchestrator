import SwiftUI

struct ContextSelector: View {
    @ObservedObject var controller: ChatController

    var body: some View {
        Menu {
            Button("작업 관리…") { controller.showTasks() }
            if controller.contexts.isEmpty { Text("등록된 작업 없음") }
            Section("열린 작업") {
                ForEach(controller.pinnedContexts) { context in
                    Button(title(context)) { controller.openContext(context.id) }
                }
            }
            if !controller.otherContexts.isEmpty {
                Menu("닫힌 작업과 지난 대화") {
                    ForEach(controller.otherContexts) { context in
                        Button(title(context)) { controller.openContext(context.id) }
                    }
                }
            }
        } label: {
            Label("작업 목록", systemImage: "rectangle.stack")
        }.menuStyle(.borderlessButton).fixedSize().font(.system(size: 11))
    }

    private func title(_ context: ChatContext) -> String {
        context.label + (context.needs_input ? " · 승인 필요" : "")
            + (controller.unread(context) > 0 ? " · 새 대화" : "")
    }
}
