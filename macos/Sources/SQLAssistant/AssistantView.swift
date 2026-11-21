import SwiftUI

struct AssistantView: View {
    @AppStorage("submittedQuestions") private var submittedQuestions = Data()
    @State private var isPinned = false
    @State private var source: DataSourceSelection?
    @State private var question = ""
    @State private var historyPosition: Int?
    @State private var questionDraft = ""
    @State private var reply: AssistantReply?
    @State private var errorMessage: String?
    @State private var progress: String?
    @State private var answers: [Clarification] = []
    @State private var fields: [Clarification] = []
    @State private var showsSourcePicker = false
    @FocusState private var questionFocused: Bool

    private var canAsk: Bool {
        progress == nil && source?.canApply == true && !question.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }

    private var questionHistory: [String] {
        (try? JSONDecoder().decode([String].self, from: submittedQuestions)) ?? []
    }

    var body: some View {
        VStack(spacing: 0) {
            composer
                .padding(16)
            Divider()
            content
        }
        .background(FloatingWindow(isPinned: isPinned))
        .toolbar {
            ToolbarItemGroup(placement: .primaryAction) {
                sourceButton
                Button {
                    isPinned.toggle()
                } label: {
                    Label(isPinned ? "Открепить окно" : "Закрепить поверх окон", systemImage: isPinned ? "pin.fill" : "pin")
                }
            }
        }
        .sheet(isPresented: $showsSourcePicker) {
            SourcePicker(current: source) { selection in
                source = selection
                resetResponse()
            }
        }
        .task {
            await connectDefaultSource()
            questionFocused = true
        }
    }

    private var composer: some View {
        HStack(alignment: .center, spacing: 12) {
            TextField("Задай вопрос о данных", text: $question, axis: .vertical)
                .textFieldStyle(.plain)
                .lineLimit(1...4)
                .font(.system(size: 16))
                .focused($questionFocused)
                .disabled(progress != nil)
                .onKeyPress(keys: [.upArrow, .downArrow]) { press in
                    let editingModifiers: EventModifiers = [.command, .control, .option, .shift]
                    guard press.modifiers.intersection(editingModifiers).isEmpty else { return .ignored }
                    return browseHistory(older: press.key == .upArrow) ? .handled : .ignored
                }
                .onChange(of: question) { _, _ in resetResponse() }

            Button {
                Task { await ask() }
            } label: {
                Label("Спросить", systemImage: "arrow.up")
                    .labelStyle(.iconOnly)
            }
            .buttonStyle(.borderedProminent)
            .controlSize(.large)
            .keyboardShortcut(.return, modifiers: .command)
            .help("Спросить (⌘↩)")
            .disabled(!canAsk || reply?.action == "clarify")
        }
        .padding(10)
        .padding(.leading, 5)
        .background(Color(nsColor: .textBackgroundColor), in: RoundedRectangle(cornerRadius: 12))
        .overlay {
            RoundedRectangle(cornerRadius: 12)
                .strokeBorder(questionFocused ? Color.accentColor.opacity(0.65) : Color.secondary.opacity(0.25))
                .allowsHitTesting(false)
        }
    }

    private var sourceButton: some View {
        Button {
            showsSourcePicker = true
        } label: {
            HStack(spacing: 5) {
                Image(systemName: "cylinder")
                if let source, !source.schema.isEmpty { Text(source.schema) }
                if let count = source?.tables?.count {
                    Text(count, format: .number).foregroundStyle(.secondary)
                }
            }
        }
        .accessibilityLabel("Источник данных")
        .help(source.map { "\($0.catalog.database) · \($0.schema)" } ?? "Выбрать подключение")
        .disabled(progress != nil)
    }

    @ViewBuilder private var content: some View {
        if let progress {
            ProgressView(progress)
                .controlSize(.small)
                .frame(maxWidth: .infinity, maxHeight: .infinity)
        } else {
            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    if let errorMessage {
                        Text(errorMessage)
                            .foregroundStyle(.secondary)
                            .textSelection(.enabled)
                    }
                    if let reply {
                        response(reply)
                    } else if errorMessage == nil, let source, source.catalog.database == "sql_assistant_demo", source.tables == nil {
                        Button {
                            question = source.schema == "shop_eval" ? "Сколько разных товаров было продано?" : "Сколько клиентов в базе?"
                            questionFocused = true
                        } label: {
                            Label(
                                source.schema == "shop_eval" ? "Сколько разных товаров было продано?" : "Сколько клиентов в базе?",
                                systemImage: "arrow.up.left"
                            )
                        }
                        .buttonStyle(.plain)
                        .foregroundStyle(.secondary)
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(16)
            }
        }
    }

    @ViewBuilder private func response(_ reply: AssistantReply) -> some View {
        if reply.action == "clarify" {
            GroupBox {
                VStack(alignment: .leading, spacing: 12) {
                    Text(reply.message ?? "Уточни вопрос.")
                        .foregroundStyle(.secondary)
                    ForEach($fields, id: \.label) { $field in
                        VStack(alignment: .leading, spacing: 4) {
                            Text(field.label).font(.caption.weight(.medium))
                            TextField(field.label, text: $field.value)
                                .labelsHidden()
                                .textFieldStyle(.roundedBorder)
                        }
                    }
                    Button("Продолжить") {
                        Task { await ask(withClarification: true) }
                    }
                    .buttonStyle(.borderedProminent)
                    .keyboardShortcut(.return, modifiers: .command)
                    .disabled(!fields.contains { !$0.value.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty })
                }
                .padding(5)
            } label: {
                Label("Уточнение", systemImage: "questionmark.bubble")
            }
        } else if reply.action == "sql" || reply.action == "relationships" {
            ResultView(reply: reply)
        } else if let message = reply.message {
            Text(message)
                .foregroundStyle(.secondary)
                .textSelection(.enabled)
        }
    }

    private func connectDefaultSource() async {
        progress = "Подключение к PostgreSQL…"
        defer { progress = nil }
        do {
            source = try await Backend.source()
            if source?.canApply != true { showsSourcePicker = true }
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    private func ask(withClarification: Bool = false) async {
        guard canAsk, let source else { return }
        if !withClarification { rememberQuestion() }
        let filledFields = fields.filter { !$0.value.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty }
        let nextAnswers = withClarification ? answers + filledFields : []
        let request = AssistantRequest(
            action: "ask", connection: source.connection, database: source.catalog.database,
            schema: source.schema, tables: source.tables?.sorted(), question: question, answers: nextAnswers
        )
        progress = "Ожидание ответа…"
        errorMessage = nil
        if !withClarification { reply = nil }
        defer { progress = nil }
        do {
            let response = try await Backend.send(request)
            answers = nextAnswers
            fields = (response.clarificationFields ?? []).map { Clarification(label: $0) }
            reply = response
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    private func rememberQuestion() {
        let recent = [question] + questionHistory.filter { $0 != question }
        if let data = try? JSONEncoder().encode(Array(recent.prefix(3))) {
            submittedQuestions = data
        }
        historyPosition = nil
        questionDraft = ""
    }

    private func browseHistory(older: Bool) -> Bool {
        let history = questionHistory
        guard !history.isEmpty, older || historyPosition != nil else { return false }

        if historyPosition == nil { questionDraft = question }
        let position = (historyPosition ?? -1) + (older ? 1 : -1)
        if position < 0 {
            question = questionDraft
            historyPosition = nil
        } else if history.indices.contains(position) {
            question = history[position]
            historyPosition = position
        }
        return true
    }

    private func resetResponse() {
        reply = nil
        errorMessage = nil
        answers = []
        fields = []
    }
}
