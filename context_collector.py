"""
프로젝트 컨텍스트 수집기

변경된 파일 하나를 리뷰할 때, 프로젝트 전체 맥락에서 이해할 수 있도록
관련 파일과 인터페이스를 자동으로 수집합니다.

수집 항목:
1. 프로젝트 디렉토리 구조 (트리)
2. import/의존 파일의 인터페이스 (protocol, class, struct 시그니처)
3. 부모 클래스 / 프로토콜 정의
4. 이 타입을 사용하는 호출부 (callers)
5. 관련 테스트 파일
6. SwiftLint 결과 (선택)
"""

import os
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path


# ──────────────────────────────────────────
# 데이터 구조
# ──────────────────────────────────────────

@dataclass
class FileContext:
    """변경된 파일 하나에 대한 프로젝트 컨텍스트"""
    filepath: str
    diff: str
    full_content: str

    # 프로젝트 구조
    project_tree: str = ""

    # 의존 파일들의 인터페이스 (import하는 파일들)
    dependency_interfaces: dict[str, str] = field(default_factory=dict)

    # 이 파일이 구현/상속하는 프로토콜, 부모 클래스
    protocol_definitions: dict[str, str] = field(default_factory=dict)

    # 이 타입을 사용하는 다른 파일들 (호출부)
    caller_snippets: dict[str, str] = field(default_factory=dict)

    # 관련 테스트 파일
    test_content: dict[str, str] = field(default_factory=dict)

    # SwiftLint 결과
    swiftlint_output: str = ""

    # SourceKit-LSP 분석 결과 (컴파일러 수준)
    lsp_analysis: str = ""


# ──────────────────────────────────────────
# 1. 프로젝트 트리
# ──────────────────────────────────────────

def build_project_tree(max_depth: int = 4) -> str:
    """프로젝트의 Swift 파일 구조를 트리 형태로 생성합니다."""
    ignore_dirs = {
        "Pods", "DerivedData", ".build", "build", ".git",
        "node_modules", "Carthage", ".swiftpm", "xcuserdata",
    }
    ignore_exts = {".o", ".d", ".dia", ".hmap", ".modulemap"}

    lines = []
    root = Path(".")

    def walk(path: Path, prefix: str, depth: int):
        if depth > max_depth:
            return

        entries = sorted(path.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
        dirs = [e for e in entries if e.is_dir() and e.name not in ignore_dirs and not e.name.startswith(".")]
        files = [e for e in entries if e.is_file() and e.suffix in {".swift", ".xib", ".storyboard", ".plist", ".yml", ".yaml"}]

        items = dirs + files
        for i, item in enumerate(items):
            is_last = (i == len(items) - 1)
            connector = "└── " if is_last else "├── "
            extension = "    " if is_last else "│   "

            if item.is_dir():
                lines.append(f"{prefix}{connector}{item.name}/")
                walk(item, prefix + extension, depth + 1)
            else:
                lines.append(f"{prefix}{connector}{item.name}")

    try:
        walk(root, "", 0)
    except Exception:
        pass

    return "\n".join(lines[:200])  # 200줄 제한


# ──────────────────────────────────────────
# 2. Swift 파일 파싱 유틸리티
# ──────────────────────────────────────────

def find_swift_files() -> list[Path]:
    """프로젝트 내 모든 Swift 파일을 찾습니다."""
    ignore_dirs = {"Pods", "DerivedData", ".build", "build", "Carthage", ".git"}
    result = []
    for root, dirs, files in os.walk("."):
        dirs[:] = [d for d in dirs if d not in ignore_dirs and not d.startswith(".")]
        for f in files:
            if f.endswith(".swift"):
                result.append(Path(root) / f)
    return result


def extract_type_names(content: str) -> list[str]:
    """파일에서 정의된 타입 이름들을 추출합니다 (class, struct, enum, protocol, actor)."""
    pattern = r'(?:class|struct|enum|protocol|actor)\s+(\w+)'
    return re.findall(pattern, content)


def extract_imports(content: str) -> list[str]:
    """파일의 import 문을 추출합니다."""
    pattern = r'^import\s+(\w+)'
    return re.findall(pattern, content, re.MULTILINE)


def extract_interface(content: str) -> str:
    """파일에서 공개 인터페이스만 추출합니다.
    protocol, class/struct/enum 선언, public/open 함수 시그니처, 프로퍼티 선언 등.
    구현 본문은 제거하고 시그니처만 남깁니다.
    """
    lines = content.split("\n")
    interface_lines = []
    brace_depth = 0
    in_function_body = False
    current_type_depth = 0

    for line in lines:
        stripped = line.strip()

        # 빈 줄, 주석 건너뛰기
        if not stripped or stripped.startswith("//"):
            continue

        # import 문
        if stripped.startswith("import "):
            interface_lines.append(stripped)
            continue

        # 타입 선언 (class, struct, enum, protocol, actor)
        type_match = re.match(
            r'((?:public|open|internal|@\w+\s+)*(?:final\s+)?'
            r'(?:class|struct|enum|protocol|actor))\s+(\w+[^{]*)',
            stripped
        )
        if type_match:
            # 인터페이스에 타입 선언 추가
            decl = stripped.rstrip("{").strip()
            interface_lines.append(f"\n{decl} {{")
            current_type_depth = brace_depth
            brace_depth += stripped.count("{") - stripped.count("}")
            continue

        # 프로퍼티 선언 (var/let)
        prop_match = re.match(
            r'\s*((?:public|open|internal|private\(set\)|@\w+\s+)*'
            r'(?:static\s+|class\s+)?(?:var|let))\s+(\w+)',
            stripped
        )
        if prop_match and brace_depth <= current_type_depth + 1:
            # 프로퍼티 시그니처만 (getter/setter 본문 제외)
            # 타입 어노테이션까지만 추출
            prop_line = re.match(r'[^{=]+', stripped)
            if prop_line:
                interface_lines.append(f"    {prop_line.group().strip()}")

        # 함수/메서드 선언
        func_match = re.match(
            r'\s*((?:public|open|internal|@\w+\s+|override\s+|static\s+|class\s+)*'
            r'func)\s+(\w+[^{]*)',
            stripped
        )
        if func_match and brace_depth <= current_type_depth + 1:
            sig = stripped.split("{")[0].strip()
            interface_lines.append(f"    {sig}")
            in_function_body = True

        # init 선언
        init_match = re.match(
            r'\s*((?:public|open|required|convenience)\s+)?init[^{]*',
            stripped
        )
        if init_match and brace_depth <= current_type_depth + 1:
            sig = stripped.split("{")[0].strip()
            interface_lines.append(f"    {sig}")

        # 닫는 중괄호 (타입 닫기)
        brace_depth += stripped.count("{") - stripped.count("}")
        if brace_depth <= current_type_depth and interface_lines and interface_lines[-1] != "}":
            interface_lines.append("}")

    # 끝 정리
    if interface_lines and interface_lines[-1] != "}":
        interface_lines.append("}")

    result = "\n".join(interface_lines)
    return result[:3000]  # 3000자 제한


# ──────────────────────────────────────────
# 3. 의존성 분석
# ──────────────────────────────────────────

def find_dependencies(filepath: str, content: str, all_files: list[Path]) -> dict[str, str]:
    """파일이 의존하는 프로젝트 내 다른 파일들의 인터페이스를 수집합니다.

    방법:
    1. 파일 내에서 사용되는 타입 이름을 추출
    2. 프로젝트 내 다른 파일에서 해당 타입이 정의된 곳을 찾음
    3. 해당 파일의 인터페이스를 추출
    """
    # 현재 파일에서 참조하는 타입 후보 추출
    # UpperCamelCase 단어 = 타입 이름 후보
    type_refs = set(re.findall(r'\b([A-Z][a-zA-Z0-9]+)\b', content))

    # Swift 기본 타입 제외
    swift_builtins = {
        "String", "Int", "Double", "Float", "Bool", "Array", "Dictionary",
        "Set", "Optional", "Result", "Error", "Void", "Any", "AnyObject",
        "URL", "Data", "Date", "UUID", "CGFloat", "CGPoint", "CGSize",
        "CGRect", "NSObject", "UIView", "UIViewController", "View", "Text",
        "Button", "Image", "List", "NavigationView", "VStack", "HStack",
        "ZStack", "State", "Binding", "Published", "ObservableObject",
        "EnvironmentObject", "StateObject", "Observable", "MainActor",
        "Task", "AsyncSequence", "Sendable", "Codable", "Equatable",
        "Hashable", "Identifiable", "Comparable", "CustomStringConvertible",
        "Never", "Some", "Self", "Type", "Protocol",
    }
    type_refs -= swift_builtins

    dependencies = {}
    target_path = Path(filepath)

    for swift_file in all_files:
        if swift_file.resolve() == target_path.resolve():
            continue

        try:
            file_content = swift_file.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue

        # 이 파일에서 정의된 타입 이름
        defined_types = set(extract_type_names(file_content))

        # 현재 파일이 참조하는 타입이 이 파일에 정의되어 있으면 → 의존성
        matching_types = type_refs & defined_types
        if matching_types:
            interface = extract_interface(file_content)
            if interface.strip():
                rel_path = str(swift_file)
                dependencies[rel_path] = interface

        # 의존성 파일 최대 8개
        if len(dependencies) >= 8:
            break

    return dependencies


# ──────────────────────────────────────────
# 4. 프로토콜/부모 클래스 정의 추출
# ──────────────────────────────────────────

def find_protocol_definitions(content: str, all_files: list[Path], filepath: str) -> dict[str, str]:
    """파일이 구현하는 프로토콜이나 상속하는 부모 클래스의 정의를 찾습니다."""

    # class Foo: Bar, BazProtocol / struct Foo: SomeProtocol
    pattern = r'(?:class|struct|enum|actor)\s+\w+\s*:\s*([^{]+)'
    matches = re.findall(pattern, content)

    conformances = set()
    for match in matches:
        # 제네릭 파라미터 제거
        clean = re.sub(r'<[^>]+>', '', match)
        for item in clean.split(","):
            name = item.strip().split("<")[0].strip()
            if name and name[0].isupper():
                conformances.add(name)

    # Swift 기본 프로토콜 제외
    builtin_protocols = {
        "Codable", "Decodable", "Encodable", "Equatable", "Hashable",
        "Comparable", "Identifiable", "CustomStringConvertible", "Error",
        "Sendable", "ObservableObject", "View", "App", "Scene",
        "UIViewController", "UIView", "UITableViewDelegate",
        "UITableViewDataSource", "UICollectionViewDelegate",
        "UICollectionViewDataSource", "NSObject", "NSCoding",
    }
    conformances -= builtin_protocols

    definitions = {}
    target_path = Path(filepath)

    for proto_name in conformances:
        for swift_file in all_files:
            if swift_file.resolve() == target_path.resolve():
                continue
            try:
                file_content = swift_file.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue

            # 해당 프로토콜/클래스가 이 파일에 정의되어 있는지
            if re.search(rf'(?:protocol|class|struct)\s+{re.escape(proto_name)}\b', file_content):
                interface = extract_interface(file_content)
                if interface.strip():
                    definitions[f"{proto_name} ({swift_file})"] = interface
                break

    return definitions


# ──────────────────────────────────────────
# 5. 호출부 (Callers) 수집
# ──────────────────────────────────────────

def find_callers(filepath: str, content: str, all_files: list[Path]) -> dict[str, str]:
    """이 파일에서 정의된 타입을 사용하는 다른 파일들의 관련 스니펫을 수집합니다."""

    defined_types = extract_type_names(content)
    if not defined_types:
        return {}

    callers = {}
    target_path = Path(filepath)

    # 타입별 regex 패턴 미리 생성
    patterns = [re.compile(rf'\b{re.escape(t)}\b') for t in defined_types]

    for swift_file in all_files:
        if swift_file.resolve() == target_path.resolve():
            continue

        try:
            file_content = swift_file.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue

        # 이 파일에서 우리 타입을 사용하는지
        matched_lines = []
        for i, line in enumerate(file_content.split("\n"), 1):
            for pat in patterns:
                if pat.search(line):
                    # 해당 라인 + 주변 2줄
                    all_lines = file_content.split("\n")
                    start = max(0, i - 3)
                    end = min(len(all_lines), i + 2)
                    snippet = "\n".join(
                        f"{'>' if j == i - 1 else ' '} {j+1}: {all_lines[j]}"
                        for j in range(start, end)
                    )
                    matched_lines.append(snippet)
                    break

            if len(matched_lines) >= 3:  # 파일당 최대 3군데
                break

        if matched_lines:
            callers[str(swift_file)] = "\n---\n".join(matched_lines)

        if len(callers) >= 5:  # 최대 5개 파일
            break

    return callers


# ──────────────────────────────────────────
# 6. 관련 테스트 파일
# ──────────────────────────────────────────

def find_related_tests(filepath: str, all_files: list[Path]) -> dict[str, str]:
    """변경된 파일과 관련된 테스트 파일을 찾습니다."""
    filename = Path(filepath).stem  # e.g., "HomeViewModel"

    # 테스트 파일 후보: HomeViewModelTests, HomeViewModelSpec, TestHomeViewModel
    test_patterns = [
        f"{filename}Tests",
        f"{filename}Spec",
        f"{filename}Test",
        f"Test{filename}",
    ]

    tests = {}
    for swift_file in all_files:
        stem = swift_file.stem
        if any(stem == pat or stem.startswith(pat) for pat in test_patterns):
            try:
                content = swift_file.read_text(encoding="utf-8", errors="ignore")
                tests[str(swift_file)] = content[:4000]  # 4000자 제한
            except Exception:
                continue

        if len(tests) >= 3:
            break

    return tests


# ──────────────────────────────────────────
# 7. SwiftLint 결과 (선택)
# ──────────────────────────────────────────

def run_swiftlint(filepath: str) -> str:
    """SwiftLint가 있으면 해당 파일에 대해 실행합니다."""
    try:
        result = subprocess.run(
            ["swiftlint", "lint", "--path", filepath, "--reporter", "json", "--quiet"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0 or result.stdout:
            return result.stdout[:2000]
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return ""


# ──────────────────────────────────────────
# 메인: 컨텍스트 수집
# ──────────────────────────────────────────

def collect_context(
    filepath: str,
    diff: str,
    full_content: str,
    head_sha: str,
    enable_swiftlint: bool = False,
    enable_lsp: bool = False,
) -> FileContext:
    """변경된 파일 하나에 대한 전체 프로젝트 컨텍스트를 수집합니다."""

    ctx = FileContext(
        filepath=filepath,
        diff=diff,
        full_content=full_content,
    )

    # 프로젝트 내 모든 Swift 파일
    all_files = find_swift_files()

    print(f"    📁 프로젝트 Swift 파일: {len(all_files)}개")

    # 1. 프로젝트 트리
    ctx.project_tree = build_project_tree()

    # 2. 의존 파일 인터페이스
    ctx.dependency_interfaces = find_dependencies(filepath, full_content, all_files)
    print(f"    🔗 의존 파일: {len(ctx.dependency_interfaces)}개")

    # 3. 프로토콜/부모 클래스
    ctx.protocol_definitions = find_protocol_definitions(full_content, all_files, filepath)
    print(f"    📐 프로토콜/부모: {len(ctx.protocol_definitions)}개")

    # 4. 호출부
    ctx.caller_snippets = find_callers(filepath, full_content, all_files)
    print(f"    📞 호출부: {len(ctx.caller_snippets)}개 파일")

    # 5. 테스트 파일
    ctx.test_content = find_related_tests(filepath, all_files)
    print(f"    🧪 테스트: {len(ctx.test_content)}개")

    # 6. SwiftLint
    if enable_swiftlint:
        ctx.swiftlint_output = run_swiftlint(filepath)

    # 7. SourceKit-LSP (컴파일러 수준 분석)
    if enable_lsp:
        try:
            from sourcekit_lsp import (
                SourceKitLSPClient,
                analyze_with_lsp,
                format_lsp_analysis,
                check_swift_toolchain,
            )

            toolchain = check_swift_toolchain()
            if toolchain["available"] and toolchain["sourcekit_lsp"]:
                print(f"    🔬 SourceKit-LSP 분석 중... ({toolchain['version']})")
                client = SourceKitLSPClient()
                if client.start():
                    try:
                        analysis = analyze_with_lsp(filepath, full_content, client)
                        ctx.lsp_analysis = format_lsp_analysis(analysis)
                        if ctx.lsp_analysis:
                            print(f"    🔬 LSP: 타입 {len(analysis.type_annotations)}개, "
                                  f"hover {len(analysis.hover_info)}개, "
                                  f"참조 {len(analysis.external_references)}개")
                    finally:
                        client.stop()
                else:
                    print("    ⚠️  SourceKit-LSP 시작 실패 → Regex fallback")
            else:
                print(f"    ⚠️  Swift toolchain 없음 → Regex fallback")
        except ImportError:
            print("    ⚠️  sourcekit_lsp 모듈 없음 → Regex fallback")
        except Exception as e:
            print(f"    ⚠️  LSP 분석 실패 ({e}) → Regex fallback")

    return ctx


def format_context_for_prompt(ctx: FileContext) -> str:
    """수집된 컨텍스트를 LLM 프롬프트용 텍스트로 포맷팅합니다."""

    sections = []

    # 프로젝트 구조
    if ctx.project_tree:
        sections.append(f"""## 📁 프로젝트 구조
```
{ctx.project_tree}
```""")

    # 의존 파일 인터페이스
    if ctx.dependency_interfaces:
        deps = []
        for path, interface in ctx.dependency_interfaces.items():
            deps.append(f"### `{path}` (인터페이스)\n```swift\n{interface}\n```")
        sections.append("## 🔗 의존 파일 인터페이스\n이 파일이 사용하는 타입들의 정의입니다.\n\n" + "\n\n".join(deps))

    # 프로토콜/부모 클래스
    if ctx.protocol_definitions:
        protos = []
        for name, definition in ctx.protocol_definitions.items():
            protos.append(f"### `{name}`\n```swift\n{definition}\n```")
        sections.append("## 📐 구현/상속 대상 정의\n이 파일이 conform하거나 상속하는 타입들입니다.\n\n" + "\n\n".join(protos))

    # 호출부
    if ctx.caller_snippets:
        callers = []
        for path, snippet in ctx.caller_snippets.items():
            callers.append(f"### `{path}`\n```\n{snippet}\n```")
        sections.append("## 📞 호출부 (이 타입을 사용하는 곳)\n이 파일의 타입을 사용하는 다른 파일들입니다. 변경이 기존 사용부에 영향을 주는지 확인하세요.\n\n" + "\n\n".join(callers))

    # 테스트
    if ctx.test_content:
        tests = []
        for path, content in ctx.test_content.items():
            tests.append(f"### `{path}`\n```swift\n{content}\n```")
        sections.append("## 🧪 관련 테스트\n\n" + "\n\n".join(tests))

    # SwiftLint
    if ctx.swiftlint_output:
        sections.append(f"## 🔧 SwiftLint 결과\n```json\n{ctx.swiftlint_output}\n```")

    # SourceKit-LSP
    if ctx.lsp_analysis:
        sections.append(ctx.lsp_analysis)

    return "\n\n---\n\n".join(sections)
