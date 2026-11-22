import SwiftUI

struct SourcePicker: View {
    @Environment(\.dismiss) private var dismiss
    @AppStorage("connectionProfiles") private var storedProfiles = Data()
    @State private var selection: DataSourceSelection?
    @State private var profileID: UUID?
    @State private var isLoading = false
    @State private var errorMessage: String?
    @State private var editsProfile = false
    @State private var profileDraft = ConnectionProfile()
    @State private var passwordDraft = ""
    @State private var rememberPassword = false
    @State private var showsRoleAccess = false

    let checkDefaultOnOpen: Bool
    let onApply: (DataSourceSelection) -> Void

    init(current: DataSourceSelection?, checkDefaultOnOpen: Bool = true, onApply: @escaping (DataSourceSelection) -> Void) {
        _selection = State(initialValue: current)
        _profileID = State(initialValue: current?.profileID)
        self.checkDefaultOnOpen = checkDefaultOnOpen
        self.onApply = onApply
    }

    private var profiles: [ConnectionProfile] {
        (try? JSONDecoder().decode([ConnectionProfile].self, from: storedProfiles)) ?? []
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            Text(editsProfile ? "Профиль PostgreSQL" : "Источник данных").font(.headline)
            if editsProfile { profileForm } else { sourceForm }
            if let errorMessage {
                Text(errorMessage).foregroundStyle(.secondary).textSelection(.enabled)
            }
            HStack {
                if isLoading { ProgressView().controlSize(.small) }
                Spacer()
                Button(editsProfile ? "Назад" : "Отмена", role: .cancel) {
                    if editsProfile {
                        editsProfile = false
                        passwordDraft = ""
                        errorMessage = nil
                    } else {
                        dismiss()
                    }
                }
                .keyboardShortcut(.cancelAction)
                .disabled(isLoading)
                if editsProfile {
                    Button("Сохранить") { Task { await saveProfile() } }
                        .keyboardShortcut(.defaultAction)
                        .disabled(isLoading || [profileDraft.name, profileDraft.database, profileDraft.user].contains {
                            $0.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
                        })
                } else {
                    Button("Применить") {
                        if let selection {
                            onApply(selection)
                            dismiss()
                        }
                    }
                    .keyboardShortcut(.defaultAction)
                    .disabled(isLoading || selection?.canApply != true)
                }
            }
        }
        .padding(22)
        .frame(width: 450)
        .interactiveDismissDisabled(isLoading)
        .sheet(isPresented: $showsRoleAccess) {
            if let selection {
                RoleAccessView(
                    source: selection, opensReadSetup: selection.availableTables.isEmpty,
                    onUseRole: useRole, onGranted: refreshSource
                )
            }
        }
        .task {
            if checkDefaultOnOpen, selection == nil { await selectProfile(profileID) }
        }
    }

    private var sourceForm: some View {
        VStack(alignment: .leading, spacing: 12) {
            Form {
                Picker("Подключение", selection: Binding(get: { profileID }, set: { id in
                    Task { await selectProfile(id) }
                })) {
                    Text("По умолчанию").tag(nil as UUID?)
                    ForEach(profiles) { Text($0.name).tag($0.id as UUID?) }
                }
                HStack {
                    Button("Добавить…") { editProfile(nil) }
                    if let profile = profiles.first(where: { $0.id == profileID }) {
                        Button("Изменить…") { editProfile(profile) }
                    }
                }
                if selection == nil, profileID == nil {
                    Button("Проверить подключение по умолчанию") { Task { await selectProfile(nil) } }
                }
                if let selection {
                    Picker("База", selection: Binding(get: { selection.catalog.database }, set: { database in
                        Task { await selectDatabase(database) }
                    })) {
                        ForEach(selection.catalog.databases, id: \.self) { Text($0).tag($0) }
                    }
                    Button(selection.availableTables.isEmpty ? "Настроить чтение…" : "Роли и доступ…") {
                        showsRoleAccess = true
                    }
                    if !selection.catalog.schemas.isEmpty {
                        Picker("Схема", selection: Binding(get: { selection.schema }, set: { schema in
                            self.selection?.schema = schema
                            self.selection?.tables = nil
                        })) {
                            ForEach(selection.catalog.schemas, id: \.name) { Text($0.name).tag($0.name) }
                        }
                    }
                }
            }
            if let selection {
                if selection.availableTables.isEmpty {
                    Text("Текущей роли пока недоступны таблицы в этой базе.").foregroundStyle(.secondary)
                } else {
                    Toggle("Все таблицы схемы", isOn: Binding(get: { selection.tables == nil }, set: { all in
                        self.selection?.tables = all ? nil : Set(selection.availableTables)
                    }))
                    if selection.tables != nil {
                        ScrollView {
                            VStack(alignment: .leading, spacing: 6) {
                                ForEach(selection.availableTables, id: \.self) { table in
                                    Toggle(table, isOn: Binding(get: {
                                        self.selection?.tables?.contains(table) == true
                                    }, set: { checked in
                                        if checked { self.selection?.tables?.insert(table) }
                                        else { self.selection?.tables?.remove(table) }
                                    }))
                                }
                            }
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .padding(8)
                        }
                        .frame(height: 110)
                        .background(.quaternary.opacity(0.35), in: RoundedRectangle(cornerRadius: 8))
                    }
                }
            }
        }
        .disabled(isLoading)
    }

    private var profileForm: some View {
        Form {
            TextField("Название", text: $profileDraft.name)
            TextField("Хост", text: $profileDraft.host)
            TextField("Порт", text: $profileDraft.port)
            TextField("Начальная база", text: $profileDraft.database)
            TextField("Роль для чтения", text: $profileDraft.user)
            SecureField("Пароль", text: $passwordDraft)
            Toggle("Запомнить пароль в Связке ключей", isOn: $rememberPassword)
        }
        .disabled(isLoading)
    }

    private func selectProfile(_ id: UUID?) async {
        guard !isLoading, selection == nil || id != profileID else { return }
        profileID = id
        selection = nil
        isLoading = true
        errorMessage = nil
        defer { isLoading = false }
        do {
            let profile = profiles.first { $0.id == id }
            let connection = try profile.map { try $0.connection(password: ProfilePasswords.load(for: $0.id)) }
            selection = try await Backend.source(profileID: id, connection: connection)
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    private func selectDatabase(_ database: String) async {
        guard let selection, !isLoading, database != selection.catalog.database else { return }
        isLoading = true
        errorMessage = nil
        defer { isLoading = false }
        do {
            self.selection = try await Backend.source(
                profileID: selection.profileID, connection: selection.connection, database: database
            )
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    private func editProfile(_ profile: ConnectionProfile?) {
        profileDraft = profile ?? ConnectionProfile()
        passwordDraft = ""
        rememberPassword = false
        errorMessage = nil
        if let profile {
            do {
                passwordDraft = try ProfilePasswords.load(for: profile.id)
                rememberPassword = !passwordDraft.isEmpty
                if passwordDraft.isEmpty, selection?.profileID == profile.id {
                    passwordDraft = selection?.connection?.password ?? ""
                }
            } catch {
                errorMessage = error.localizedDescription
            }
        }
        editsProfile = true
    }

    private func useRole(_ catalog: RoleCatalog, _ role: DatabaseRole) {
        guard role.name != catalog.currentRole else { return }
        let profile = profiles.first {
            $0.host == catalog.host && $0.port == catalog.port && $0.user == role.name && $0.database == catalog.database
        }
        editProfile(profile)
        if profile == nil {
            profileDraft = ConnectionProfile(
                name: role.name, host: catalog.host, port: catalog.port, database: catalog.database, user: role.name
            )
        }
    }

    private func refreshSource() async {
        guard let selection else { return }
        do {
            var refreshed = try await Backend.source(
                profileID: selection.profileID, connection: selection.connection, database: selection.catalog.database
            )
            if refreshed.catalog.schemas.contains(where: { $0.name == selection.schema }) {
                refreshed.schema = selection.schema
                refreshed.tables = selection.tables?.intersection(refreshed.availableTables)
            }
            self.selection = refreshed
            errorMessage = nil
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    private func saveProfile() async {
        guard !isLoading else { return }
        isLoading = true
        errorMessage = nil
        defer { isLoading = false }
        do {
            let next = try await Backend.source(
                profileID: profileDraft.id, connection: profileDraft.connection(password: passwordDraft)
            )
            let updated = (profiles.filter { $0.id != profileDraft.id } + [profileDraft]).sorted { $0.name < $1.name }
            let encoded = try JSONEncoder().encode(updated)
            try ProfilePasswords.save(rememberPassword ? passwordDraft : "", for: profileDraft.id)
            storedProfiles = encoded
            profileID = profileDraft.id
            selection = next
            passwordDraft = ""
            editsProfile = false
        } catch {
            errorMessage = error.localizedDescription
        }
    }
}
