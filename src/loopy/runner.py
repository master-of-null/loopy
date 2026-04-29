from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json
import subprocess
from typing import Literal

from pydantic import ValidationError

from loopy.adapters import AgentAdapter, AgentCall
from loopy.contracts import ReviewResult
from loopy.prompts import PromptFile, load_prompt_files, render_agent_input
from loopy.state import RunPaths, create_run


CONTEXT_PROMPT = """You are gathering context for an automated iterate/review coding loop.

Inspect the target project in read-only mode. Return concise markdown that will help later
implementation and review agents work effectively.

Include:
- What the project appears to do
- Tech stack and package/test tools
- Important files and directories
- Commands that are likely useful for validation
- Constraints, conventions, or risks worth preserving

Do not modify files.
"""


REVIEW_CONTRACT_PROMPT = """Return a final response that satisfies this JSON contract:

{
  "acceptable": true,
  "summary": "Short review summary.",
  "findings": [
    {
      "severity": "blocker",
      "summary": "What must be fixed.",
      "details": "Optional details.",
      "files": ["optional/path.py"]
    }
  ],
  "next_instructions": "Optional instructions for the next implementer pass."
}

Use acceptable=false if any blocker remains. Return only the JSON object.
Include every key shown. Use [] when there are no findings, and use null when optional details or
next_instructions do not apply.
"""


EVALUATION_CONTRACT_PROMPT = """Return a final response that satisfies this JSON contract:

{
  "acceptable": true,
  "summary": "Short validation summary, including what you ran or why you did not run it.",
  "findings": [
    {
      "severity": "blocker",
      "summary": "What validation failed or what must be fixed before review.",
      "details": "Optional details, including command output summaries.",
      "files": ["optional/path.py"]
    }
  ],
  "next_instructions": "Optional instructions for the next implementer pass."
}

Use acceptable=false if relevant validation fails, cannot be run, or leaves a real unresolved risk.
Return only the JSON object.
Include every key shown. Use [] when there are no findings, and use null when optional details or
next_instructions do not apply.
"""


@dataclass(frozen=True)
class LoopyConfig:
    engine: str
    target: Path
    original_task: str
    runs_dir: Path
    implementer_dir: Path
    evaluator_dir: Path
    reviewer_dir: Path
    max_iters: int


DiffScope = Literal["unstaged", "staged", "all"]


@dataclass(frozen=True)
class ReviewOnlyConfig:
    engine: str
    target: Path
    original_task: str
    runs_dir: Path
    reviewer_dir: Path
    diff_scope: DiffScope


RunConfig = LoopyConfig | ReviewOnlyConfig


@dataclass(frozen=True)
class LoopyResult:
    accepted: bool
    run: RunPaths
    iterations: int
    last_review: ReviewResult | None


def run_loopy(config: LoopyConfig) -> LoopyResult:
    implementer_prompts = load_prompt_files(config.implementer_dir)
    evaluator_prompts = load_prompt_files(config.evaluator_dir)
    reviewer_prompts = load_prompt_files(config.reviewer_dir)

    run = create_run(config.runs_dir, task_name=_task_name(config.original_task))
    run.task.write_text(config.original_task, encoding="utf-8")

    adapter = AgentAdapter()
    schema_path = _write_review_schema(run)

    print(f"\n== loopy run: {run.root} ==")
    print("\n== context ==")
    project_context = _run_context(config=config, run=run, adapter=adapter)

    previous_review: str | None = None
    last_review: ReviewResult | None = None

    for iteration in range(1, config.max_iters + 1):
        iteration_dir = run.iteration_dir(iteration)
        iteration_dir.mkdir(parents=True, exist_ok=True)
        iteration_goal = _iteration_goal(iteration)
        print(f"\n== iteration {iteration} ==")

        implementation_outputs = _run_prompt_sequence(
            config=config,
            run=run,
            adapter=adapter,
            prompts=implementer_prompts,
            project_context=project_context,
            previous_review=previous_review,
            implementation_reports=None,
            evaluation_reports=None,
            iteration_goal=iteration_goal,
            iteration=iteration,
            role="implementer",
            readonly=False,
        )
        assert implementation_outputs is not None
        implementation_reports = _format_implementation_reports(
            prompts=implementer_prompts,
            outputs=implementation_outputs,
        )
        (iteration_dir / "implementation-reports.md").write_text(
            implementation_reports,
            encoding="utf-8",
        )

        evaluation_results = _run_prompt_sequence(
            config=config,
            run=run,
            adapter=adapter,
            prompts=evaluator_prompts,
            project_context=project_context,
            previous_review=previous_review,
            implementation_reports=implementation_reports,
            evaluation_reports=None,
            iteration_goal=iteration_goal,
            iteration=iteration,
            role="evaluator",
            readonly=True,
            schema_path=schema_path,
            parse_reviews=True,
        )
        assert evaluation_results is not None
        evaluation_review = _merge_review_results(evaluation_results)
        evaluation_report = evaluation_review.model_dump_json(indent=2)
        (iteration_dir / "evaluation.merged.json").write_text(
            evaluation_report,
            encoding="utf-8",
        )

        if not evaluation_review.acceptable:
            print("\n== evaluation failed; skipping reviewer ==")
            last_review = evaluation_review
            _write_json(
                iteration_dir / "review.merged.json",
                last_review.model_dump(mode="json"),
            )
            previous_review = last_review.model_dump_json(indent=2)
            continue

        review_results = _run_prompt_sequence(
            config=config,
            run=run,
            adapter=adapter,
            prompts=reviewer_prompts,
            project_context=project_context,
            previous_review=previous_review,
            implementation_reports=implementation_reports,
            evaluation_reports=evaluation_report,
            iteration_goal=iteration_goal,
            iteration=iteration,
            role="reviewer",
            readonly=True,
            schema_path=schema_path,
            parse_reviews=True,
        )

        assert review_results is not None
        last_review = _merge_review_results(review_results)
        _write_json(
            iteration_dir / "review.merged.json",
            last_review.model_dump(mode="json"),
        )
        previous_review = last_review.model_dump_json(indent=2)

        if last_review.acceptable:
            print("\n== accepted ==")
            print(last_review.summary)
            return LoopyResult(
                accepted=True,
                run=run,
                iterations=iteration,
                last_review=last_review,
            )

        print("\n== review requires another pass ==")
        print(last_review.summary)

    return LoopyResult(
        accepted=False,
        run=run,
        iterations=config.max_iters,
        last_review=last_review,
    )


def run_review_only(config: ReviewOnlyConfig) -> LoopyResult:
    reviewer_prompts = load_prompt_files(config.reviewer_dir)
    review_target = _collect_review_target(config.target, config.diff_scope)

    run = create_run(config.runs_dir, task_name=_task_name(config.original_task))
    run.task.write_text(config.original_task, encoding="utf-8")

    adapter = AgentAdapter()
    schema_path = _write_review_schema(run)
    (run.root / "review-target.patch").write_text(review_target, encoding="utf-8")

    print(f"\n== loopy review-only run: {run.root} ==")
    print("\n== context ==")
    project_context = _run_context(config=config, run=run, adapter=adapter)

    iteration = 1
    iteration_dir = run.iteration_dir(iteration)
    iteration_dir.mkdir(parents=True, exist_ok=True)
    (iteration_dir / "implementation-reports.md").write_text(
        review_target,
        encoding="utf-8",
    )

    print(f"\n== review-only ({config.diff_scope}) ==")
    review_results = _run_prompt_sequence(
        config=config,
        run=run,
        adapter=adapter,
        prompts=reviewer_prompts,
        project_context=project_context,
        previous_review=None,
        implementation_reports=review_target,
        evaluation_reports=None,
        iteration_goal=_review_only_goal(config.diff_scope),
        iteration=iteration,
        role="reviewer",
        readonly=True,
        schema_path=schema_path,
        parse_reviews=True,
    )
    assert review_results is not None
    last_review = _merge_review_results(review_results)
    _write_json(
        iteration_dir / "review.merged.json",
        last_review.model_dump(mode="json"),
    )

    if last_review.acceptable:
        print("\n== accepted ==")
    else:
        print("\n== review found blockers ==")
    print(last_review.summary)

    return LoopyResult(
        accepted=last_review.acceptable,
        run=run,
        iterations=iteration,
        last_review=last_review,
    )


def _run_context(*, config: RunConfig, run: RunPaths, adapter: AgentAdapter) -> str:
    prompt = PromptFile(path=Path("built-in-context.md"), text=CONTEXT_PROMPT)
    iteration_goal = "Gather reusable read-only project context before implementation begins."
    if isinstance(config, ReviewOnlyConfig):
        iteration_goal = "Gather reusable read-only project context before review begins."
    context_input = render_agent_input(
        original_task=config.original_task,
        project_context="No project context has been gathered yet.",
        prompt=prompt,
        previous_review=None,
        iteration_goal=iteration_goal,
        iteration=0,
        role="context",
    )
    (run.root / "context.prompt.xml").write_text(context_input, encoding="utf-8")

    result = adapter.run(
        AgentCall(
            engine=config.engine,
            role="context",
            prompt=context_input,
            target=config.target,
            output_path=run.context,
            stream_log_path=run.root / "context.stream.log",
            metadata_path=run.root / "context.metadata.json",
            readonly=True,
        )
    )
    _raise_on_agent_failure("context", result.returncode)
    return result.output_text


def _run_prompt_sequence(
    *,
    config: RunConfig,
    run: RunPaths,
    adapter: AgentAdapter,
    prompts: list[PromptFile],
    project_context: str,
    previous_review: str | None,
    implementation_reports: str | None,
    evaluation_reports: str | None,
    iteration_goal: str,
    iteration: int,
    role: str,
    readonly: bool,
    schema_path: Path | None = None,
    parse_reviews: bool = False,
) -> list[ReviewResult] | list[str] | None:
    iteration_dir = run.iteration_dir(iteration)
    results: list[ReviewResult] = []
    outputs: list[str] = []

    for index, prompt in enumerate(prompts, start=1):
        call_stem = f"{role}-{index:03d}-{prompt.path.stem}"
        prompt_text = prompt.text
        if role == "reviewer":
            prompt_text = f"{prompt_text.rstrip()}\n\n{REVIEW_CONTRACT_PROMPT}"
        if role == "evaluator":
            prompt_text = f"{prompt_text.rstrip()}\n\n{EVALUATION_CONTRACT_PROMPT}"

        rendered = render_agent_input(
            original_task=config.original_task,
            project_context=project_context,
            prompt=PromptFile(path=prompt.path, text=prompt_text),
            previous_review=previous_review,
            implementation_reports=implementation_reports,
            evaluation_reports=evaluation_reports,
            iteration_goal=iteration_goal,
            iteration=iteration,
            role=role,
        )
        prompt_path = iteration_dir / f"{call_stem}.prompt.xml"
        output_path = iteration_dir / f"{call_stem}.output.md"
        prompt_path.write_text(rendered, encoding="utf-8")

        print(f"\n-- {role} {index}/{len(prompts)}: {prompt.name} --")
        result = adapter.run(
            AgentCall(
                engine=config.engine,
                role=role,
                prompt=rendered,
                target=config.target,
                output_path=output_path,
                stream_log_path=iteration_dir / f"{call_stem}.stream.log",
                metadata_path=iteration_dir / f"{call_stem}.metadata.json",
                readonly=readonly,
                schema_path=schema_path if role in {"evaluator", "reviewer"} else None,
            )
        )
        _raise_on_agent_failure(f"{role} {prompt.name}", result.returncode)

        if parse_reviews:
            review = _parse_review_result(result.output_text)
            _write_json(
                iteration_dir / f"{call_stem}.review.json",
                review.model_dump(mode="json"),
            )
            results.append(review)
        else:
            outputs.append(result.output_text)

    return results if parse_reviews else outputs


def _parse_review_result(text: str) -> ReviewResult:
    try:
        return ReviewResult.model_validate_json(text)
    except ValidationError:
        json_text = _extract_json_object(text)
        return ReviewResult.model_validate_json(json_text)


def _extract_json_object(text: str) -> str:
    decoder = json.JSONDecoder()
    for index, char in enumerate(text):
        if char != "{":
            continue
        try:
            _, end = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        return text[index : index + end]
    raise ValueError("Could not find a JSON object in reviewer output.")


def _merge_review_results(results: list[ReviewResult]) -> ReviewResult:
    if len(results) == 1:
        return results[0]

    findings = [finding for result in results for finding in result.findings]
    acceptable = all(result.acceptable for result in results)
    summary = "\n\n".join(result.summary for result in results)
    next_instructions = "\n\n".join(
        result.next_instructions for result in results if result.next_instructions
    )
    return ReviewResult(
        acceptable=acceptable,
        summary=summary,
        findings=findings,
        next_instructions=next_instructions or None,
    )


def _write_review_schema(run: RunPaths) -> Path:
    schema_path = run.root / "review.schema.json"
    _write_json(schema_path, _strict_json_schema(ReviewResult.model_json_schema()))
    return schema_path


def _strict_json_schema(value: object) -> object:
    if isinstance(value, dict):
        cleaned = {
            key: _strict_json_schema(item)
            for key, item in value.items()
            if key != "default"
        }
        properties = cleaned.get("properties")
        if isinstance(properties, dict):
            cleaned["required"] = list(properties)
        return cleaned

    if isinstance(value, list):
        return [_strict_json_schema(item) for item in value]

    return value


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2), encoding="utf-8")


def _raise_on_agent_failure(name: str, returncode: int) -> None:
    if returncode != 0:
        raise RuntimeError(f"Agent call failed for {name} with exit code {returncode}.")


def _task_name(task: str) -> str:
    first_line = task.strip().splitlines()[0] if task.strip() else "task"
    return first_line


def _iteration_goal(iteration: int) -> str:
    if iteration == 1:
        return (
            "Initial implementation pass. Build the original task as completely as practical, "
            "using the project context to fit the existing codebase."
        )

    return (
        "Follow-up implementation pass. Focus on resolving the previous review's blockers and "
        "next instructions while preserving the original task intent."
    )


def _format_implementation_reports(
    *,
    prompts: list[PromptFile],
    outputs: list[str],
) -> str:
    sections: list[str] = []
    for prompt, output in zip(prompts, outputs, strict=True):
        sections.append(f"## {prompt.name}\n\n{output.strip()}")
    return "\n\n".join(sections)


def _review_only_goal(diff_scope: DiffScope) -> str:
    return (
        "Review-only pass. No implementer or evaluator has run. Review only the "
        f"{diff_scope} changes captured in the implementation report and ignore unrelated "
        "repository state."
    )


def _collect_review_target(target: Path, diff_scope: DiffScope) -> str:
    sections = [
        "# Review-Only Target",
        "",
        "Loopy is running in review-only mode. No implementer has modified files in this run.",
        f"Diff scope: `{diff_scope}`.",
        "",
        "Review only the changes represented below. Treat unrelated repository state as out of scope.",
    ]

    diff_sections: list[str] = []
    if diff_scope == "unstaged":
        diff_sections.append(
            _format_diff_section("Unstaged tracked changes", _git_diff(target))
        )
        diff_sections.append(_format_untracked_section(target))
    elif diff_scope == "staged":
        diff_sections.append(
            _format_diff_section("Staged changes", _git_diff(target, "--cached"))
        )
    elif diff_scope == "all":
        diff_sections.append(
            _format_diff_section(
                "Tracked changes against HEAD",
                _git_diff(target, "HEAD"),
            )
        )
        diff_sections.append(_format_untracked_section(target))
    else:
        raise ValueError(f"Unsupported diff scope: {diff_scope}")

    diff_text = "\n\n".join(section for section in diff_sections if section.strip())
    if not diff_text.strip():
        raise ValueError(f"No {diff_scope} changes found to review.")

    return "\n".join(sections).rstrip() + "\n\n" + diff_text.rstrip() + "\n"


def _format_diff_section(title: str, diff_text: str) -> str:
    if not diff_text.strip():
        return ""
    return f"## {title}\n\n```diff\n{diff_text.rstrip()}\n```"


def _format_untracked_section(target: Path) -> str:
    paths = _git_lines(
        target,
        "ls-files",
        "--others",
        "--exclude-standard",
        "--",
        ".",
    )
    if not paths:
        return ""

    sections = ["## Untracked files"]
    for path in paths:
        diff_text = _git_diff_no_index(target, "/dev/null", path)
        sections.append(f"### {path}\n\n```diff\n{diff_text.rstrip()}\n```")
    return "\n\n".join(sections)


def _git_diff(target: Path, *extra_args: str) -> str:
    return _git(
        target,
        "diff",
        "--no-ext-diff",
        "--no-color",
        "--relative",
        *extra_args,
        "--",
        ".",
    )


def _git_diff_no_index(target: Path, before: str, after: str) -> str:
    return _git(
        target,
        "diff",
        "--no-index",
        "--no-color",
        "--",
        before,
        after,
        allowed_returncodes={0, 1},
    )


def _git_lines(target: Path, *args: str) -> list[str]:
    output = _git(target, *args)
    return [line for line in output.splitlines() if line]


def _git(
    target: Path,
    *args: str,
    allowed_returncodes: set[int] | None = None,
) -> str:
    allowed = allowed_returncodes or {0}
    command = ["git", "-C", str(target), *args]
    result = subprocess.run(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if result.returncode not in allowed:
        detail = result.stderr.strip() or result.stdout.strip()
        command_text = " ".join(command)
        raise RuntimeError(f"`{command_text}` failed: {detail}")
    return result.stdout
