import SwiftUI

struct OverlayComposer: View {
    @ObservedObject var controller: ChatController
    var body: some View {
        VStack(alignment: .leading, spacing: 5) {
            ChatInputEditor(text: $controller.inputText, onSubmit: controller.submitInput)
                .frame(height: 34)
                .padding(5).background(.white.opacity(0.96), in: RoundedRectangle(cornerRadius: 8))
                .accessibilityLabel("도로에게 보낼 내 메시지")
            HStack {
                Text(controller.currentLabel).lineLimit(1).foregroundStyle(.secondary)
                Spacer()
                Button("보내기") { controller.submitInput() }
                    .buttonStyle(.bordered)
                    .disabled(!controller.canSendInput).keyboardShortcut(.return, modifiers: .command)
                    .help("Enter로 보내기 · Shift+Enter는 줄바꿈")
            }.font(.system(size: 11))
            if let problem = controller.inputProblem(controller.inputText) {
                Text(problem).font(.system(size: 11)).foregroundStyle(.red)
            }
            if !controller.inputStatus.isEmpty {
                Text(controller.inputStatus).font(.system(size: 10)).foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true).textSelection(.enabled)
            }
        }
        .disabled(controller.sending || controller.conversation?.input_enabled != true)
        .padding(8).background(.regularMaterial, in: RoundedRectangle(cornerRadius: 12))
    }
}
