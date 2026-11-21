import Foundation
import Security

enum ProfilePasswords {
    static func load(for id: UUID) throws -> String {
        var attributes = query(for: id)
        attributes[kSecReturnData as String] = true
        attributes[kSecMatchLimit as String] = kSecMatchLimitOne
        var item: CFTypeRef?
        let status = SecItemCopyMatching(attributes as CFDictionary, &item)
        if status == errSecItemNotFound { return "" }
        try check(status)
        guard let data = item as? Data, let password = String(data: data, encoding: .utf8) else {
            throw AssistantError(message: "Не удалось прочитать пароль из Связки ключей.")
        }
        return password
    }

    static func save(_ password: String, for id: UUID) throws {
        let query = query(for: id)
        if password.isEmpty {
            let status = SecItemDelete(query as CFDictionary)
            if status != errSecItemNotFound { try check(status) }
            return
        }

        let data = [kSecValueData as String: Data(password.utf8)]
        let status = SecItemUpdate(query as CFDictionary, data as CFDictionary)
        if status == errSecItemNotFound {
            try check(SecItemAdd(query.merging(data) { _, value in value } as CFDictionary, nil))
        } else {
            try check(status)
        }
    }

    private static func query(for id: UUID) -> [String: Any] {
        [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: Bundle.main.bundleIdentifier ?? "com.astarino.sql-assistant",
            kSecAttrAccount as String: id.uuidString,
        ]
    }

    private static func check(_ status: OSStatus) throws {
        if status != errSecSuccess {
            let message = SecCopyErrorMessageString(status, nil) as String? ?? "Код \(status)"
            throw AssistantError(message: "Связка ключей: \(message)")
        }
    }
}
