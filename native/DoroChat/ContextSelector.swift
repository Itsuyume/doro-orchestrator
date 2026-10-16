import SwiftUI

struct ContextSelector: View {
    @ObservedObject var controller: ChatController

    var body: some View {
        Menu {
            Button("대화 목록") { controller.showTasks() }
            if controller.contexts.isEmpty { Text("등록된 대화 없음") }
            Section("열어 둔 대화") {
                ForEach(controller.pinnedContexts) { context in
                    Button(title(context)) { controller.openContext(context.id) }
                }
            }
            if !controller.otherContexts.isEmpty {
                Menu("지난 대화") {
                    ForEach(controller.otherContexts) { context in
                        Button(title(context)) { controller.openContext(context.id) }
                    }
                }
            }
        } label: {
            Label("대화", systemImage: "rectangle.stack")
        }.menuStyle(.borderlessButton).fixedSize().font(.system(size: 11))
    }

    private func title(_ context: ChatContext) -> String {
        context.label + (context.needs_input ? " · 승인 필요" : "")
            + (controller.unread(context) > 0 ? " · 새 대화" : "")
    }
}
