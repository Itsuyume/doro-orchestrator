import SwiftUI

struct ApprovalView: View {
    @ObservedObject var controller: ChatController
    let target: ApprovalTarget
    @State private var details = false

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(alignment: .firstTextBaseline) {
                Text(question).font(.system(size: 13, weight: .semibold))
                Spacer()
                Button(details ? "상세 접기" : "상세 내용") { details.toggle() }
                    .buttonStyle(.plain).font(.system(size: 11))
                    .accessibilityLabel(details ? "승인 요청 상세 접기" : "승인 요청 상세 내용 펼치기")
            }
            if details {
                ScrollView {
                    VStack(alignment: .leading, spacing: 6) {
                        Text(target.label).font(.system(size: 11)).foregroundStyle(.secondary)
                        Text(brief).font(.system(size: 13)).lineSpacing(2)
                        Text(target.approval.details).font(.system(size: 12)).lineSpacing(2)
                    }.frame(maxWidth: .infinity, alignment: .leading).textSelection(.enabled)
                }.frame(height: 110)
            } else {
                Text(brief).font(.system(size: 13)).lineSpacing(2).lineLimit(4)
                    .fixedSize(horizontal: false, vertical: true).textSelection(.enabled)
            }
            HStack(spacing: 10) {
                if let status { Text(status).font(.system(size: 11)).foregroundStyle(.secondary) }
                Spacer(minLength: 0)
                Button("거절") { controller.submitApproval(.reject, target: target) }
                    .disabled(!canAnswer).accessibilityLabel(target.label + " · 질문 거절")
                Button { controller.submitApproval(.approve, target: target) } label: {
                    Text("승인").font(.system(size: 13, weight: .semibold))
                        .padding(.horizontal, 14).padding(.vertical, 6)
                        .foregroundStyle(ChatSurface.actionText)
                        .background(ChatSurface.action, in: RoundedRectangle(cornerRadius: 8))
                }.buttonStyle(.plain).disabled(!canAnswer).opacity(canAnswer ? 1 : 0.45)
                    .accessibilityLabel(target.label + " · 질문 승인")
            }.controlSize(.large)
        }.padding(10).frame(maxWidth: .infinity, alignment: .leading)
            .background(ChatSurface.aiBubble, in: RoundedRectangle(cornerRadius: 12))
            .foregroundStyle(.primary)
            .onAppear { details = target.approval.brief.isEmpty }
            .onChange(of: target.id) { _, _ in details = target.approval.brief.isEmpty }
    }

    private var canAnswer: Bool {
        !controller.sending && controller.readError.isEmpty
            && controller.approvals.canSubmit(target, current: controller.conversation)
    }

    private var brief: String {
        target.approval.brief.isEmpty ? target.approval.details : target.approval.brief
    }

    private var question: String {
        if target.approval.kind.contains("반영") { return "이 변경을 반영할까도로?" }
        if target.approval.kind.contains("시작") { return "이 범위로 시작할까도로?" }
        return "이 방향으로 진행할까도로?"
    }

    private var status: String? {
        if !controller.readError.isEmpty { return controller.readError }
        if controller.sending { return "전달 확인 중" }
        return controller.inputStatus.hasPrefix("전달 확인 실패") ? controller.inputStatus : nil
    }
}

struct ApprovalEntry: View {
    enum Style { case title, count, icon }
    @ObservedObject var controller: ChatController
    var style = Style.title
    var body: some View {
        Menu {
            ForEach(controller.contexts.filter(\.needs_input)) { context in
                Button(context.label) { controller.openApproval(context.id) }
            }
        } label: {
            switch style {
            case .count:
                HStack(spacing: 2) {
                    Image(systemName: "exclamationmark.bubble")
                    Text(controller.approvalCount > 99 ? "99+" : "\(controller.approvalCount)").monospacedDigit()
                }.frame(height: 24)
            case .icon:
                Image(systemName: "exclamationmark.bubble").frame(width: 24, height: 24)
            case .title:
                Label("승인 \(controller.approvalCount)", systemImage: "bubble.left.and.exclamationmark.bubble.right")
            }
        }.menuStyle(.borderlessButton).menuIndicator(style == .title ? .visible : .hidden)
            .fixedSize().foregroundStyle(.primary).help("승인 대기 \(controller.approvalCount)개")
            .accessibilityLabel("대기 중인 승인 \(controller.approvalCount)개 열기")
    }
}
