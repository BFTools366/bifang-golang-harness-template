"""构造 Git 多远端发布的目标摘要与部分结果消息。"""

from __future__ import annotations

from typing import Any, Sequence


def describe_targets(targets: Sequence[dict[str, str]]) -> str:
    """以不含地址或凭据的远端名和分支名描述发布目标。"""
    if not targets:
        return "none"
    return ", ".join(
        f"remote '{target['remote']}' branch '{target['branch']}'" for target in targets
    )


def primary_failure_message(
    remote: str,
    branch: str,
    detail: str,
    outcome: str,
    additional_targets: Sequence[dict[str, str]],
    confirmed_additional: Sequence[dict[str, str]] = (),
) -> str:
    """描述主目标结果以及尚未尝试的全部补充目标。"""
    if confirmed_additional:
        confirmed = describe_targets(confirmed_additional)
        remaining = describe_targets(additional_targets)
        return (
            f"Primary Git remote '{remote}' branch '{branch}' {detail}; current target {outcome}, "
            f"previously confirmed additional targets remain recorded (targets: {confirmed}), "
            f"remaining additional targets were not attempted (targets: {remaining}), and the "
            "same target arguments can be retried."
        )
    targets = describe_targets(additional_targets)
    return (
        f"Primary Git remote '{remote}' branch '{branch}' {detail}; current target {outcome}, "
        f"all additional targets were not attempted (targets: {targets}), and the same target "
        "arguments can be retried."
    )


def additional_failure_message(
    target: dict[str, str],
    detail: str,
    outcome: str,
    published: Sequence[dict[str, str]],
    remaining: Sequence[dict[str, str]],
    confirmed_later: Sequence[dict[str, str]] = (),
) -> str:
    """描述当前补充目标，以及前后已确认或未尝试的精确范围。"""
    earlier = describe_targets(published)
    subsequent = describe_targets(remaining)
    later_confirmed = describe_targets(confirmed_later)
    later_clause = ""
    if confirmed_later:
        later_clause = (
            "later confirmed additional targets remain recorded "
            f"(targets: {later_confirmed}), "
        )
    return (
        f"Additional Git remote '{target['remote']}' branch '{target['branch']}' {detail}; the "
        "primary target and earlier additional targets are confirmed published "
        f"(earlier additional targets: {earlier}), current target {outcome}, {later_clause}subsequent "
        f"additional targets were not attempted (targets: {subsequent}), and the same target arguments can "
        "be retried."
    )


def pending_failure(
    pending: dict[str, Any],
    index: int,
    kind: str,
    detail: str,
    outcome: str,
) -> tuple[str, str]:
    """按冻结目标位置返回稳定错误码与完整部分结果消息。"""
    targets = pending["targets"]
    target = targets[index]
    public = [{"remote": item["remote"], "branch": item["branch"]} for item in targets]
    if len(targets) == 1:
        stable_codes = {
            "push-failed": "push-rejected",
            "verification-failed": "remote-verification-failed",
            "local-state-changed": "local-state-changed",
            "state-write-failed": "state-write-failed",
        }
        stable_messages = {
            "push-failed": "Git default branch push could not be confirmed.",
            "verification-failed": (
                "Git remote default branch could not be confirmed at the frozen published HEAD."
            ),
            "local-state-changed": (
                "Git default branch was confirmed published but local Git state changed."
            ),
            "state-write-failed": (
                "Git default branch was confirmed published but lifecycle state could not be saved."
            ),
        }
        return stable_codes[kind], stable_messages[kind]
    if index == 0:
        confirmed = [
            public[position]
            for position in range(1, len(targets))
            if targets[position]["confirmed"]
        ]
        remaining = [
            public[position]
            for position in range(1, len(targets))
            if not targets[position]["confirmed"]
        ]
        message = primary_failure_message(
            target["remote"],
            target["branch"],
            detail,
            outcome,
            remaining,
            confirmed,
        )
        return f"primary-{kind}", message
    confirmed_later = [
        public[position]
        for position in range(index + 1, len(targets))
        if targets[position]["confirmed"]
    ]
    remaining = [
        public[position]
        for position in range(index + 1, len(targets))
        if not targets[position]["confirmed"]
    ]
    message = additional_failure_message(
        public[index],
        detail,
        outcome,
        public[1:index],
        remaining,
        confirmed_later,
    )
    return f"additional-{kind}", message
