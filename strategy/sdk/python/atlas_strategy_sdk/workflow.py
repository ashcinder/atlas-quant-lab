from enum import StrEnum


class AIRole(StrEnum):
    REGIME_DETECTION = "regime_detection"
    SIGNAL_REVIEW = "signal_review"
    RISK_CONTROL = "risk_control"
    POSITION_MANAGEMENT = "position_management"
    EXECUTION_REVIEW = "execution_review"


class AIAuthority(StrEnum):
    ADVISORY = "advisory"
    VETO = "veto"
    BOUNDED_ADJUSTMENT = "bounded_adjustment"


class FailurePolicy(StrEnum):
    DENY = "deny"
    USE_BASELINE = "use_baseline"
    SKIP = "skip"


ROLE_AUTHORITY = {
    AIRole.REGIME_DETECTION: {AIAuthority.ADVISORY, AIAuthority.VETO},
    AIRole.SIGNAL_REVIEW: set(AIAuthority),
    AIRole.RISK_CONTROL: set(AIAuthority),
    AIRole.POSITION_MANAGEMENT: {AIAuthority.ADVISORY, AIAuthority.BOUNDED_ADJUSTMENT},
    AIRole.EXECUTION_REVIEW: {AIAuthority.ADVISORY, AIAuthority.VETO},
}


def validate_ai_permission(role: AIRole, authority: AIAuthority) -> None:
    if authority not in ROLE_AUTHORITY[role]:
        raise ValueError(f"{role} cannot use {authority}")
