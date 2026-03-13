#!/usr/bin/env python3
"""
iOS Code Review Bot — GitHub Actions
PR 라벨로 감도 변경, 프로젝트 컨텍스트 분석, 근거 링크 포함.
"""

import json
import os
import subprocess
from fnmatch import fnmatch
from pathlib import Path

import yaml
from github import Github

from severity import SEVERITY, SEVERITY_ORDER, severity_meets_threshold
from sensitivity import SENSITIVITY_MODES
from references import build_reference_prompt
from context_collector import collect_context, format_context_for_prompt
from llm_client import create_llm_client, PROVIDERS

# ──────────────────────────────────────────
# 1. 설정 (라벨 오버라이드 포함)
# ──────────────────────────────────────────

DEFAULT_CONFIG = {
    "language": "ko",
    "provider": "gemini",        # gemini(무료), groq(무료), openai, anthropic, openrouter
    "model": "",                 # 비워두면 프로바이더 기본 모델 사용
    "sensitivity": "balanced",
    "max_files": 20,
    "enable_swiftlint": False,
    "enable_lsp": False,
    "review_areas": [
        "memory_management", "concurrency", "swift_conventions",
        "architecture", "performance", "error_handling", "accessibility",
    ],
    "team_rules": [],
    "ignore": ["*.generated.swift", "*/Pods/*", "*/DerivedData/*", "*.pb.swift"],
}

AREA_DESC = {
    "memory_management": "메모리 관리 — retain cycle, [weak self], 강한 참조 순환",
    "concurrency": "동시성 — @MainActor, data race, async/await, Task 관리",
    "swift_conventions": "Swift 컨벤션 — 네이밍, guard let, 옵셔널, API Design Guidelines",
    "architecture": "아키텍처 — MVVM/MVC, 의존성 방향, SRP",
    "performance": "성능 — 메인 스레드 블로킹, 뷰 리렌더링",
    "error_handling": "에러 처리 — do-catch, Result, 에러 전파",
    "accessibility": "접근성 — VoiceOver, Dynamic Type",
}

def load_config() -> dict:
    config = DEFAULT_CONFIG.copy()
    config_path = Path(os.environ.get("INPUT_CONFIG_PATH", ".codereview.yml"))
    if config_path.exists():
        with open(config_path) as f:
            user = yaml.safe_load(f) or {}
        config.update(user)
    for env_key, cfg_key in {
        "INPUT_PROVIDER": "provider", "INPUT_MODEL": "model",
        "INPUT_LANGUAGE": "language", "INPUT_SENSITIVITY": "sensitivity",
        "INPUT_MAX_FILES": "max_files",
    }.items():
        val = os.environ.get(env_key)
        if val:
            config[cfg_key] = int(val) if cfg_key == "max_files" else val
    if os.environ.get("INPUT_ENABLE_LSP", "").lower() == "true":
        config["enable_lsp"] = True
    return config


# ──────────────────────────────────────────
# 2. Git 유틸리티
# ──────────────────────────────────────────

def git(*args): return subprocess.run(["git", *args], capture_output=True, text=True).stdout.strip()
def get_changed_files(b, h): return [f for f in git("diff", "--name-only", f"{b}...{h}").split("\n") if f.strip()]
def get_file_diff(b, h, p): return git("diff", f"{b}...{h}", "--", p)
def get_file_content(h, p): return git("show", f"{h}:{p}")
def should_review(fp, config):
    for pat in config.get("ignore", []):
        if fnmatch(fp, pat): return False
    return Path(fp).suffix == ".swift"


# ──────────────────────────────────────────
# 3. 프롬프트
# ──────────────────────────────────────────

def build_system_prompt(config, sensitivity):
    lang = config.get("language", "ko")
    lang_inst = "한국어로 리뷰해주세요." if lang == "ko" else "Review in English."
    mode = SENSITIVITY_MODES.get(sensitivity, SENSITIVITY_MODES["balanced"])
    min_severity = mode["min_severity"]
    areas = "\n".join(f"- {AREA_DESC.get(a, a)}" for a in config.get("review_areas", []))
    team_rules = config.get("team_rules", [])
    rules_block = ""
    if team_rules:
        rules_block = "\n\n## 팀 규칙\n" + "\n".join(f"- {r}" for r in team_rules)
    severity_guide = "\n".join(f"- **{k}** ({v['icon']}): {v['label']}" for k, v in SEVERITY.items())
    references = build_reference_prompt()

    return f"""당신은 시니어 iOS 개발자이자 코드 리뷰어입니다. {lang_inst}

{mode["prompt_instructions"]}

## 리뷰 영역
{areas}
{rules_block}

## 심각도 (P1~P5)
{severity_guide}

최소 심각도: **{min_severity}**

## 프로젝트 컨텍스트 활용
제공되는 프로젝트 맥락(의존 파일, 프로토콜, 호출부, 테스트)을 적극 활용하여
파일 단위가 아닌 프로젝트 전체 관점에서 리뷰하세요.

## 근거 링크
각 코멘트에 근거 링크 1~2개를 포함하세요.

{references}

## 응답 형식 (JSON만)
{{
  "summary": "요약",
  "overall_severity": "P1~P5",
  "comments": [
    {{
      "line": 42,
      "severity": "P2",
      "message": "메시지",
      "suggestion": "코드 (선택)",
      "references": [{{"title": "제목", "url": "https://..."}}]
    }}
  ],
  "good_points": [],
  "context_insights": []
}}"""


# ──────────────────────────────────────────
# 4. LLM 호출
# ──────────────────────────────────────────

def review_file(client, filepath, diff, full_content, project_context, config, sensitivity):
    mode = SENSITIVITY_MODES.get(sensitivity, SENSITIVITY_MODES["balanced"])
    user_msg = f"""## 리뷰 대상: `{filepath}`

### Diff
```diff
{diff[:8000]}
```

### 전체 파일
```swift
{full_content[:12000]}
```

---

# 프로젝트 컨텍스트
{project_context}

---

JSON만 출력하세요."""

    try:
        system_prompt = build_system_prompt(config, sensitivity)
        text = client.chat(system_prompt, user_msg).strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1].rsplit("```", 1)[0]
        result = json.loads(text)
        min_sev = mode["min_severity"]
        result["comments"] = [
            c for c in result.get("comments", [])
            if severity_meets_threshold(c.get("severity", "P5"), min_sev)
        ]
        return result
    except Exception as e:
        print(f"  ⚠️ {filepath}: {e}")
        return None


# ──────────────────────────────────────────
# 5. PR 코멘트 게시
# ──────────────────────────────────────────

def format_comment_body(comment):
    sev = comment.get("severity", "P5")
    info = SEVERITY.get(sev, SEVERITY["P5"])
    msg = comment.get("message", "")
    suggestion = comment.get("suggestion", "")
    refs = comment.get("references", [])
    body = f"{info['icon']} **{info['label']}**\n\n{msg}"
    if suggestion:
        body += f"\n\n**개선 제안:**\n```swift\n{suggestion}\n```"
    if refs:
        ref_links = " · ".join(f"[{r['title']}]({r['url']})" for r in refs if r.get("url"))
        if ref_links:
            body += f"\n\n📖 **근거:** {ref_links}"
    return body


def post_review(gh, repo_name, pr_number, head_sha, reviews, sensitivity):
    repo = gh.get_repo(repo_name)
    pr = repo.get_pull(pr_number)
    mode = SENSITIVITY_MODES.get(sensitivity, SENSITIVITY_MODES["balanced"])

    parts = [f"## 🤖 iOS Code Review — {mode['name']}\n"]

    severity_counts = {}
    total = 0
    for review in reviews.values():
        if not review: continue
        for c in review.get("comments", []):
            sev = c.get("severity", "P5")
            severity_counts[sev] = severity_counts.get(sev, 0) + 1
            total += 1

    if total > 0:
        badges = " ".join(f"{SEVERITY[s]['icon']} {s}: {cnt}건" for s in SEVERITY_ORDER if severity_counts.get(s, 0) > 0)
        parts.append(f"**{badges}**\n")

    for fp, review in reviews.items():
        if not review: continue
        comments = review.get("comments", [])
        summary = review.get("summary", "")
        overall = review.get("overall_severity", "P5")
        good = review.get("good_points", [])
        insights = review.get("context_insights", [])
        icon = SEVERITY.get(overall, {}).get("icon", "")
        parts.append(f"### {icon} `{fp}` — {len(comments)}개 코멘트\n{summary}\n")
        if good: parts.append("✅ " + " / ".join(good) + "\n")
        if insights: parts.append("💡 " + " / ".join(insights) + "\n")

    if total == 0:
        parts.append("✅ 리뷰할 이슈가 없습니다. 좋은 코드네요!\n")

    parts.append(
        "\n<details><summary>📋 심각도 기준 · 감도 변경</summary>\n\n"
        "| 심각도 | 의미 |\n|---|---|\n"
        "| 🔴 P1 | 꼭 반영 |\n"
        "| 🟠 P2 | 적극 고려 |\n"
        "| 🟡 P3 | 웬만하면 반영 |\n"
        "| 🔵 P4 | 넘어가도 OK |\n"
        "| 💬 P5 | 사소한 의견 |\n\n"
        "감도 변경: 워크플로우의 `sensitivity` 값 또는 `.codereview.yml` 파일에서 설정\n\n"
        "</details>"
    )

    pr.create_issue_comment("\n".join(parts))

    commit = repo.get_commit(head_sha)
    for fp, review in reviews.items():
        if not review: continue
        for comment in review.get("comments", []):
            line = comment.get("line")
            body = format_comment_body(comment)
            try:
                pr.create_review_comment(body=body, commit=commit, path=fp, line=line)
            except Exception as e:
                print(f"  ⚠️ {fp}:{line}: {e}")


# ──────────────────────────────────────────
# 6. 메인
# ──────────────────────────────────────────

def main():
    github_token = os.environ["GITHUB_TOKEN"]
    pr_number = int(os.environ["PR_NUMBER"])
    repo_name = os.environ["REPO_FULL_NAME"]
    base_sha = os.environ["BASE_SHA"]
    head_sha = os.environ["HEAD_SHA"]

    config = load_config()
    gh = Github(github_token)

    # LLM 클라이언트 생성
    provider = config.get("provider", "gemini")
    model = config.get("model") or None
    client = create_llm_client(provider, model)

    # 감도 설정 (워크플로우 input 또는 .codereview.yml)
    sensitivity = config.get("sensitivity", "balanced")
    mode = SENSITIVITY_MODES.get(sensitivity, SENSITIVITY_MODES["balanced"])

    print(f"📋 PR #{pr_number} 리뷰 시작")
    print(f"   프로바이더: {client.provider_name} ({client.model})")
    print(f"   감도: {mode['name']}")

    changed = get_changed_files(base_sha, head_sha)
    targets = [f for f in changed if should_review(f, config)]

    if not targets:
        print("ℹ️  리뷰 대상 Swift 파일 없음")
        return

    max_files = config.get("max_files", 20)
    if len(targets) > max_files:
        targets = targets[:max_files]

    print(f"📂 리뷰 대상: {len(targets)}개 파일\n")

    reviews = {}
    enable_lint = config.get("enable_swiftlint", False)
    enable_lsp = config.get("enable_lsp", False)

    for fp in targets:
        print(f"  🔍 {fp}")
        diff = get_file_diff(base_sha, head_sha, fp)
        content = get_file_content(head_sha, fp)
        if not diff.strip(): continue

        print(f"    📦 컨텍스트 수집 중...")
        ctx = collect_context(fp, diff, content, head_sha, enable_lint, enable_lsp)
        project_context = format_context_for_prompt(ctx)

        print(f"    🤖 리뷰 중...")
        result = review_file(client, fp, diff, content, project_context, config, sensitivity)
        if result:
            reviews[fp] = result
            n = len(result.get("comments", []))
            overall = result.get("overall_severity", "")
            print(f"    ✅ {n}개 코멘트 ({overall})")
        print()

    print("📝 PR 코멘트 게시 중...")
    post_review(gh, repo_name, pr_number, head_sha, reviews, sensitivity)
    print("🎉 리뷰 완료!")


if __name__ == "__main__":
    main()
