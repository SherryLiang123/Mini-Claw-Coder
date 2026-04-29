from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class SkillContract:
    name: str
    description: str = ""
    triggers: list[str] = field(default_factory=list)
    inputs: list[str] = field(default_factory=list)
    outputs: list[str] = field(default_factory=list)
    allowed_tools: list[str] = field(default_factory=list)
    forbidden_paths: list[str] = field(default_factory=list)
    verification: list[str] = field(default_factory=list)

    def to_prompt(self) -> str:
        rows = [
            f"name: {self.name}",
            f"description: {self.description or '(none)'}",
            f"triggers: {', '.join(self.triggers) or '(none)'}",
            f"inputs: {', '.join(self.inputs) or '(none)'}",
            f"outputs: {', '.join(self.outputs) or '(none)'}",
            f"allowed_tools: {', '.join(self.allowed_tools) or '(not specified)'}",
            f"forbidden_paths: {', '.join(self.forbidden_paths) or '(none)'}",
            f"verification: {', '.join(self.verification) or '(none)'}",
        ]
        return "\n".join(rows)


@dataclass(frozen=True)
class Skill:
    name: str
    body: str
    path: Path
    contract: SkillContract

    def to_prompt(self) -> str:
        return "\n".join(
            [
                f"### {self.name}",
                "Contract:",
                self.contract.to_prompt(),
                "",
                "Instructions:",
                self.body.strip(),
            ]
        )

    def relevance_score(self, query: str) -> int:
        terms = {
            token.lower()
            for token in re.split(r"[^A-Za-z0-9_]+", query)
            if len(token) >= 3
        }
        if not terms:
            return 0
        haystack = " ".join(
            [
                self.name,
                self.contract.description,
                " ".join(self.contract.triggers),
                self.body[:1_000],
            ]
        ).lower()
        return sum(3 if term in " ".join(self.contract.triggers).lower() else 1 for term in terms if term in haystack)


class SkillLoader:
    def __init__(self, roots: list[Path]) -> None:
        self.roots = roots

    def load(self) -> list[Skill]:
        skills: list[Skill] = []
        for root in self.roots:
            if not root.exists():
                continue
            for skill_file in sorted(root.glob("*/SKILL.md")):
                skills.append(
                    load_skill(skill_file)
                )
        return skills


def load_skill(path: Path) -> Skill:
    raw = path.read_text(encoding="utf-8")
    metadata, body = _split_front_matter(raw)
    fallback_name = path.parent.name
    contract = SkillContract(
        name=str(metadata.get("name", fallback_name)),
        description=str(metadata.get("description", "")),
        triggers=_as_list(metadata.get("triggers", [])),
        inputs=_as_list(metadata.get("inputs", [])),
        outputs=_as_list(metadata.get("outputs", [])),
        allowed_tools=_as_list(metadata.get("allowed_tools", [])),
        forbidden_paths=_as_list(metadata.get("forbidden_paths", [])),
        verification=_as_list(metadata.get("verification", [])),
    )
    return Skill(name=contract.name, body=body.strip(), path=path, contract=contract)


def select_relevant_skills(skills: list[Skill], query: str, limit: int = 3) -> list[Skill]:
    scored = [(skill.relevance_score(query), skill) for skill in skills]
    relevant = [(score, skill) for score, skill in scored if score > 0]
    if not relevant:
        return skills[:limit]
    return [skill for _, skill in sorted(relevant, key=lambda item: (-item[0], item[1].name))[:limit]]


def _split_front_matter(raw: str) -> tuple[dict[str, object], str]:
    lines = raw.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, raw

    end = None
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            end = index
            break
    if end is None:
        return {}, raw

    metadata = _parse_metadata(lines[1:end])
    body = "\n".join(lines[end + 1 :])
    return metadata, body


def _parse_metadata(lines: list[str]) -> dict[str, object]:
    data: dict[str, object] = {}
    current_key = ""
    for raw_line in lines:
        line = raw_line.rstrip()
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if line.startswith("  - ") and current_key:
            items = data.setdefault(current_key, [])
            if isinstance(items, list):
                items.append(line[4:].strip())
            continue
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        current_key = key.strip()
        parsed = _parse_value(value.strip())
        data[current_key] = parsed
    return data


def _parse_value(value: str) -> object:
    if not value:
        return []
    if value.startswith("[") and value.endswith("]"):
        inner = value[1:-1].strip()
        if not inner:
            return []
        return [item.strip().strip("\"'") for item in inner.split(",")]
    return value.strip("\"'")


def _as_list(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    if isinstance(value, str) and value:
        return [value]
    return []
