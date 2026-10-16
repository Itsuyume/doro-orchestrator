import SwiftUI

struct ChatToolbar: View {
    @ObservedObject var controller: ChatController

    var body: some View {
        ViewThatFits(in: .horizontal) {
            controls(compact: false)
            controls(compact: true)
        }.font(.system(size: 11)).padding(.horizontal, 6).frame(height: TaskListLayout.headerHeight)
            .background(ChatSurface.chrome, in: RoundedRectangle(cornerRadius: 10))
    }

    private func controls(compact: Bool) -> some View {
        HStack(spacing: 4) {
            ContextSelector(controller: controller)
            ModelSettingsButton(controller: controller)
            ToolbarStatus(text: status, active: controller.display != .hidden && !controller.collapsed)
                .frame(minWidth: compact ? 48 : 60, maxWidth: .infinity).layoutPriority(-1)
            if controller.approvalCount > 0 {
                ApprovalEntry(controller: controller, style: compact ? .icon : .count)
            }
            Button { controller.beginNewTask() } label: {
                Image(systemName: "plus").frame(width: 24, height: 24).contentShape(Rectangle())
            }.buttonStyle(.plain).help("새 작업").accessibilityLabel("새 GPT 작업 시작")
                .disabled(controller.showingNewTask)
            Button { controller.collapseToDock() } label: {
                Image(systemName: "chevron.up").frame(width: 24, height: 24).contentShape(Rectangle())
            }.buttonStyle(.plain).help("대화 접기").accessibilityLabel("대화 접기 · dock만 남기기")
        }
    }

    private var status: String {
        if controller.showingNewTask { return "새 작업" }
        if controller.showingTasks || controller.inputStatus.isEmpty { return controller.currentLabel }
        return [controller.inputStatus, controller.currentLabel].filter { !$0.isEmpty }.joined(separator: " · ")
    }
}
