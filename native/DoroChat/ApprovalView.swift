import SwiftUI

struct ApprovalView: View {
    @ObservedObject var controller: ChatController
    let target: ApprovalTarget
    @State private var details = false

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack(alignment: .top) {
                Text(question).font(.system(size: 18, weight: .bold))
                Spacer()
                Button { controller.approvals.dismiss() } label: {
                    Image(systemName: "xmark").frame(width: 24, height: 24)
                }.buttonStyle(.plain).help("나중에 · 승인 대기는 유지")
                    .accessibilityLabel("승인창 닫기 · 결정하지 않음")
            }
            ScrollView {
                VStack(alignment: .leading, spacing: 12) {
                    Text(target.approval.brief.isEmpty ? "이 질문에는 짧은 요약이 없어 원문을 보여주도로." : target.approval.brief)
                        .font(.system(size: 14)).lineSpacing(4).fixedSize(horizontal: false, vertical: true)
                        .textSelection(.enabled)
                    DisclosureGroup("상세 내용", isExpanded: $details) {
                        Text("작업: " + target.label).font(.system(size: 11)).foregroundStyle(.secondary)
                        Text(target.approval.details).font(.system(size: 12)).lineSpacing(3)
                            .textSelection(.enabled).padding(.top, 6)
                    }.font(.system(size: 12))
                }.frame(maxWidth: .infinity, alignment: .leading)
            }.contentShape(Rectangle())
            status
            HStack(spacing: 8) {
                Button("나중에") { controller.approvals.dismiss() }.keyboardShortcut(.cancelAction)
                Spacer()
                Button("보류") { controller.submitApproval(.reject, target: target) }
                    .disabled(!canAnswer)
                Button("승인") { controller.submitApproval(.approve, target: target) }
                    .buttonStyle(.borderedProminent).tint(.black.opacity(0.8)).disabled(!canAnswer)
                    .accessibilityLabel(target.label + " · 질문 " + target.approval.checkpoint_id.prefix(4) + " 승인")
            }.controlSize(.large)
        }.padding(18).frame(width: 360, height: 340)
            .background(Color(white: 0.98), in: RoundedRectangle(cornerRadius: 18))
            .foregroundStyle(.black.opacity(0.88)).preferredColorScheme(.light)
            .onAppear { details = target.approval.brief.isEmpty }
    }

    private var canAnswer: Bool {
        !controller.sending && controller.readError.isEmpty
            && controller.approvals.canSubmit(target, current: controller.conversation)
    }

    private var question: String {
        if target.approval.kind.contains("반영") { return "이 변경을 반영할까도로?" }
        if target.approval.kind.contains("시작") { return "이 범위로 시작할까도로?" }
        return "이 방향으로 진행할까도로?"
    }

    private var status: some View {
        Text(!controller.readError.isEmpty ? controller.readError : controller.approvals.responsePending(target)
             ? receivedStatus
             : controller.inputStatus.hasPrefix("전달 확인 실패") ? controller.inputStatus : "이 질문에만 적용되도로.")
            .font(.system(size: 11)).foregroundStyle(.secondary).textSelection(.enabled)
    }

    private var receivedStatus: String {
        switch controller.approvals.responseDecision(target) {
        case .approve: return "승인 답변 접수됨 · 도로 확인 대기"
        case .reject: return "보류 답변 접수됨 · 도로 확인 대기"
        case nil: return "답변 접수됨 · 도로 확인 대기"
        }
    }
}

struct ApprovalEntry: View {
    @ObservedObject var controller: ChatController
    var body: some View {
        Menu {
            ForEach(controller.contexts.filter(\.needs_input)) { context in
                Button(context.label) { controller.openApproval(context.id) }
            }
        } label: {
            Label("승인 \(controller.approvalCount)", systemImage: "bubble.left.and.exclamationmark.bubble.right")
        }.menuStyle(.borderlessButton).fixedSize().foregroundStyle(.primary)
            .accessibilityLabel("대기 중인 승인 \(controller.approvalCount)개 열기")
    }
}
