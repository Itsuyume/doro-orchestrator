import SwiftUI

struct ModelPicker: View {
    @Environment(\.dismiss) private var dismiss
    @ObservedObject var controller: ChatController
    let selection: ModelSelection
    let session: String
    @State private var model = ""
    @State private var effort = "medium"
    @State private var provider = "claude"
    @State private var enabled = true
    @State private var saving = false
    @State private var status = ""
    private var choices: [ModelSelection] { [selection] + (selection.alternatives ?? []) }
    private var selected: ModelSelection? { choices.first { ($0.provider ?? "claude") == provider } }

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Picker("AI", selection: $provider) {
                ForEach(choices, id: \.provider) { choice in
                    Text(choice.provider == "agy" ? "AGY" : "Claude").tag(choice.provider ?? "claude")
                }
            }.pickerStyle(.segmented).labelsHidden()
            if let choice = selected {
                if provider == "agy" { Toggle("사용", isOn: $enabled) }
                Picker("모델", selection: $model) {
                    ForEach(choice.models, id: \.self) { option in Text(option[1]).tag(option[0]) }
                }
                Picker("생각 깊이", selection: $effort) {
                    ForEach(choice.efforts, id: \.self) { option in Text(option[1]).tag(option[0]) }
                }
                if !choice.actual_model.isEmpty {
                    Text((provider == "agy" ? "최근 CLI 모델: " : "최근 실제 응답: ") + choice.actual_model)
                        .font(.system(size: 11)).foregroundStyle(.secondary).textSelection(.enabled)
                }
                if provider == "agy", let reason = choice.reason {
                    Text(reason).font(.system(size: 11)).fixedSize(horizontal: false, vertical: true)
                        .foregroundStyle(choice.ready == false ? Color.orange : Color.secondary)
                }
            }
            HStack {
                if !status.isEmpty { Text(status).font(.system(size: 11)).fixedSize(horizontal: false, vertical: true) }
                Spacer()
                if saving { ProgressView().controlSize(.small) }
                Button("저장") { save() }.disabled(saving || selected == nil)
                    .keyboardShortcut(.defaultAction)
            }
        }.padding(16).frame(width: 320)
            .disabled(saving)
            .onAppear { loadChoice() }
            .onChange(of: provider) { _, _ in loadChoice() }
    }

    private func loadChoice() {
        guard let selected else { return }
        model = selected.model
        effort = selected.effort
        enabled = selected.enabled ?? true
        status = ""
    }

    private func save() {
        guard !saving else { return }
        saving = true
        Task {
            defer { saving = false }
            do {
                try await controller.changeModel(model, effort: effort, session: session, provider: provider, enabled: enabled)
                dismiss()
            } catch { status = "저장 실패: " + error.localizedDescription }
        }
    }
}

struct ModelSettingsButton: View {
    @ObservedObject var controller: ChatController
    @State private var showing = false
    var body: some View {
        Button { showing.toggle() } label: {
            HStack(spacing: 6) {
                ProviderLight(name: "Claude", enabled: controller.conversation?.claude_enabled)
                ProviderLight(name: "AGY", enabled: controller.conversation.map { view in
                    view.agy_enabled && view.model_selection?.alternatives?.first(where: { $0.provider == "agy" })?.available == true
                })
            }.padding(.horizontal, 5).frame(height: 24)
                .background(.primary.opacity(0.035), in: RoundedRectangle(cornerRadius: 5))
                .overlay { RoundedRectangle(cornerRadius: 5).strokeBorder(.primary.opacity(0.10), lineWidth: 0.5) }
        }.buttonStyle(.plain).fixedSize().help("Claude·AGY 모델 설정")
            .accessibilityLabel("Claude·AGY 모델과 생각 깊이 선택")
            .popover(isPresented: $showing) {
                if let selection = controller.conversation?.model_selection {
                    ModelPicker(controller: controller, selection: selection, session: controller.selectedSession)
                        .id(controller.selectedSession)
                }
            }
    }
}
