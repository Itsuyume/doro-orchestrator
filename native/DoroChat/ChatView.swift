import AppKit
import SwiftUI

struct MessageBubble: View {
    let message: ChatMessage
    @Binding var expanded: Bool
    var onRetry: (() -> Void)? = nil

    var body: some View {
        HStack(alignment: .top, spacing: 0) {
            if message.from_user { Spacer(minLength: 44) }
            VStack(alignment: message.from_user ? .trailing : .leading, spacing: 6) {
                Text(message.sender).font(.system(size: 11, weight: .semibold))
                VStack(alignment: .leading, spacing: 7) {
                    if expanded {
                        Text(message.phase).font(.system(size: 10, weight: .medium)).foregroundStyle(.secondary)
                    }
                    Text(verbatim: message.text).font(.system(size: 14)).lineSpacing(3)
                        .lineLimit(MessagePreview.lineLimit(message.text, expanded: expanded))
                    if MessagePreview.canExpand(message.text) {
                        Button(expanded ? "발언 접기" : "전체 발언 펼치기") { expanded.toggle() }
                            .buttonStyle(.plain).font(.system(size: 11, weight: .semibold))
                            .accessibilityValue(expanded ? "펼쳐짐" : "접힘")
                    }
                    if message.state != "completed" {
                        Text(message.state).font(.system(size: 11, weight: .semibold)).foregroundStyle(.secondary)
                    }
                    if message.retryable == true {
                        Button("다시 보내기") { onRetry?() }.buttonStyle(.plain).font(.system(size: 11))
                    }
                    if !message.incoming.isEmpty {
                        DisclosureGroup("이 발언자가 받은 입력") {
                            Text(verbatim: message.incoming).font(.system(size: 11, design: .monospaced))
                                .padding(.top, 6)
                        }.font(.system(size: 11)).tint(.primary)
                    }
                }
                .padding(10)
                .background(message.from_user ? ChatSurface.userBubble : ChatSurface.aiBubble,
                            in: RoundedRectangle(cornerRadius: 12))
            }.frame(maxWidth: .infinity, alignment: message.from_user ? .trailing : .leading)
            if !message.from_user { Spacer(minLength: 44) }
        }
        .accessibilityElement(children: .contain)
        .padding(.horizontal, 10)
        .contextMenu {
            Button("복사") {
                NSPasteboard.general.clearContents()
                NSPasteboard.general.setString(message.text, forType: .string)
            }
        }
    }
}

struct ChatView: View {
    @ObservedObject var controller: ChatController
    @State private var userScrolling = false

    var body: some View {
        VStack(alignment: .trailing, spacing: 5) {
            if !controller.collapsed {
                ChatToolbar(controller: controller)
                expandedBody
            }
            if controller.collapsed, controller.display == .panel {
                StackTray(controller: controller)
            }
            if controller.display == .integrated { HStack {
                if controller.collapsed, !controller.pinnedContexts.isEmpty { StackTray(controller: controller) }
                Spacer(minLength: 0)
                PetHandle(controller: controller).frame(width: 76, height: 83)
                    .overlay(alignment: .topLeading) {
                        if controller.collapsed, controller.approvalCount > 0 {
                            ApprovalEntry(controller: controller).font(.system(size: 10, weight: .semibold)).padding(4)
                                .background(.regularMaterial, in: Capsule())
                        }
                    }
            } }
        }
        .foregroundStyle(.primary)
        .padding(6)
        .background(controller.collapsed ? Color.clear : ChatSurface.panel, in: RoundedRectangle(cornerRadius: 16))
        .overlay {
            if !controller.collapsed { RoundedRectangle(cornerRadius: 16).strokeBorder(ChatSurface.border, lineWidth: 0.75) }
        }
    }

    private var expandedBody: some View {
        VStack(spacing: 5) {
            if !controller.readError.isEmpty || !controller.controlError.isEmpty {
                Text([controller.readError, controller.controlError].filter { !$0.isEmpty }.joined(separator: "\n"))
                    .font(.system(size: 12)).foregroundStyle(.red)
                    .textSelection(.enabled).padding(8).frame(maxWidth: .infinity, alignment: .leading)
                    .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 10))
                if controller.canRecoverState {
                    Button("원본 보관 후 복구") { controller.recoverState() }
                        .buttonStyle(.plain).font(.system(size: 12))
                        .help("기존 초안 파일은 보관하고 현재 입력을 새로 저장해도로. 이전 전송을 자동 재시도하지 않도로.")
                }
            }
            if controller.showingNewTask { NewTaskView(controller: controller) }
            else if controller.showingTasks { TaskManager(controller: controller) }
            else if let view = controller.conversation {
                transcript(view)
                if let target = controller.approvals.presented, target.sessionID == view.session_id {
                    ApprovalView(controller: controller, target: target)
                }
                OverlayComposer(controller: controller)
            } else if controller.readError.isEmpty {
                Spacer(); ProgressView("대화를 읽는 중이도로…"); Spacer()
            }
        }
    }

    private func transcript(_ view: Conversation) -> some View {
        ScrollViewReader { proxy in
            ScrollView {
                LazyVStack(spacing: 12) {
                    ForEach(view.messages) { message in
                        MessageBubble(message: message, expanded: expansion(message.id),
                                      onRetry: { controller.retryDelivery(message.id) }).id(message.id)
                    }
                    Color.clear.frame(height: 1).id("latest")
                }.frame(maxWidth: .infinity).padding(.vertical, 12).scrollTargetLayout()
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
            .contentShape(Rectangle())
            .background(ChatSurface.panel, in: RoundedRectangle(cornerRadius: 18))
            .clipShape(RoundedRectangle(cornerRadius: 18))
            .scrollPosition(id: readingPosition, anchor: .top)
            .defaultScrollAnchor(controller.scrollTarget == nil ? .bottom : .top)
            .onScrollGeometryChange(for: Bool.self) { geometry in
                geometry.contentOffset.y + geometry.containerSize.height >= geometry.contentSize.height - 24
            } action: { _, atBottom in
                if userScrolling {
                    controller.followLatest = atBottom
                    if atBottom { controller.scrollTarget = nil }
                }
            }
            .onScrollPhaseChange { _, phase, context in
                let active = phase == .tracking || phase == .interacting || phase == .decelerating
                if active || userScrolling {
                    let geometry = context.geometry
                    controller.followLatest = geometry.contentOffset.y + geometry.containerSize.height >= geometry.contentSize.height - 24
                    if controller.followLatest { controller.scrollTarget = nil }
                }
                userScrolling = active
            }
            .overlay(alignment: .bottom) {
                latestButton(proxy, hasMessages: !view.messages.isEmpty)
            }
            .onAppear {
                let target = controller.scrollTarget
                guard target != view.messages.first?.id else { return }
                DispatchQueue.main.async {
                    guard controller.selectedSession == view.session_id else { return }
                    proxy.scrollTo(target ?? "latest", anchor: target == nil ? .bottom : .top)
                }
            }
            .onChange(of: view.messages.last?.text) { _, _ in
                if controller.followLatest { proxy.scrollTo("latest", anchor: .bottom) }
            }
            .onChange(of: view.messages.count) { _, _ in
                if controller.followLatest { proxy.scrollTo("latest", anchor: .bottom) }
            }
        }.id(view.session_id)
    }

    @ViewBuilder private func latestButton(_ proxy: ScrollViewProxy, hasMessages: Bool) -> some View {
        if !controller.followLatest && hasMessages {
            Button {
                controller.returnToLatest()
                proxy.scrollTo("latest", anchor: .bottom)
            } label: {
                Label("최신 답변", systemImage: "arrow.down")
                    .font(.system(size: 12, weight: .medium))
                    .padding(.horizontal, 12).padding(.vertical, 7)
                    .background(ChatSurface.chrome, in: Capsule())
            }.buttonStyle(.plain).padding(8)
                .accessibilityLabel("최신 답변으로 이동")
                .help("맨 아래로 이동하고 새 답변을 따라가기로 전환")
        }
    }

    private var readingPosition: Binding<String?> {
        Binding(get: { controller.scrollTarget }, set: { target in
            if userScrolling && !controller.followLatest { controller.scrollTarget = target }
        })
    }

    private func expansion(_ id: String) -> Binding<Bool> {
        Binding(get: { controller.expandedMessages.contains(id) }, set: { expanded in
            if expanded { controller.expandedMessages.insert(id) }
            else { controller.expandedMessages.remove(id) }
        })
    }

}
