import Foundation

struct ModelDownloadProgress {
    let downloaded: Int64
    let total: Int64
}

struct OllamaSetupClient {
    static let model = "qwen3.5:4b"
    var endpoint = URL(string: "http://127.0.0.1:11434")!

    static var installedCommand: URL? {
        let path = ProcessInfo.processInfo.environment["PATH"] ?? ""
        let folders = path.split(separator: ":").map(String.init) + ["/opt/homebrew/bin", "/usr/local/bin"]
        return folders.lazy
            .map { URL(fileURLWithPath: $0, isDirectory: true).appendingPathComponent("ollama") }
            .first { FileManager.default.isExecutableFile(atPath: $0.path) }
    }

    func startServer(executable: URL) throws -> Process {
        let server = Process()
        server.executableURL = executable
        server.arguments = ["serve"]
        var environment = ProcessInfo.processInfo.environment
        environment["OLLAMA_HOST"] = endpoint.absoluteString
        server.environment = environment
        server.standardInput = FileHandle.nullDevice
        server.standardOutput = FileHandle.nullDevice
        server.standardError = FileHandle.nullDevice
        try server.run()
        return server
    }

    func waitForServer(_ server: Process?) async throws -> Bool {
        let deadline = ContinuousClock.now + .seconds(12)
        while true {
            try Task.checkCancellation()
            do {
                return try await hasModel()
            } catch let error as URLError where [.cannotConnectToHost, .networkConnectionLost, .timedOut].contains(error.code) {
                if server?.isRunning == false {
                    throw AssistantError(message: "Ollama завершилась при запуске. Попробуй запустить `ollama serve` в Терминале и проверить подключение.")
                }
                if ContinuousClock.now >= deadline {
                    throw AssistantError(message: "Ollama пока не ответила. Нажми «Проверить подключение» ещё раз.")
                }
                try await Task.sleep(for: .milliseconds(350))
            }
        }
    }

    func hasModel() async throws -> Bool {
        var request = URLRequest(url: endpoint.appendingPathComponent("api/tags"))
        request.timeoutInterval = 3
        request.cachePolicy = .reloadIgnoringLocalCacheData
        let (data, response) = try await URLSession.shared.data(for: request)
        try check(response)
        let inventory = try JSONDecoder().decode(ModelList.self, from: data)
        return inventory.models.contains { $0.name == Self.model }
    }

    func download(progress: (ModelDownloadProgress) -> Void) async throws {
        var request = URLRequest(url: endpoint.appendingPathComponent("api/pull"))
        request.httpMethod = "POST"
        request.timeoutInterval = 60
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONEncoder().encode(PullRequest(model: Self.model))

        let (bytes, response) = try await URLSession.shared.bytes(for: request)
        defer { bytes.task.cancel() }
        try check(response)
        let decoder = JSONDecoder()
        var layers: [String: ModelDownloadProgress] = [:]
        for try await line in bytes.lines where !line.isEmpty {
            try Task.checkCancellation()
            let event = try decoder.decode(PullEvent.self, from: Data(line.utf8))
            if let error = event.error { throw AssistantError(message: error) }
            if event.status == "success" { return }

            if let digest = event.digest, let size = event.total, size > 0 {
                let downloaded = min(max(event.completed ?? 0, 0), size)
                layers[digest] = ModelDownloadProgress(downloaded: downloaded, total: size)
                progress(ModelDownloadProgress(
                    downloaded: layers.values.reduce(0) { $0 + $1.downloaded },
                    total: layers.values.reduce(0) { $0 + $1.total }
                ))
            }
        }
        throw AssistantError(message: "Ollama не подтвердила завершение загрузки. Попробуй ещё раз.")
    }

    private func check(_ response: URLResponse) throws {
        guard let response = response as? HTTPURLResponse else {
            throw AssistantError(message: "Не удалось прочитать ответ Ollama.")
        }
        guard (200..<300).contains(response.statusCode) else {
            throw AssistantError(message: "Ollama вернула ошибку HTTP \(response.statusCode).")
        }
    }

    private struct ModelList: Decodable {
        struct Model: Decodable { let name: String }
        let models: [Model]
    }

    private struct PullRequest: Encodable {
        let model: String
        let stream = true
    }

    private struct PullEvent: Decodable {
        let status: String?
        let digest: String?
        let total: Int64?
        let completed: Int64?
        let error: String?
    }
}
