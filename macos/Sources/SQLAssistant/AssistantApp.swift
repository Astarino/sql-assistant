import AppKit
import SwiftUI

@main
struct AssistantApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) private var delegate

    var body: some Scene {
        WindowGroup("SQL Assistant") {
            AssistantView()
                .frame(minWidth: 380, minHeight: 310)
        }
        .defaultSize(width: 510, height: 400)
        .commands { CommandGroup(replacing: .newItem) {} }
    }
}

final class AppDelegate: NSObject, NSApplicationDelegate {
    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.regular)
        NSApp.activate()
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool {
        true
    }
}

struct FloatingWindow: NSViewRepresentable {
    let isPinned: Bool

    func makeNSView(context: Context) -> WindowAnchor { WindowAnchor() }

    func updateNSView(_ view: WindowAnchor, context: Context) {
        view.isPinned = isPinned
    }

    final class WindowAnchor: NSView {
        var isPinned = false {
            didSet { updateLevel() }
        }

        override func viewDidMoveToWindow() {
            super.viewDidMoveToWindow()
            updateLevel()
        }

        private func updateLevel() {
            window?.level = isPinned ? .floating : .normal
        }
    }
}
