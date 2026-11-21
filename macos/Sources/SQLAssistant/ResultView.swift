import AppKit
import SwiftUI
import UniformTypeIdentifiers

struct ResultView: View {
    let reply: AssistantReply
    @State private var copied = false
    @State private var fileError: String?

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            if let relationships = reply.relationships {
                if let message = reply.message {
                    Text(message).foregroundStyle(.secondary).textSelection(.enabled)
                }
                ForEach(relationships.indices, id: \.self) { index in
                    Text(relationships[index].joinOn.joined(separator: " AND\n"))
                        .font(.system(.callout, design: .monospaced))
                        .textSelection(.enabled)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .padding(10)
                        .background(.quaternary.opacity(0.4), in: RoundedRectangle(cornerRadius: 8))
                }
            } else if let result = reply.execution {
                if let message = reply.message {
                    Text(message).foregroundStyle(.secondary).textSelection(.enabled)
                }
                if result.rows.isEmpty {
                    Text("Запрос выполнен. Строк нет.").foregroundStyle(.secondary)
                } else {
                    table(result)
                }
                if result.truncated {
                    Text("Показаны первые \(result.rows.count) строк.")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                queryBlock(result.query, exportable: true)
            } else if let error = reply.executionError {
                Label("SQL не выполнен", systemImage: "exclamationmark.circle")
                    .font(.headline)
                Text(error).foregroundStyle(.secondary).textSelection(.enabled)
                if let query = reply.sql { queryBlock(query, exportable: false) }
            }
            if let fileError {
                Text(fileError).font(.caption).foregroundStyle(.secondary).textSelection(.enabled)
            }
        }
    }

    private func table(_ result: QueryResult) -> some View {
        ViewThatFits(in: .horizontal) {
            tableGrid(result, columnLimit: .infinity)
            ScrollView(.horizontal) {
                tableGrid(result, columnLimit: 220)
            }
        }
        .background(Color(nsColor: .textBackgroundColor), in: RoundedRectangle(cornerRadius: 8))
        .clipShape(.rect(cornerRadius: 8))
        .overlay {
            RoundedRectangle(cornerRadius: 8)
                .strokeBorder(.quaternary)
                .allowsHitTesting(false)
        }
        .textSelection(.enabled)
    }

    private func tableGrid(_ result: QueryResult, columnLimit: CGFloat) -> some View {
        Grid(alignment: .leading, horizontalSpacing: 0, verticalSpacing: 0) {
            GridRow {
                ForEach(result.columns.indices, id: \.self) { index in
                    cell(result.columns[index], maxWidth: columnLimit)
                        .font(.system(.caption, design: .monospaced).weight(.semibold))
                        .foregroundStyle(.secondary)
                }
            }
            .background(.quaternary.opacity(0.45))

            ForEach(result.rows.indices, id: \.self) { index in
                Divider().gridCellUnsizedAxes(.horizontal)
                GridRow {
                    ForEach(result.rows[index].indices, id: \.self) { column in
                        let value = result.rows[index][column]
                        cell(value ?? "NULL", maxWidth: columnLimit)
                            .foregroundStyle(value == nil ? Color.secondary : Color.primary)
                            .monospacedDigit()
                    }
                }
            }
        }
    }

    private func cell(_ value: String, maxWidth: CGFloat) -> some View {
        Text(value)
            .lineLimit(3)
            .frame(minWidth: 80, maxWidth: maxWidth, alignment: .leading)
            .padding(.horizontal, 12)
            .padding(.vertical, 8)
    }

    private func queryBlock(_ query: String, exportable: Bool) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack {
                Text("SQL")
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(.secondary)
                Spacer()
                if exportable {
                    Button {
                        NSPasteboard.general.clearContents()
                        NSPasteboard.general.setString(query, forType: .string)
                        copied = true
                    } label: {
                        Label(copied ? "Скопировано" : "Копировать SQL", systemImage: copied ? "checkmark" : "document.on.document")
                            .labelStyle(.iconOnly)
                    }
                    .help(copied ? "Скопировано" : "Копировать SQL")
                    Menu {
                        Button("Сохранить SQL…") { save(query) }
                        Button("Открыть в DBeaver") { openInDBeaver(query) }
                    } label: {
                        Label("Действия с SQL", systemImage: "ellipsis.circle")
                            .labelStyle(.iconOnly)
                    }
                    .menuIndicator(.hidden)
                }
            }
            .buttonStyle(.borderless)
            Text(query)
                .font(.system(.callout, design: .monospaced))
                .textSelection(.enabled)
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(10)
                .background(.quaternary.opacity(0.4), in: RoundedRectangle(cornerRadius: 8))
        }
    }

    private func save(_ query: String) {
        let panel = NSSavePanel()
        panel.allowedContentTypes = [UTType(filenameExtension: "sql") ?? .plainText]
        panel.nameFieldStringValue = "query.sql"
        let saveFile: (NSApplication.ModalResponse) -> Void = { response in
            guard response == .OK, let url = panel.url else { return }
            do {
                try (query + "\n").write(to: url, atomically: true, encoding: .utf8)
                fileError = nil
            } catch {
                fileError = error.localizedDescription
            }
        }
        if let window = NSApp.keyWindow {
            panel.beginSheetModal(for: window, completionHandler: saveFile)
        } else {
            panel.begin(completionHandler: saveFile)
        }
    }

    private func openInDBeaver(_ query: String) {
        guard let app = NSWorkspace.shared.urlForApplication(withBundleIdentifier: "org.jkiss.dbeaver.core.product"),
              let executable = Bundle(url: app)?.executableURL else {
            fileError = "DBeaver Community не найден. Можно скопировать SQL или сохранить файл."
            return
        }

        do {
            let folder = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
            try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: false)
            let script = folder.appendingPathComponent("query.sql")
            try (query + "\n").write(to: script, atomically: true, encoding: .utf8)
            let process = Process()
            process.executableURL = executable
            process.arguments = ["-f", script.path]
            process.standardOutput = FileHandle.nullDevice
            process.standardError = FileHandle.nullDevice
            try process.run()
            fileError = nil
        } catch {
            fileError = error.localizedDescription
        }
    }
}
