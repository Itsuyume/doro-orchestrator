import SwiftUI

struct OverlayComposer: View {
    @ObservedObject var controller: ChatController
    var body: some View {
        VStack(alignment: .leading, spacing: 5) {
            ChatInputEditor(text: $controller.inputText, growsWithText: true, onSubmit: controller.submitInput)
                .frame(minHeight: 34, maxHeight: 120)
                .fixedSize(horizontal: false, vertical: true)
                .padding(5).background(ChatSurface.editor, in: RoundedRectangle(cornerRadius: 8))
                .accessibilityLabel("도로에게 보낼 내 메시지")
                .accessibilityActions {
                    if controller.canSendInput { Button("보내기") { controller.submitInput() } }
                }
                .help("Enter로 보내기 · Shift+Enter는 줄바꿈")
            Text("Enter 보내기 · Shift+Enter 줄바꿈")
                .font(.system(size: 11)).foregroundStyle(.secondary)
            if let problem = controller.inputProblem(controller.inputText) {
                Text(problem).font(.system(size: 11)).foregroundStyle(.red)
            }
        }
        .disabled(controller.sending || controller.conversation?.input_enabled != true)
        .padding(8).background(.regularMaterial, in: RoundedRectangle(cornerRadius: 12))
    }
}
