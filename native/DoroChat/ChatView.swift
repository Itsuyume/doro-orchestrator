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
                        .lineLimit(expanded ? nil : 6)
                    if message.text.count > 180 {
                        Button(expanded ? "발언 접기" : "전체 발언 펼치기") { expanded.toggle() }
                            .buttonStyle(.plain).font(.system(size: 11, weight: .semibold))
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
                .background(message.from_user ? Color(white: 0.94) : .white,
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
                header
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
        .foregroundStyle(Color.black.opacity(0.86))
        .padding(6)
        .overlay {
            if controller.collapsed, controller.display == .panel {
                WindowDragHandle(label: "작업 목록", onTap: { controller.toggleChat() })
            }
        }
        .preferredColorScheme(.light)
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
            if controller.showingTasks { TaskManager(controller: controller) }
            else if let view = controller.conversation {
                transcript(view)
                OverlayComposer(controller: controller)
            } else if controller.readError.isEmpty {
                Spacer(); ProgressView("대화를 읽는 중이도로…"); Spacer()
            }
        }
    }

    private var header: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 8) {
                if !controller.showingTasks {
                    Button { controller.showTasks() } label: {
                        Image(systemName: "chevron.left").frame(width: 26, height: 22).contentShape(Rectangle())
                    }.buttonStyle(.plain).help("작업 목록")
                        .accessibilityLabel("작업 목록으로 돌아가기")
                }
                ContextSelector(controller: controller)
                WindowDragHandle().frame(maxWidth: .infinity).frame(height: 20)
            }
            HStack {
                ProviderLight(name: "Claude", enabled: controller.conversation?.claude_enabled)
                ProviderLight(name: "AGY", enabled: controller.conversation?.agy_enabled)
                ModelSettingsButton(controller: controller)
                Spacer()
                if controller.approvalCount > 0 {
                    ApprovalEntry(controller: controller)
                }
                Button { controller.minimizeCurrent() } label: {
                    Image(systemName: "minus").frame(width: 26, height: 20).contentShape(Rectangle())
                }.buttonStyle(.plain).background(.black.opacity(0.045), in: RoundedRectangle(cornerRadius: 6))
                    .accessibilityLabel("창 최소화 · 메뉴 막대에서 다시 열기").help("최소화")
                Button { controller.requestStop() } label: {
                    Image(systemName: "xmark").frame(width: 26, height: 20).contentShape(Rectangle())
                }.buttonStyle(.plain).background(.black.opacity(0.045), in: RoundedRectangle(cornerRadius: 6))
                    .accessibilityLabel("도로협업 종료 · 작업 기록은 유지")
                    .help(controller.canQuit ? "종료 · 메뉴 아이콘도 닫기" : "메시지 전달 확인 중")
                    .disabled(!controller.canQuit)
            }.font(.system(size: 11))
        }.padding(9).background(.regularMaterial, in: RoundedRectangle(cornerRadius: 12))
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
            .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 18))
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
