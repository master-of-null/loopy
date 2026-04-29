from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class PromptFile:
    path: Path
    text: str

    @property
    def name(self) -> str:
        return self.path.name


def load_prompt_files(directory: Path) -> list[PromptFile]:
    if not directory.exists():
        raise FileNotFoundError(f"Prompt directory does not exist: {directory}")
    if not directory.is_dir():
        raise NotADirectoryError(f"Prompt path is not a directory: {directory}")

    paths = sorted(path for path in directory.iterdir() if path.suffix == ".md")
    if not paths:
        raise ValueError(f"No markdown prompt files found in: {directory}")

    return [PromptFile(path=path, text=path.read_text(encoding="utf-8")) for path in paths]


def render_agent_input(
    *,
    original_task: str,
    project_context: str,
    prompt: PromptFile,
    previous_review: str | None,
    iteration_goal: str,
    implementation_reports: str | None = None,
    iteration: int,
    role: str,
) -> str:
    previous_review_text = previous_review or "No previous review feedback."
    implementation_report_text = (
        implementation_reports or "No implementation reports have been produced for this call."
    )

    return f"""<loopy_run>
<role>{role}</role>
<iteration>{iteration}</iteration>

<iteration_goal>
{iteration_goal}
</iteration_goal>

<original_task>
{original_task}
</original_task>

<project_context>
{project_context}
</project_context>

<previous_review>
{previous_review_text}
</previous_review>

<current_iteration_implementation_reports>
{implementation_report_text}
</current_iteration_implementation_reports>

<prompt_file name="{prompt.name}">
{prompt.text}
</prompt_file>
</loopy_run>
"""
