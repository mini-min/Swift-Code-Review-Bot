"""iOS 참조 링크 데이터베이스 — Apple Docs, WWDC, 커뮤니티"""

APPLE_DOCS = {
    "memory_management": [
        {"topic": "ARC", "url": "https://docs.swift.org/swift-book/documentation/the-swift-programming-language/automaticreferencecounting/", "keywords": ["retain cycle", "weak", "unowned", "strong reference", "deinit", "memory leak"]},
        {"topic": "Preventing Timing Problems When Using Closures", "url": "https://developer.apple.com/documentation/swift/preventing-timing-problems-when-using-closures", "keywords": ["closure", "capture list", "weak self", "escaping"]},
    ],
    "concurrency": [
        {"topic": "Swift Concurrency", "url": "https://docs.swift.org/swift-book/documentation/the-swift-programming-language/concurrency/", "keywords": ["async", "await", "Task", "actor", "structured concurrency"]},
        {"topic": "MainActor", "url": "https://developer.apple.com/documentation/swift/mainactor", "keywords": ["MainActor", "main thread", "UI update"]},
        {"topic": "Sendable", "url": "https://developer.apple.com/documentation/swift/sendable", "keywords": ["Sendable", "data race", "thread safety"]},
    ],
    "swift_conventions": [
        {"topic": "Swift API Design Guidelines", "url": "https://www.swift.org/documentation/api-design-guidelines/", "keywords": ["naming", "convention", "API design", "clarity"]},
        {"topic": "Optional Chaining", "url": "https://docs.swift.org/swift-book/documentation/the-swift-programming-language/optionalchaining/", "keywords": ["optional", "guard let", "if let", "nil"]},
        {"topic": "Error Handling", "url": "https://docs.swift.org/swift-book/documentation/the-swift-programming-language/errorhandling/", "keywords": ["try", "catch", "throw", "Result", "error handling"]},
        {"topic": "Access Control", "url": "https://docs.swift.org/swift-book/documentation/the-swift-programming-language/accesscontrol/", "keywords": ["private", "internal", "public", "access control"]},
    ],
    "performance": [
        {"topic": "Improving Your App's Performance", "url": "https://developer.apple.com/documentation/xcode/improving-your-app-s-performance", "keywords": ["performance", "optimization", "instruments"]},
    ],
    "swiftui": [
        {"topic": "Managing Model Data", "url": "https://developer.apple.com/documentation/swiftui/managing-model-data-in-your-app", "keywords": ["ObservableObject", "StateObject", "Observable"]},
        {"topic": "Observation Framework", "url": "https://developer.apple.com/documentation/observation", "keywords": ["@Observable", "observation"]},
    ],
    "security": [
        {"topic": "Keychain Services", "url": "https://developer.apple.com/documentation/security/keychain_services", "keywords": ["keychain", "secure storage", "credentials"]},
        {"topic": "App Transport Security", "url": "https://developer.apple.com/documentation/bundleresources/information_property_list/nsapptransportsecurity", "keywords": ["ATS", "HTTPS", "transport security"]},
    ],
    "accessibility": [
        {"topic": "Accessibility in SwiftUI", "url": "https://developer.apple.com/documentation/swiftui/accessibility", "keywords": ["accessibility", "VoiceOver", "Dynamic Type"]},
    ],
}

WWDC_SESSIONS = [
    {"title": "Eliminate data races using Swift Concurrency", "year": 2022, "url": "https://developer.apple.com/videos/play/wwdc2022/110351/", "keywords": ["data race", "Sendable", "actor", "concurrency"]},
    {"title": "Visualize and optimize Swift concurrency", "year": 2022, "url": "https://developer.apple.com/videos/play/wwdc2022/110350/", "keywords": ["concurrency", "instruments", "task"]},
    {"title": "Discover Observation in SwiftUI", "year": 2023, "url": "https://developer.apple.com/videos/play/wwdc2023/10149/", "keywords": ["Observable", "SwiftUI", "state management"]},
    {"title": "Demystify SwiftUI performance", "year": 2023, "url": "https://developer.apple.com/videos/play/wwdc2023/10160/", "keywords": ["SwiftUI", "performance", "view update"]},
    {"title": "Beyond the basics of structured concurrency", "year": 2023, "url": "https://developer.apple.com/videos/play/wwdc2023/10170/", "keywords": ["TaskGroup", "async let", "cancellation"]},
    {"title": "A Swift Tour: Explore Swift's features and design", "year": 2024, "url": "https://developer.apple.com/videos/play/wwdc2024/10184/", "keywords": ["Swift 6", "strict concurrency", "typed throws"]},
    {"title": "Analyze heap memory", "year": 2024, "url": "https://developer.apple.com/videos/play/wwdc2024/10173/", "keywords": ["memory", "heap", "leak", "retain cycle"]},
    {"title": "Migrate your app to Swift 6", "year": 2024, "url": "https://developer.apple.com/videos/play/wwdc2024/10169/", "keywords": ["Swift 6", "migration", "Sendable"]},
    {"title": "Meet Swift Testing", "year": 2024, "url": "https://developer.apple.com/videos/play/wwdc2024/10179/", "keywords": ["testing", "Swift Testing", "@Test"]},
]

COMMUNITY_REFS = [
    {"source": "Swift Evolution", "url": "https://github.com/swiftlang/swift-evolution", "keywords": ["SE-", "proposal", "evolution"]},
    {"source": "Swift Forums", "url": "https://forums.swift.org", "keywords": ["discussion", "proposal", "community"]},
    {"source": "SwiftLint Rules", "url": "https://realm.github.io/SwiftLint/rule-directory.html", "keywords": ["swiftlint", "lint", "static analysis"]},
]


def build_reference_prompt() -> str:
    sections = []
    sections.append("## 📖 Apple 공식 문서")
    for _, refs in APPLE_DOCS.items():
        for r in refs:
            sections.append(f"- [{r['topic']}]({r['url']}) — {', '.join(r['keywords'])}")
    sections.append("\n## 🎬 WWDC 세션")
    for s in WWDC_SESSIONS:
        sections.append(f"- [{s['title']} (WWDC{s['year']})]({s['url']}) — {', '.join(s['keywords'])}")
    sections.append("\n## 🌐 커뮤니티")
    for r in COMMUNITY_REFS:
        sections.append(f"- [{r['source']}]({r['url']}) — {', '.join(r['keywords'])}")
    return "\n".join(sections)
