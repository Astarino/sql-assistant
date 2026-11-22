import AppKit
import SwiftUI

struct SetupView: View {
    private enum Stage {
        case checking, ollama, model, database
    }

    let connectDefault: () async -> Void
    let chooseSource: () -> Void
    let skip: () -> Void
    var client = OllamaSetupClient()

    @Environment(\.scenePhase) private var scenePhase
    @State private var stage = Stage.checking
    @State private var checking = false
    @State private var download: Task<Void, Never>?
    @State private var progress: ModelDownloadProgress?
    @State private var errorMessage: String?

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 18) {
                Text("Настройка SQL Assistant").font(.title2.weight(.semibold))

                VStack(alignment: .leading, spacing: 8) {
                    step("Ollama", complete: stage == .model || stage == .database, active: stage == .ollama)
                    step("Модель Qwen 3.5 4B", complete: stage == .database, active: stage == .model)
                    step("PostgreSQL", complete: false, active: stage == .database)
                }

                Divider()
                VStack(alignment: .leading, spacing: 10) {
                    instructions
                    if let errorMessage {
                        Text(errorMessage).foregroundStyle(.secondary).textSelection(.enabled)
                    }
                }

                Button("Настроить позже", action: skip)
                    .buttonStyle(.link)
                    .disabled(checking || download != nil)
            }
            .frame(maxWidth: 460, alignment: .leading)
            .padding(22)
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        .task { await checkOllama() }
        .onChange(of: scenePhase) { _, phase in
            if phase == .active, stage == .ollama {
                Task { await checkOllama() }
            }
        }
        .onDisappear { download?.cancel() }
    }

    @ViewBuilder private var instructions: some View {
        switch stage {
        case .checking:
            ProgressView("Проверяю Ollama…").controlSize(.small)
        case .ollama:
            let app = NSWorkspace.shared.urlForApplication(withBundleIdentifier: "com.electron.ollama")
            Text("Запусти Ollama").font(.headline)
            if let app {
                Text("Открой Ollama и вернись в это окно.").foregroundStyle(.secondary)
                Button("Открыть Ollama") {
                    Task {
                        await checkOllama(start: {
                            guard NSWorkspace.shared.open(app) else {
                                throw AssistantError(message: "Не удалось открыть Ollama. Открой её из «Программ».")
                            }
                            return nil
                        })
                    }
                }
                .buttonStyle(.borderedProminent)
            } else if let command = OllamaSetupClient.installedCommand {
                Text("Ollama уже установлена. Для подключения запусти её локальный сервер.").foregroundStyle(.secondary)
                Button("Запустить Ollama") {
                    Task { await checkOllama(start: { try client.startServer(executable: command) }) }
                }
                .buttonStyle(.borderedProminent)
            } else {
                Text("Открой скачанный `.dmg`, перенеси Ollama в «Программы» и запусти её. Если используешь терминал, запусти `ollama serve`.")
                    .foregroundStyle(.secondary)
                Link("Скачать Ollama", destination: URL(string: "https://ollama.com/download/Ollama.dmg")!)
                    .buttonStyle(.borderedProminent)
            }
            Button("Проверить подключение") { Task { await checkOllama() } }
        case .model:
            Text("Скачай модель").font(.headline)
            if download != nil {
                if let progress {
                    ProgressView(value: Double(progress.downloaded), total: Double(progress.total)) {
                        Text("Загрузка Qwen 3.5 4B")
                    } currentValueLabel: {
                        Text("\(progress.downloaded.formatted(.byteCount(style: .file))) из \(progress.total.formatted(.byteCount(style: .file)))")
                    }
                } else {
                    ProgressView("Подготовка загрузки…").controlSize(.small)
                }
                Button("Отменить загрузку") { download?.cancel() }
            } else {
                Text("Модель загрузится один раз и будет работать на этом Mac. Понадобится около 4 ГБ на диске.")
                    .foregroundStyle(.secondary)
                Button("Скачать Qwen 3.5 4B", action: downloadModel)
                    .buttonStyle(.borderedProminent)
                Button("Проверить модель") { Task { await checkOllama() } }
            }
        case .database:
            if checking || download != nil {
                ProgressView("Подключаюсь к PostgreSQL…").controlSize(.small)
            } else {
                Text("Подключи PostgreSQL").font(.headline)
                Text("Выбери подключение или добавь профиль. Для нового профиля понадобятся адрес сервера, имя базы и роль с правами на чтение.")
                    .foregroundStyle(.secondary)
                Button("Выбрать источник данных…", action: chooseSource)
                    .buttonStyle(.borderedProminent)
                Link("Установить PostgreSQL на Mac", destination: URL(string: "https://www.postgresql.org/download/macosx/")!)
            }
        }
    }

    private func step(_ title: String, complete: Bool, active: Bool) -> some View {
        Label(title, systemImage: complete ? "checkmark.circle.fill" : "circle")
            .foregroundStyle(complete ? Color.green : active ? Color.primary : Color.secondary)
            .accessibilityValue(complete ? "Готово" : active ? "Текущий шаг" : "Ожидает настройки")
    }

    private func checkOllama(start: (() throws -> Process?)? = nil) async {
        guard !checking, download == nil else { return }
        checking = true
        stage = .checking
        errorMessage = nil
        defer { checking = false }
        do {
            let modelAvailable: Bool
            if let start {
                modelAvailable = try await client.waitForServer(start())
            } else {
                modelAvailable = try await client.hasModel()
            }
            if modelAvailable {
                stage = .database
                await connectDefault()
            } else {
                stage = .model
            }
        } catch {
            guard !Task.isCancelled else { return }
            stage = .ollama
            if !(error is URLError) { errorMessage = error.localizedDescription }
        }
    }

    private func downloadModel() {
        guard download == nil else { return }
        errorMessage = nil
        progress = nil
        download = Task {
            defer { download = nil }
            do {
                try await client.download { progress = $0 }
                try Task.checkCancellation()
                stage = .database
                await connectDefault()
            } catch {
                if !Task.isCancelled { errorMessage = error.localizedDescription }
            }
        }
    }
}
