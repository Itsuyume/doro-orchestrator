import SwiftUI

struct OverlayComposer: View {
    @ObservedObject var controller: ChatController
    var body: some View {
        VStack(alignment: .leading, spacing: 5) {
            ChatInputEditor(text: $controller.inputText, onSubmit: controller.submitInput)
                .frame(height: 34)
                .padding(5).background(ChatSurface.editor, in: RoundedRectangle(cornerRadius: 8))
                .accessibilityLabel("도로에게 보낼 내 메시지")
                .accessibilityActions {
                    if controller.canSendInput { Button("보내기") { controller.submitInput() } }
                }
                .help("Enter로 보내기 · Shift+Enter는 줄바꿈")
            if let problem = controller.inputProblem(controller.inputText) {
                Text(problem).font(.system(size: 11)).foregroundStyle(.red)
            }
        }
        .disabled(controller.sending || controller.conversation?.input_enabled != true)
        .padding(8).background(.regularMaterial, in: RoundedRectangle(cornerRadius: 12))
    }
}
