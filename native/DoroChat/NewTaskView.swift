import SwiftUI

struct NewTaskView: View {
    @ObservedObject var controller: ChatController

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            ChatInputEditor(text: $controller.newTask.text, label: "새 작업 내용", onSubmit: controller.submitNewTask)
                .frame(maxWidth: .infinity, minHeight: 120, maxHeight: .infinity)
                .padding(8).background(ChatSurface.editor, in: RoundedRectangle(cornerRadius: 10))
                .disabled(controller.newTask.queued)
            if let problem = controller.inputProblem(controller.newTask.text), !controller.newTask.text.isEmpty {
                Text(problem).font(.system(size: 11)).foregroundStyle(.red)
            }
            HStack {
                if controller.newTaskBusy { ProgressView().controlSize(.small) }
                Text(controller.newTask.status).font(.system(size: 11)).foregroundStyle(.secondary)
                    .textSelection(.enabled).lineLimit(3).help(controller.newTask.status)
                Spacer(minLength: 0)
                Button {
                    controller.submitNewTask()
                } label: {
                    Text(controller.newTask.creationFailed ? "다시 시작" : controller.newTask.retryable ? "다시 보내기" : "시작")
                        .padding(.horizontal, 12).padding(.vertical, 7)
                        .foregroundStyle(controller.canStartNewTask ? ChatSurface.actionText : .secondary)
                        .background(controller.canStartNewTask ? ChatSurface.action : .primary.opacity(0.06),
                                    in: RoundedRectangle(cornerRadius: 8))
                }.buttonStyle(.plain)
                    .disabled(!controller.canStartNewTask)
            }
        }.padding(8).onExitCommand { controller.showTasks() }
    }
}
