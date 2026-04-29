from __future__ import annotations

import difflib
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SkillPatchProposal:
    target_skill: str
    skill_path: str
    contract_patch: list[str]
    instruction_patch: list[str]
    metadata: dict[str, str]


@dataclass(frozen=True)
class SkillPatchPreview:
    target_skill: str
    skill_path: str
    diff: str
    proposed_content: str


def parse_skill_patch_candidate_content(content: str) -> SkillPatchProposal:
    metadata: dict[str, str] = {}
    contract_patch: list[str] = []
    instruction_patch: list[str] = []
    section = "metadata"
    for raw_line in content.splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped:
            continue
        if stripped == "### Suggested Contract Patch":
            section = "contract"
            continue
        if stripped == "### Suggested Instruction Patch":
            section = "instruction"
            continue
        if section == "metadata" and stripped.startswith("- ") and ": " in stripped:
            key, value = stripped[2:].split(": ", 1)
            metadata[key.strip()] = value.strip()
            continue
        if section == "contract":
            contract_patch.append(stripped)
            continue
        if section == "instruction":
            instruction_patch.append(stripped)

    return SkillPatchProposal(
        target_skill=metadata.get("target_skill", "(unknown)"),
        skill_path=metadata.get("skill_path", "(unknown)"),
        contract_patch=contract_patch,
        instruction_patch=instruction_patch,
        metadata=metadata,
    )


def render_skill_patch_artifact(
    *,
    artifact_id: str,
    candidate: dict[str, object],
    promote_reason: str,
    created_at: str,
    artifact_path: Path,
) -> str:
    proposal = parse_skill_patch_candidate_content(str(candidate.get("content", "")))
    lines = [
        "# Skill Patch Artifact",
        f"- artifact_id: {artifact_id}",
        f"- candidate_id: {candidate.get('candidate_id', '')}",
        f"- target_skill: {proposal.target_skill}",
        f"- skill_path: {proposal.skill_path}",
        f"- created_at: {created_at}",
        f"- promote_reason: {promote_reason}",
        f"- confidence: {candidate.get('confidence', '')}",
        f"- source: {candidate.get('source', '')}",
        f"- artifact_path: {artifact_path}",
        "",
        "## Proposed Contract Patch",
        *(proposal.contract_patch or ["(none)"]),
        "",
        "## Proposed Instruction Patch",
        *(proposal.instruction_patch or ["(none)"]),
        "",
        "## Review Checklist",
        "1. Confirm the target skill still matches current repository behavior.",
        "2. Check whether the suggested triggers and verification lines overlap with existing skill content.",
        "3. Run `python -m mini_claw memory skill-patch-verify <artifact>` with a focused verification command.",
        "4. Apply the patch manually only after the eval gate result is acceptable.",
        "",
        "## Original Candidate",
        str(candidate.get("content", "")).strip() or "(none)",
    ]
    return "\n".join(lines) + "\n"


def build_skill_patch_apply_preview(
    *,
    current_content: str,
    artifact: dict[str, object],
) -> SkillPatchPreview:
    artifact_content = str(artifact.get("content", ""))
    target_skill = str(artifact.get("target_skill") or _metadata_value(artifact_content, "target_skill") or "(unknown)")
    skill_path = str(artifact.get("skill_path") or _metadata_value(artifact_content, "skill_path") or "(unknown)")
    contract_patch = _extract_markdown_section(artifact_content, "## Proposed Contract Patch")
    instruction_patch = _extract_markdown_section(artifact_content, "## Proposed Instruction Patch")
    contract_patch = [line for line in contract_patch if line.strip() and line.strip() != "(none)"]
    instruction_patch = [
        line for line in instruction_patch if line.strip() and line.strip() != "(none)"
    ]

    proposal_lines = [
        "",
        "## Runtime Learning Proposal",
        f"- source_artifact: {artifact.get('artifact_id', '')}",
        f"- source_candidate: {artifact.get('candidate_id', '')}",
        f"- target_skill: {target_skill}",
        "",
        "### Proposed Contract Changes",
        *(contract_patch or ["(none)"]),
        "",
        "### Proposed Instruction Changes",
        *(instruction_patch or ["(none)"]),
        "",
    ]
    base = current_content.rstrip()
    proposed_content = base + "\n" + "\n".join(proposal_lines)
    diff_lines = difflib.unified_diff(
        current_content.splitlines(),
        proposed_content.splitlines(),
        fromfile=skill_path,
        tofile=f"{skill_path} (skill patch preview)",
        lineterm="",
    )
    return SkillPatchPreview(
        target_skill=target_skill,
        skill_path=skill_path,
        diff="\n".join(diff_lines) + "\n",
        proposed_content=proposed_content + "\n",
    )


def _metadata_value(content: str, key: str) -> str:
    prefix = f"- {key}: "
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith(prefix):
            return stripped[len(prefix) :].strip()
    return ""


def _extract_markdown_section(content: str, heading: str) -> list[str]:
    lines: list[str] = []
    in_section = False
    for raw_line in content.splitlines():
        stripped = raw_line.strip()
        if stripped == heading:
            in_section = True
            continue
        if in_section and stripped.startswith("## "):
            break
        if in_section:
            lines.append(stripped)
    return lines
