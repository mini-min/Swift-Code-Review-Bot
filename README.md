# 🍎 Swift Code Review Bot

AI가 시니어 iOS 개발자처럼 PR을 리뷰해주는 봇입니다.
프로젝트 전체 맥락을 이해하고, Apple 공식 문서 근거와 함께 P1~P5 코멘트 (뱅크샐러드 코드 리뷰 스타일)를 남깁니다.

**Gemini를 사용하면 완전 무료**입니다. GPT, Claude도 선택할 수 있습니다.

---

## 설치

### 1. API 키 발급

사용할 AI의 키를 발급받으세요. 여러 개를 등록해두고 `provider`만 바꿔가며 쓸 수도 있습니다.

| AI | 비용 | 키 발급 | Secret 이름 |
|----|------|---------|-------------|
| **Google Gemini** | **무료** | [aistudio.google.com/apikey](https://aistudio.google.com/apikey) | `GEMINI_API_KEY` |
| OpenAI GPT | 유료 | [platform.openai.com/api-keys](https://platform.openai.com/api-keys) | `OPENAI_API_KEY` |
| Anthropic Claude | 유료 | [console.anthropic.com](https://console.anthropic.com) | `ANTHROPIC_API_KEY` |

### 2. GitHub Secret 등록

내 repo → **Settings** → **Secrets and variables** → **Actions** → **New repository secret**

사용할 AI에 맞는 Secret을 등록하세요:

| 사용할 AI | Secret Name | Secret Value |
|-----------|-------------|-------------|
| Gemini | `GEMINI_API_KEY` | Gemini 키 |
| GPT | `OPENAI_API_KEY` | OpenAI 키 |
| Claude | `ANTHROPIC_API_KEY` | Anthropic 키 |

여러 개를 등록해도 됩니다. `provider`에 지정한 AI의 키만 사용됩니다.

### 3. 워크플로우 추가

내 repo → **Actions** 탭 → **"set up a workflow yourself"** → 아래 복붙 → **Commit**

**Gemini (무료):**
```yaml
name: iOS Code Review
on:
  pull_request:
    paths: ['**/*.swift']
permissions:
  contents: read
  pull-requests: write
jobs:
  review:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with: { fetch-depth: 0 }
      - uses: your-org/ios-code-review@v1
        with:
          gemini_api_key: ${{ secrets.GEMINI_API_KEY }}
          provider: gemini
```

**GPT:**
```yaml
      - uses: your-org/ios-code-review@v1
        with:
          openai_api_key: ${{ secrets.OPENAI_API_KEY }}
          provider: openai
```

**Claude:**
```yaml
      - uses: your-org/ios-code-review@v1
        with:
          anthropic_api_key: ${{ secrets.ANTHROPIC_API_KEY }}
          provider: anthropic
```

**끝.** `.swift` 파일이 포함된 PR을 올려보세요.

---

## 설정

### 워크플로우에서 설정

```yaml
- uses: your-org/ios-code-review@v1
  with:
    gemini_api_key: ${{ secrets.GEMINI_API_KEY }}
    provider: gemini
    sensitivity: balanced      # 감도 모드 (아래 표 참고)
    language: ko               # ko / en
    max_files: 20
```

### .codereview.yml (선택)

프로젝트 루트에 이 파일을 만들면 팀 규칙 등을 세밀하게 설정할 수 있습니다.
없어도 기본값으로 동작합니다.

```yaml
sensitivity: balanced

team_rules:
  - "ViewModel은 @MainActor로 선언"
  - "Force unwrap(!) 금지"
  - "네트워크 호출은 NetworkService를 통해서만"

ignore:
  - "*.generated.swift"
  - "*/Pods/*"
```

---

## 감도 모드

| 값 | 모드 | 설명 |
|----|------|------|
| `strict` | 🔬 깐깐 | 모든 이슈 꼼꼼히 |
| `balanced` | ⚖️ 균형 **(기본)** | 중요 이슈 중심 |
| `critical_only` | 🚨 심각만 | 크래시/보안만 |
| `learning` | 📚 학습 | 자세한 설명 + 근거 |
| `performance` | 🚀 성능 | 성능 이슈 집중 |
| `security` | 🛡️ 보안 | 보안 취약점 집중 |

---

## 심각도 (P1~P5)

| 등급 | 의미 | 작성자 대응 |
|------|------|-------------|
| 🔴 P1 | 꼭 반영해주세요 | 반드시 수정 |
| 🟠 P2 | 적극적으로 고려해주세요 | 수용 또는 토론 |
| 🟡 P3 | 웬만하면 반영해주세요 | 수용 또는 사유 설명 |
| 🔵 P4 | 넘어가도 좋습니다 | 무시 가능 |
| 💬 P5 | 사소한 의견 | 무시 가능 |

모든 코멘트에 Apple 공식 문서, WWDC 세션 등 근거 링크가 포함됩니다.

---

## License

MIT
