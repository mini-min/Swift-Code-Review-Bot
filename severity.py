"""P1~P5 심각도 체계 정의"""

SEVERITY = {
    "P1": {
        "label": "P1: 꼭 반영해주세요",
        "icon": "🔴",
        "action": "REQUEST_CHANGES",
        "description": (
            "서비스에 중대한 오류를 발생시킬 수 있습니다. "
            "반드시 수정하거나, 합리적인 의견으로 리뷰어를 설득해주세요."
        ),
    },
    "P2": {
        "label": "P2: 적극적으로 고려해주세요",
        "icon": "🟠",
        "action": "REQUEST_CHANGES",
        "description": "수용하거나, 수용할 수 없다면 토론할 것을 권장합니다.",
    },
    "P3": {
        "label": "P3: 웬만하면 반영해주세요",
        "icon": "🟡",
        "action": "COMMENT",
        "description": (
            "수용하거나, 반영할 수 없다면 이유를 설명하거나 "
            "JIRA 티켓 등으로 계획을 명시해주세요."
        ),
    },
    "P4": {
        "label": "P4: 반영해도 좋고 넘어가도 좋습니다",
        "icon": "🔵",
        "action": "APPROVE",
        "description": "무시 가능. 고민해보는 정도면 충분합니다.",
    },
    "P5": {
        "label": "P5: 사소한 의견입니다",
        "icon": "💬",
        "action": "APPROVE",
        "description": "무시해도 괜찮습니다.",
    },
}

SEVERITY_ORDER = ["P1", "P2", "P3", "P4", "P5"]


def get_highest_severity(severities: list[str]) -> str:
    for level in SEVERITY_ORDER:
        if level in severities:
            return level
    return "P5"


def severity_meets_threshold(severity: str, threshold: str) -> bool:
    try:
        return SEVERITY_ORDER.index(severity) <= SEVERITY_ORDER.index(threshold)
    except ValueError:
        return True
