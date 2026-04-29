from __future__ import annotations

from argparse import ArgumentParser, SUPPRESS
from pathlib import Path
import sys

from loopy.runner import LoopyConfig, ReviewOnlyConfig, run_loopy, run_review_only


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    target = args.target.resolve()
    if not target.exists():
        parser.error(f"target does not exist: {target}")

    try:
        if args.command == "review":
            original_task = _load_task(args, required=False) or _default_review_task(
                args.diff_scope
            )
            config = ReviewOnlyConfig(
                engine=args.engine,
                target=target,
                original_task=original_task,
                runs_dir=args.runs_dir.resolve(),
                reviewer_dir=_resolve_prompt_dir(args.reviewer_dir, "reviewer"),
                diff_scope=args.diff_scope,
            )
            result = run_review_only(config)
        else:
            original_task = _load_task(args, required=True)
            config = LoopyConfig(
                engine=args.engine,
                target=target,
                original_task=original_task,
                runs_dir=args.runs_dir.resolve(),
                implementer_dir=_resolve_prompt_dir(args.implementer_dir, "implementer"),
                evaluator_dir=_resolve_prompt_dir(args.evaluator_dir, "evaluator"),
                reviewer_dir=_resolve_prompt_dir(args.reviewer_dir, "reviewer"),
                max_iters=args.max_iters,
            )
            result = run_loopy(config)
    except Exception as exc:
        print(f"\nloopy failed: {exc}", file=sys.stderr)
        return 2

    print(f"\nrun directory: {result.run.root}")
    if result.accepted:
        return 0

    if args.command == "review":
        print("review reported blockers")
        return 1

    print(f"stopped after {result.iterations} iteration(s) without acceptance")
    return 1


def _build_parser() -> ArgumentParser:
    parser = ArgumentParser(description="Run a prompt-driven implement/review loop.")
    _add_shared_arguments(parser)
    parser.add_argument(
        "--implementer-dir",
        type=Path,
        help="Directory of markdown prompts run for implementation.",
    )
    parser.add_argument(
        "--evaluator-dir",
        type=Path,
        help="Directory of markdown prompts run for agentic validation.",
    )
    parser.add_argument(
        "--max-iters",
        type=int,
        default=3,
        help="Maximum implement/review iterations before failing.",
    )
    subparsers = parser.add_subparsers(dest="command", metavar="command")
    review_parser = subparsers.add_parser(
        "review",
        help="Run only the read-only reviewer against a git diff.",
        description="Run a read-only Loopy review against a git diff.",
    )
    _add_shared_arguments(review_parser, suppress_defaults=True)
    review_parser.add_argument(
        "--diff-scope",
        choices=["unstaged", "staged", "all"],
        default="unstaged",
        help="Git diff scope to review. Defaults to unstaged changes.",
    )
    return parser


def _add_shared_arguments(parser: ArgumentParser, *, suppress_defaults: bool = False) -> None:
    parser.add_argument(
        "--engine",
        choices=["codex", "claude"],
        default=_default("codex", suppress=suppress_defaults),
        help="Agent CLI to run.",
    )
    parser.add_argument(
        "--target",
        type=Path,
        default=_default(Path("."), suppress=suppress_defaults),
        help="Project directory the agents should inspect and edit. Defaults to '.'.",
    )
    parser.add_argument(
        "--task",
        default=_default(None, suppress=suppress_defaults),
        help="Task text. Use --task-file for longer instructions.",
    )
    parser.add_argument(
        "--task-file",
        type=Path,
        default=_default(None, suppress=suppress_defaults),
        help="Path to a markdown/text file containing the original task.",
    )
    parser.add_argument(
        "--reviewer-dir",
        type=Path,
        default=_default(None, suppress=suppress_defaults),
        help="Directory of markdown prompts run for review.",
    )
    parser.add_argument(
        "--runs-dir",
        type=Path,
        default=_default(Path("runs"), suppress=suppress_defaults),
        help="Directory where run artifacts are saved.",
    )


def _default(value: object, *, suppress: bool) -> object:
    if suppress:
        return SUPPRESS
    return value


def _load_task(args: object, *, required: bool) -> str | None:
    task = getattr(args, "task")
    task_file = getattr(args, "task_file")
    if task and task_file:
        raise SystemExit("Provide at most one of --task or --task-file.")
    if not task and not task_file:
        if required:
            raise SystemExit("Provide exactly one of --task or --task-file.")
        return None

    if task_file:
        return task_file.read_text(encoding="utf-8")
    return task


def _default_review_task(diff_scope: str) -> str:
    return (
        f"Review the current {diff_scope} code changes for correctness, regressions, "
        "missing validation, and production-readiness issues."
    )


def _resolve_prompt_dir(value: Path | None, role: str) -> Path:
    if value:
        return value.resolve()
    return Path(__file__).resolve().parents[2] / "prompts" / role


if __name__ == "__main__":
    raise SystemExit(main())
