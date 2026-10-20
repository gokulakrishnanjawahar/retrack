"""Memory returned by recall, ready to put in an agent's prompt."""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Memory:
    playbooks: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[dict[str, Any]] = field(default_factory=list)
    holdout: bool = False
    recall_id: str | None = None

    @classmethod
    def from_response(cls, data: dict[str, Any]) -> "Memory":
        return cls(
            playbooks=list(data.get("playbooks") or []),
            warnings=list(data.get("warnings") or []),
            holdout=bool(data.get("holdout")),
            recall_id=data.get("recall_id"),
        )

    def __bool__(self) -> bool:
        return bool(self.playbooks or self.warnings)

    def as_prompt(self) -> str:
        """Plain-text memory for the agent's prompt; empty when there is nothing to add."""
        if not self:
            return ""
        lines = ["Relevant experience from previous runs (verify before relying on it):"]
        for playbook in self.playbooks:
            lines.append(f"\nPlaybook: {playbook.get('title', '')}")
            if playbook.get("preconditions"):
                lines.append(f"Preconditions: {playbook['preconditions']}")
            for i, step in enumerate(playbook.get("steps") or [], 1):
                tool = step.get("tool")
                suffix = f" ({tool})" if tool and tool != "none" else ""
                lines.append(f"{i}. {step.get('action', '')}{suffix}")
            if playbook.get("pitfalls"):
                lines.append(f"Pitfalls: {playbook['pitfalls']}")
        if self.warnings:
            lines.append("\nKnown failures:")
            lines.extend(f"- {w.get('message', '')}" for w in self.warnings)
        return "\n".join(lines)
