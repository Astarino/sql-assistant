import Foundation

struct DatabaseSchema: Decodable, Sendable {
    let name: String
    let tables: [String]
}

struct DatabaseCatalog: Decodable, Sendable {
    let database: String
    let databases: [String]
    let schemas: [DatabaseSchema]
}

struct DataSourceSelection: Sendable {
    let profileID: UUID?
    let connection: ConnectionSettings?
    let catalog: DatabaseCatalog
    var schema: String
    var tables: Set<String>?

    init(profileID: UUID?, connection: ConnectionSettings?, catalog: DatabaseCatalog) {
        self.profileID = profileID
        self.connection = connection
        self.catalog = catalog
        schema = catalog.schemas.first { $0.name == "public" }?.name ?? catalog.schemas.first?.name ?? ""
    }

    var availableTables: [String] {
        catalog.schemas.first { $0.name == schema }?.tables ?? []
    }

    var canApply: Bool {
        !availableTables.isEmpty && tables?.isEmpty != true
    }
}

struct ConnectionProfile: Codable, Identifiable, Sendable {
    var id = UUID()
    var name = ""
    var host = "localhost"
    var port = "5432"
    var database = "postgres"
    var user = ""

    func connection(password: String) -> ConnectionSettings {
        ConnectionSettings(host: host, port: port, database: database, user: user, password: password)
    }
}
