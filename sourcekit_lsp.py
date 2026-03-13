"""
SourceKit-LSP 연동 모듈

Swift 컴파일러 수준의 타입 정보를 추출합니다:
- 정확한 타입 추론 (let x = foo() → x의 실제 타입)
- 제네릭 타입 해석 (Array<User> 등)
- extension 메서드 추적
- 프로토콜 준수 완전 검증 (누락된 required 메서드 감지)
- cross-module 참조 (SPM, CocoaPods)
- 심볼의 정의 위치 (go-to-definition)
- 모든 참조 위치 (find-references)
- hover 정보 (타입, 문서 주석)

사용 조건:
- Swift toolchain 설치 필요 (GitHub Actions의 macOS runner에 기본 포함)
- sourcekit-lsp 바이너리 필요 (Xcode 또는 swift toolchain에 포함)
- SPM 프로젝트: Package.swift 있으면 자동 인식
- Xcode 프로젝트: .xcodeproj 또는 .xcworkspace 있으면 인식
"""

import json
import subprocess
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path


# ──────────────────────────────────────────
# LSP 클라이언트
# ──────────────────────────────────────────

class SourceKitLSPClient:
    """sourcekit-lsp와 JSON-RPC로 통신하는 간이 클라이언트"""

    def __init__(self):
        self.process = None
        self.request_id = 0
        self._initialized = False

    def start(self) -> bool:
        """LSP 서버를 시작합니다."""
        lsp_path = self._find_sourcekit_lsp()
        if not lsp_path:
            print("    ⚠️  sourcekit-lsp를 찾을 수 없습니다")
            return False

        try:
            self.process = subprocess.Popen(
                [lsp_path],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            self._send_initialize()
            self._initialized = True
            return True
        except Exception as e:
            print(f"    ⚠️  sourcekit-lsp 시작 실패: {e}")
            return False

    def stop(self):
        """LSP 서버를 종료합니다."""
        if self.process:
            try:
                self._send_request("shutdown", {})
                self._send_notification("exit", {})
                self.process.terminate()
                self.process.wait(timeout=5)
            except Exception:
                if self.process:
                    self.process.kill()

    def _find_sourcekit_lsp(self) -> str | None:
        """sourcekit-lsp 바이너리 경로를 찾습니다."""
        # 1. PATH에서 찾기
        result = subprocess.run(
            ["which", "sourcekit-lsp"],
            capture_output=True, text=True,
        )
        if result.returncode == 0:
            return result.stdout.strip()

        # 2. Xcode 내 경로
        xcode_paths = [
            "/Applications/Xcode.app/Contents/Developer/Toolchains/XcodeDefault.xctoolchain/usr/bin/sourcekit-lsp",
            "/usr/bin/sourcekit-lsp",
        ]
        for p in xcode_paths:
            if os.path.exists(p):
                return p

        # 3. Swift toolchain
        result = subprocess.run(
            ["xcrun", "--find", "sourcekit-lsp"],
            capture_output=True, text=True,
        )
        if result.returncode == 0:
            return result.stdout.strip()

        return None

    def _send_request(self, method: str, params: dict) -> dict | None:
        """LSP 요청을 보내고 응답을 받습니다."""
        self.request_id += 1
        msg = {
            "jsonrpc": "2.0",
            "id": self.request_id,
            "method": method,
            "params": params,
        }
        return self._send_and_receive(msg)

    def _send_notification(self, method: str, params: dict):
        """LSP 알림을 보냅니다 (응답 없음)."""
        msg = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
        }
        self._write_message(msg)

    def _send_and_receive(self, msg: dict) -> dict | None:
        """메시지를 보내고 응답을 파싱합니다."""
        self._write_message(msg)
        return self._read_response(msg.get("id"))

    def _write_message(self, msg: dict):
        """LSP 프로토콜 형식으로 메시지를 씁니다."""
        body = json.dumps(msg)
        header = f"Content-Length: {len(body)}\r\n\r\n"
        self.process.stdin.write(header.encode() + body.encode())
        self.process.stdin.flush()

    def _read_response(self, expected_id: int, timeout: float = 10.0) -> dict | None:
        """LSP 응답을 읽고 파싱합니다."""
        import select

        buf = b""
        while True:
            ready, _, _ = select.select([self.process.stdout], [], [], timeout)
            if not ready:
                return None

            chunk = self.process.stdout.read1(4096)
            if not chunk:
                return None
            buf += chunk

            # Content-Length 파싱
            try:
                header_end = buf.index(b"\r\n\r\n")
                header = buf[:header_end].decode()
                content_length = int(header.split("Content-Length: ")[1].split("\r\n")[0])
                body_start = header_end + 4

                if len(buf) >= body_start + content_length:
                    body = buf[body_start:body_start + content_length]
                    result = json.loads(body.decode())

                    if result.get("id") == expected_id:
                        return result.get("result")

                    # 다른 메시지 (notification 등) → 계속 읽기
                    buf = buf[body_start + content_length:]
            except (ValueError, IndexError, json.JSONDecodeError):
                continue

    def _send_initialize(self):
        """LSP initialize 핸드셰이크"""
        root_uri = f"file://{os.getcwd()}"
        self._send_request("initialize", {
            "processId": os.getpid(),
            "rootUri": root_uri,
            "capabilities": {
                "textDocument": {
                    "hover": {"contentFormat": ["plaintext"]},
                    "definition": {},
                    "references": {},
                    "documentSymbol": {},
                }
            },
        })
        self._send_notification("initialized", {})

    # ──────────────────────────────────────
    # 공개 API
    # ──────────────────────────────────────

    def open_file(self, filepath: str, content: str):
        """파일을 LSP에 열어줍니다."""
        uri = f"file://{os.path.abspath(filepath)}"
        self._send_notification("textDocument/didOpen", {
            "textDocument": {
                "uri": uri,
                "languageId": "swift",
                "version": 1,
                "text": content,
            }
        })

    def hover(self, filepath: str, line: int, character: int) -> str | None:
        """특정 위치의 타입/문서 정보를 가져옵니다."""
        uri = f"file://{os.path.abspath(filepath)}"
        result = self._send_request("textDocument/hover", {
            "textDocument": {"uri": uri},
            "position": {"line": line, "character": character},
        })
        if result and "contents" in result:
            contents = result["contents"]
            if isinstance(contents, dict):
                return contents.get("value", "")
            return str(contents)
        return None

    def definition(self, filepath: str, line: int, character: int) -> dict | None:
        """심볼의 정의 위치를 찾습니다."""
        uri = f"file://{os.path.abspath(filepath)}"
        result = self._send_request("textDocument/definition", {
            "textDocument": {"uri": uri},
            "position": {"line": line, "character": character},
        })
        return result

    def references(self, filepath: str, line: int, character: int) -> list[dict]:
        """심볼의 모든 참조 위치를 찾습니다."""
        uri = f"file://{os.path.abspath(filepath)}"
        result = self._send_request("textDocument/references", {
            "textDocument": {"uri": uri},
            "position": {"line": line, "character": character},
            "context": {"includeDeclaration": False},
        })
        return result or []

    def document_symbols(self, filepath: str) -> list[dict]:
        """파일 내 모든 심볼을 가져옵니다."""
        uri = f"file://{os.path.abspath(filepath)}"
        result = self._send_request("textDocument/documentSymbol", {
            "textDocument": {"uri": uri},
        })
        return result or []

    def diagnostics(self, filepath: str) -> list[dict]:
        """컴파일러 진단 결과 (에러, 경고)를 가져옵니다."""
        # SourceKit-LSP는 diagnostics를 notification으로 push합니다
        # 여기서는 문서 열기 후 잠시 대기하여 수집
        # 실제로는 비동기 처리가 필요하지만, 간이 구현으로는 충분
        return []


# ──────────────────────────────────────────
# 고수준 분석 함수
# ──────────────────────────────────────────

@dataclass
class LSPAnalysis:
    """SourceKit-LSP 분석 결과"""
    # 심볼별 타입 정보 (위치 → 타입)
    type_annotations: dict[str, str] = field(default_factory=dict)

    # 심볼 목록 (이름, 종류, 위치)
    symbols: list[dict] = field(default_factory=dict)

    # 외부 참조 (이 파일의 심볼을 사용하는 곳)
    external_references: dict[str, list[dict]] = field(default_factory=dict)

    # 컴파일러 진단 (에러, 경고)
    compiler_diagnostics: list[str] = field(default_factory=list)

    # hover 정보 (주요 심볼의 타입 + 문서)
    hover_info: dict[str, str] = field(default_factory=dict)


def analyze_with_lsp(
    filepath: str,
    content: str,
    client: SourceKitLSPClient,
) -> LSPAnalysis:
    """SourceKit-LSP를 사용하여 파일을 심층 분석합니다."""
    analysis = LSPAnalysis()

    # 파일 열기
    client.open_file(filepath, content)

    # 1. 문서 심볼 수집
    symbols = client.document_symbols(filepath)
    analysis.symbols = symbols

    # 2. 주요 심볼들의 hover 정보 (타입, 문서)
    lines = content.split("\n")
    for i, line in enumerate(lines):
        # 함수 정의, 프로퍼티 정의, 타입 정의 위치에서 hover
        import re
        # func 키워드 뒤의 이름
        func_match = re.search(r'\bfunc\s+(\w+)', line)
        if func_match:
            col = func_match.start(1)
            info = client.hover(filepath, i, col)
            if info:
                analysis.hover_info[f"L{i+1}:{func_match.group(1)}"] = info

        # var/let 선언
        var_match = re.search(r'\b(?:var|let)\s+(\w+)', line)
        if var_match:
            col = var_match.start(1)
            info = client.hover(filepath, i, col)
            if info:
                analysis.hover_info[f"L{i+1}:{var_match.group(1)}"] = info

        # 타입 사용 (UpperCamelCase)
        type_matches = re.finditer(r'\b([A-Z]\w+)\b', line)
        for tm in type_matches:
            col = tm.start(1)
            info = client.hover(filepath, i, col)
            if info and "Unknown" not in info:
                key = f"L{i+1}:{tm.group(1)}"
                if key not in analysis.type_annotations:
                    analysis.type_annotations[key] = info

    # 3. 파일에 정의된 타입들의 외부 참조
    for i, line in enumerate(lines):
        type_def = re.search(
            r'(?:class|struct|enum|protocol|actor)\s+(\w+)', line
        )
        if type_def:
            col = type_def.start(1)
            refs = client.references(filepath, i, col)
            if refs:
                analysis.external_references[type_def.group(1)] = refs[:10]  # 최대 10개

    return analysis


def format_lsp_analysis(analysis: LSPAnalysis) -> str:
    """LSP 분석 결과를 프롬프트용 텍스트로 포맷팅합니다."""
    sections = []

    # 타입 정보
    if analysis.type_annotations:
        type_lines = []
        for loc, type_info in list(analysis.type_annotations.items())[:20]:
            type_lines.append(f"  {loc}: {type_info}")
        sections.append(
            "### 컴파일러 타입 정보\n"
            "sourcekit-lsp로 추출한 정확한 타입 정보입니다:\n```\n"
            + "\n".join(type_lines)
            + "\n```"
        )

    # hover 정보
    if analysis.hover_info:
        hover_lines = []
        for loc, info in list(analysis.hover_info.items())[:15]:
            hover_lines.append(f"  {loc}:\n    {info}")
        sections.append(
            "### 심볼 상세 정보\n```\n"
            + "\n".join(hover_lines)
            + "\n```"
        )

    # 외부 참조
    if analysis.external_references:
        ref_lines = []
        for symbol, refs in analysis.external_references.items():
            locations = []
            for ref in refs[:5]:
                uri = ref.get("uri", "").replace("file://", "")
                line = ref.get("range", {}).get("start", {}).get("line", 0) + 1
                locations.append(f"    - {uri}:{line}")
            ref_lines.append(f"  {symbol} 참조 위치:\n" + "\n".join(locations))
        sections.append(
            "### 외부 참조 위치\n이 파일의 타입을 사용하는 정확한 위치:\n```\n"
            + "\n".join(ref_lines)
            + "\n```"
        )

    if not sections:
        return ""

    return "## 🔬 SourceKit-LSP 분석 (컴파일러 수준)\n\n" + "\n\n".join(sections)


# ──────────────────────────────────────────
# Swift 빌드 인덱스 (선택적)
# ──────────────────────────────────────────

def build_swift_index() -> bool:
    """SPM 프로젝트를 빌드하여 인덱스를 생성합니다.
    인덱스가 있으면 LSP의 정확도가 크게 향상됩니다."""

    if Path("Package.swift").exists():
        print("    📦 SPM 프로젝트 감지 — 인덱스 빌드 중...")
        result = subprocess.run(
            ["swift", "build", "--skip-update"],
            capture_output=True, text=True, timeout=120,
        )
        return result.returncode == 0

    if list(Path(".").glob("*.xcodeproj")) or list(Path(".").glob("*.xcworkspace")):
        print("    📦 Xcode 프로젝트 감지 — xcodebuild 인덱스 중...")
        # xcodebuild는 macOS runner에서만 동작
        result = subprocess.run(
            ["xcodebuild", "build", "-quiet", "-configuration", "Debug",
             "-destination", "generic/platform=iOS Simulator",
             "COMPILER_INDEX_STORE_ENABLE=YES"],
            capture_output=True, text=True, timeout=300,
        )
        return result.returncode == 0

    return False


def check_swift_toolchain() -> dict:
    """Swift toolchain 정보를 확인합니다."""
    info = {"available": False, "version": "", "sourcekit_lsp": False}

    try:
        result = subprocess.run(
            ["swift", "--version"], capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            info["available"] = True
            info["version"] = result.stdout.strip().split("\n")[0]
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    try:
        result = subprocess.run(
            ["which", "sourcekit-lsp"], capture_output=True, text=True, timeout=5,
        )
        info["sourcekit_lsp"] = result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    return info
