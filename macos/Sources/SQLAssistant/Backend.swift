import Foundation

struct ConnectionSettings: Encodable, Sendable {
    var host = "localhost"
    var port = "5432"
    var database = ""
    var user = ""
    var password = ""
}

struct Clarification: Encodable, Sendable {
    let label: String
    var value = ""
}

struct AssistantRequest: Encodable, Sendable {
    let action: String
    let connection: ConnectionSettings?
    var database: String? = nil
    var schema: String? = nil
    var tables: [String]? = nil
    var question: String? = nil
    var answers: [Clarification]? = nil
}

struct AssistantReply: Decodable, Sendable {
    let catalog: DatabaseCatalog?
    let action: String?
    let sql: String?
    let message: String?
    let clarificationFields: [String]?
    let execution: QueryResult?
    let executionError: String?
    let relationships: [TableRelationship]?
    let error: String?
}

struct TableRelationship: Decodable, Sendable {
    let joinOn: [String]
}

struct QueryResult: Decodable, Sendable {
    let query: String
    let columns: [String]
    let rows: [[String?]]
    let truncated: Bool
}

struct AssistantError: LocalizedError {
    let message: String
    var errorDescription: String? { message }
}

enum Backend {
    static func source(
        profileID: UUID? = nil,
        connection: ConnectionSettings? = nil,
        database: String? = nil
    ) async throws -> DataSourceSelection {
        let reply = try await send(AssistantRequest(action: "catalog", connection: connection, database: database))
        guard let catalog = reply.catalog else {
            throw AssistantError(message: "Не удалось получить список баз и схем PostgreSQL.")
        }
        return DataSourceSelection(profileID: profileID, connection: connection, catalog: catalog)
    }

    static func send(_ request: AssistantRequest) async throws -> AssistantReply {
        try await Task.detached(priority: .userInitiated) {
            try run(request)
        }.value
    }

    private static func run(_ request: AssistantRequest) throws -> AssistantReply {
        let project = Bundle.main.bundleURL.deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
        let python = project.appendingPathComponent(".venv/bin/python")
        guard FileManager.default.isExecutableFile(atPath: python.path) else {
            throw AssistantError(message: "Запусти приложение через macos/run.sh, чтобы установить зависимости Python.")
        }

        let input = Pipe()
        let output = Pipe()
        let process = Process()
        process.executableURL = python
        process.currentDirectoryURL = project
        process.arguments = ["desktop.py"]
        process.standardInput = input
        process.standardOutput = output
        process.standardError = output

        let payload = try JSONEncoder().encode(request)
        try process.run()
        try input.fileHandleForWriting.write(contentsOf: payload)
        try input.fileHandleForWriting.close()
        let data = output.fileHandleForReading.readDataToEndOfFile()
        process.waitUntilExit()

        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        guard process.terminationStatus == 0, let reply = try? decoder.decode(AssistantReply.self, from: data) else {
            throw AssistantError(message: "Python не вернул ответ. Проверь зависимости командой uv sync --frozen.")
        }
        if let error = reply.error {
            throw AssistantError(message: error)
        }
        return reply
    }
}
