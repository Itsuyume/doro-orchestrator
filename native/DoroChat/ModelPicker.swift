import SwiftUI

struct ModelPicker: View {
    @ObservedObject var controller: ChatController
    let selection: ModelSelection
    let session: String
    @State private var model = ""
    @State private var effort = "medium"
    @State private var saving = false
    @State private var status = "다음 Claude 검토부터 적용되도로."

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Claude 모델").font(.system(size: 16, weight: .semibold))
            Picker("모델", selection: $model) {
                ForEach(selection.models, id: \.self) { option in Text(option[1]).tag(option[0]) }
            }
            Picker("생각 깊이", selection: $effort) {
                ForEach(selection.efforts, id: \.self) { option in Text(option[1]).tag(option[0]) }
            }
            Text(selection.actual_model.isEmpty ? "이전 응답 모델: 기록 없음" : "최근 실제 응답: " + selection.actual_model)
                .font(.system(size: 11)).foregroundStyle(.secondary).textSelection(.enabled)
            Text("GPT는 현재 Work 설정을 따르도로. AGY는 꺼져 있도로.")
                .font(.system(size: 11)).foregroundStyle(.secondary)
            HStack {
                Text(status).font(.system(size: 11)).fixedSize(horizontal: false, vertical: true)
                Spacer()
                Button("저장") { save() }.disabled(saving)
            }
        }.padding(16).frame(width: 320)
            .onAppear { model = selection.model; effort = selection.effort }
    }

    private func save() {
        saving = true
        Task {
            defer { saving = false }
            do {
                try await controller.changeModel(model, effort: effort, session: session)
                status = "저장됨 · 다음 검토에 사용"
            } catch { status = "저장 실패: " + error.localizedDescription }
        }
    }
}

struct ModelSettingsButton: View {
    @ObservedObject var controller: ChatController
    @State private var showing = false
    var body: some View {
        Button { showing.toggle() } label: { Image(systemName: "slider.horizontal.3") }
            .buttonStyle(.plain).help("모델 설정").accessibilityLabel("Claude 모델과 생각 깊이 선택")
            .popover(isPresented: $showing) {
                if let selection = controller.conversation?.model_selection {
                    ModelPicker(controller: controller, selection: selection, session: controller.selectedSession)
                        .id(controller.selectedSession)
                }
            }
    }
}
