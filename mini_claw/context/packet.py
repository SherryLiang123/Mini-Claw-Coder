from __future__ import annotations

from dataclasses import dataclass, field, replace


@dataclass(frozen=True)
class ContextSection:
    name: str
    content: str
    priority: int = 50
    disclosure: str = "full"

    def render(self) -> str:
        body = self.content.strip() or "(none)"
        return f"## {self.name}\n{body}"


@dataclass(frozen=True)
class ContextBudgetReport:
    max_chars: int
    used_chars: int
    compressed: bool
    truncated_sections: list[str] = field(default_factory=list)
    omitted_sections: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "max_chars": self.max_chars,
            "used_chars": self.used_chars,
            "compressed": self.compressed,
            "truncated_sections": self.truncated_sections,
            "omitted_sections": self.omitted_sections,
        }


@dataclass(frozen=True)
class ContextPacket:
    objective: str
    sections: list[ContextSection]
    budget_report: ContextBudgetReport

    def render(self) -> str:
        body = "\n\n".join(section.render() for section in self.sections)
        budget = self.budget_report
        return "\n\n".join(
            [
                "# Context Packet",
                f"Objective: {self.objective}",
                body,
                "## Context Budget",
                (
                    f"used_chars={budget.used_chars}; max_chars={budget.max_chars}; "
                    f"compressed={budget.compressed}; "
                    f"truncated={budget.truncated_sections}; omitted={budget.omitted_sections}"
                ),
            ]
        )


class ContextCompiler:
    def __init__(self, max_chars: int) -> None:
        self.max_chars = max_chars

    def compile(self, objective: str, sections: list[ContextSection]) -> ContextPacket:
        packet = self._packet(objective, sections, compressed=False)
        if len(packet.render()) <= self.max_chars:
            return self._packet(objective, sections, compressed=False)

        fitted = list(sections)
        truncated: list[str] = []
        omitted: list[str] = []

        for index, section in sorted(enumerate(fitted), key=lambda item: item[1].priority):
            if len(self._packet(objective, fitted, True, truncated, omitted).render()) <= self.max_chars:
                break
            if section.priority >= 90:
                continue
            if len(section.content) > 800:
                fitted[index] = replace(section, content=self._truncate(section.content, 800))
                truncated.append(section.name)

        while len(self._packet(objective, fitted, True, truncated, omitted).render()) > self.max_chars:
            removable = [
                (index, section)
                for index, section in enumerate(fitted)
                if section.priority < 80
            ]
            if not removable:
                break
            index, section = min(removable, key=lambda item: item[1].priority)
            omitted.append(section.name)
            fitted.pop(index)

        return self._packet(objective, fitted, True, truncated, omitted)

    def _packet(
        self,
        objective: str,
        sections: list[ContextSection],
        compressed: bool,
        truncated: list[str] | None = None,
        omitted: list[str] | None = None,
    ) -> ContextPacket:
        report = ContextBudgetReport(
            max_chars=self.max_chars,
            used_chars=0,
            compressed=compressed,
            truncated_sections=truncated or [],
            omitted_sections=omitted or [],
        )
        packet = ContextPacket(objective=objective, sections=sections, budget_report=report)
        used = len(packet.render())
        return ContextPacket(
            objective=objective,
            sections=sections,
            budget_report=replace(report, used_chars=used),
        )

    def _truncate(self, content: str, target_chars: int) -> str:
        if len(content) <= target_chars:
            return content
        half = max(1, target_chars // 2)
        return content[:half] + "\n...[truncated by ContextCompiler]...\n" + content[-half:]
