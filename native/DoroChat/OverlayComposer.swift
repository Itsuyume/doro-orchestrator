import SwiftUI

struct OverlayComposer: View {
    @ObservedObject var controller: ChatController
    var body: some View {
        VStack(alignment: .leading, spacing: 5) {
            TextEditor(text: $controller.inputText)
                .font(.system(size: 13)).scrollContentBackground(.hidden)
                .frame(height: 34)
                .padding(5).background(.white.opacity(0.96), in: RoundedRectangle(cornerRadius: 8))
                .accessibilityLabel("도로에게 보낼 내 메시지")
            HStack {
                Text("내 메시지").foregroundStyle(.secondary)
                Spacer()
                Button("보내기") { controller.submitInput() }
                    .buttonStyle(.bordered)
                    .disabled(controller.inputText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
            }.font(.system(size: 11))
            Text(controller.inputStatus).font(.system(size: 10)).foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true).textSelection(.enabled)
        }
        .disabled(controller.sending || controller.conversation?.input_enabled != true)
        .padding(8).background(.regularMaterial, in: RoundedRectangle(cornerRadius: 12))
    }
}
