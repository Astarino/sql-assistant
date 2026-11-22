import SwiftUI

struct RoleAccessView: View {
    @Environment(\.dismiss) private var dismiss
    @State private var catalog: RoleCatalog?
    @State private var readerName = ""
    @State private var grantorName = ""
    @State private var password = ""
    @State private var showsGrantForm = false
    @State private var schemas: [DatabaseSchema]?
    @State private var schema = ""
    @State private var tables: Set<String> = []
    @State private var isLoading = false
    @State private var message: String?

    let source: DataSourceSelection
    let opensReadSetup: Bool
    let onUseRole: (RoleCatalog, DatabaseRole) -> Void
    let onGranted: () async -> Void

    private var reader: DatabaseRole? { catalog?.roles.first { $0.name == readerName } }

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            Text("Роли и доступ").font(.headline)
            Text(source.catalog.database).foregroundStyle(.secondary)
            if let catalog {
                Form {
                    Picker("Роль помощника", selection: Binding(get: { readerName }, set: { name in
                        readerName = name
                        message = nil
                    })) {
                        if readerName.isEmpty { Text("Выбрать роль").tag("") }
                        ForEach(catalog.roles, id: \.name) { role in
                            Text(role.name).tag(role.name)
                        }
                    }
                    .disabled(showsGrantForm)
                    if let reader { Text(roleStatus(reader, in: catalog)).foregroundStyle(.secondary) }
                    if showsGrantForm { grantForm(catalog) }
                }
                .disabled(isLoading)
            }
            if let message { Text(message).foregroundStyle(.secondary).textSelection(.enabled) }
            HStack {
                if isLoading { ProgressView().controlSize(.small) }
                Spacer()
                Button(showsGrantForm ? "Назад" : "Закрыть", role: .cancel) {
                    if schemas != nil { clearTables() }
                    else if showsGrantForm { resetGrantForm() }
                    else { dismiss() }
                }
                .keyboardShortcut(.cancelAction)
                .disabled(isLoading)
                if let catalog, let reader, reader.isReader, !showsGrantForm {
                    Button("Выдать чтение…") {
                        showsGrantForm = true
                        message = nil
                    }
                    .disabled(isLoading)
                    Button(reader.name == catalog.currentRole ? "Готово" : "Использовать роль") {
                        onUseRole(catalog, reader)
                        dismiss()
                    }
                    .keyboardShortcut(.defaultAction)
                    .disabled(isLoading || reader.readableTables == 0)
                } else if showsGrantForm, let catalog {
                    Button(schemas == nil ? "Показать таблицы" : "Выдать чтение") {
                        Task {
                            if schemas == nil { await run { try await loadTables(catalog) } }
                            else { await grantRead(catalog) }
                        }
                    }
                    .keyboardShortcut(.defaultAction)
                    .disabled(isLoading || grantorName.isEmpty || (schemas != nil && tables.isEmpty))
                }
            }
        }
        .padding(22)
        .frame(width: 460)
        .interactiveDismissDisabled(isLoading)
        .task { await loadRoles() }
    }

    private func roleStatus(_ role: DatabaseRole, in catalog: RoleCatalog) -> String {
        if role.administrator { return "Административная роль" }
        if role.name == catalog.owner { return "Владелец базы" }
        if role.canWrite { return "Есть права изменения в этой базе" }
        if !role.canConnect { return "Нет доступа к базе" }
        return "Доступно таблиц: \(role.readableTables)"
    }

    private func grantForm(_ catalog: RoleCatalog) -> some View {
        Group {
            if schemas == nil {
                Picker("Выдать доступ от имени", selection: Binding(get: { grantorName }, set: { name in
                    grantorName = name
                    password = ""
                    message = nil
                })) {
                    ForEach(catalog.roles, id: \.name) { role in
                        Text(role.name == catalog.owner ? "\(role.name) (владелец базы)" : role.name).tag(role.name)
                    }
                }
                SecureField("Пароль", text: $password)
            } else if let schemas, schemas.isEmpty {
                Text("Эта роль не может выдать чтение на таблицы базы.").foregroundStyle(.secondary)
            } else if let schemas {
                LabeledContent("Доступ выдаёт", value: grantorName)
                Picker("Схема", selection: $schema) {
                    ForEach(schemas, id: \.name) { Text($0.name).tag($0.name) }
                }
                if let selected = schemas.first(where: { $0.name == schema }) {
                    let allTables = Set(selected.tables)
                    let allSelected = tables == allTables
                    Button(allSelected ? "Снять выбор" : "Выбрать все") {
                        tables = allSelected ? [] : allTables
                    }
                    ScrollView {
                        VStack(alignment: .leading, spacing: 6) {
                            ForEach(selected.tables, id: \.self) { table in
                                Toggle(table, isOn: Binding(get: { tables.contains(table) }, set: { checked in
                                    if checked { tables.insert(table) } else { tables.remove(table) }
                                }))
                            }
                        }
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .padding(8)
                    }
                    .frame(height: 130)
                    .background(.quaternary.opacity(0.35), in: RoundedRectangle(cornerRadius: 8))
                }
            }
        }
        .onChange(of: schema) { _, _ in tables = [] }
    }

    private func readCatalog() async throws -> RoleCatalog {
        let reply = try await Backend.send(AssistantRequest(
            action: "roles", connection: source.connection, database: source.catalog.database
        ))
        guard let catalog = reply.roleCatalog else {
            throw AssistantError(message: "Не удалось загрузить роли PostgreSQL.")
        }
        return catalog
    }

    private func loadRoles() async {
        await run {
            let catalog = try await readCatalog()
            self.catalog = catalog
            readerName = catalog.roles.first { $0.name == catalog.currentRole && $0.isReader }?.name
                ?? catalog.roles.first { $0.isReader }?.name ?? ""
            grantorName = catalog.roles.first { $0.name == catalog.owner }?.name
                ?? catalog.roles.first { $0.administrator && $0.canConnect }?.name
                ?? catalog.currentRole
            if opensReadSetup, readerName == catalog.currentRole, reader?.readableTables == 0 {
                showsGrantForm = true
                if catalog.host.hasPrefix("/") { try await loadTables(catalog) }
            }
        }
    }

    private func loadTables(_ catalog: RoleCatalog) async throws {
        let reply = try await Backend.send(AssistantRequest(
            action: "access_options", connection: catalog.connection(as: grantorName, password: password),
            role: readerName
        ))
        schemas = reply.accessSchemas ?? []
        schema = schemas?.first(where: { $0.name == "public" })?.name ?? schemas?.first?.name ?? ""
    }

    private func grantRead(_ catalog: RoleCatalog) async {
        await run {
            let reply = try await Backend.send(AssistantRequest(
                action: "grant_read", connection: catalog.connection(as: grantorName, password: password),
                schema: schema, tables: tables.sorted(), role: readerName
            ))
            guard let count = reply.grantedCount else {
                throw AssistantError(message: "Не удалось подтвердить выдачу доступа.")
            }
            resetGrantForm()
            message = "Чтение выдано. Таблиц: \(count)."
            await onGranted()
            do { self.catalog = try await readCatalog() }
            catch { message = "Чтение выдано. Обнови список ролей, открыв окно заново." }
        }
    }

    private func clearTables() {
        schemas = nil
        schema = ""
        tables = []
        message = nil
    }

    private func resetGrantForm() {
        showsGrantForm = false
        password = ""
        clearTables()
    }

    private func run(_ operation: () async throws -> Void) async {
        guard !isLoading else { return }
        isLoading = true
        message = nil
        defer { isLoading = false }
        do { try await operation() }
        catch { message = error.localizedDescription }
    }
}
