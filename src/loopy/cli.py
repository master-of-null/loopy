from __future__ import annotations

from argparse import ArgumentParser
from pathlib import Path
import sys

from loopy.runner import LoopyConfig, run_loopy


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    target = args.target.resolve()
    if not target.exists():
        parser.error(f"target does not exist: {target}")

    original_task = _load_task(args)
    config = LoopyConfig(
        engine=args.engine,
        target=target,
        original_task=original_task,
        runs_dir=args.runs_dir.resolve(),
        implementer_dir=args.implementer_dir.resolve(),
        reviewer_dir=args.reviewer_dir.resolve(),
        max_iters=args.max_iters,
    )

    try:
        result = run_loopy(config)
    except Exception as exc:
        print(f"\nloopy failed: {exc}", file=sys.stderr)
        return 2

    print(f"\nrun directory: {result.run.root}")
    if result.accepted:
        return 0

    print(f"stopped after {result.iterations} iteration(s) without acceptance")
    return 1


def _build_parser() -> ArgumentParser:
    parser = ArgumentParser(description="Run a prompt-driven implement/review loop.")
    parser.add_argument(
        "--engine",
        choices=["codex", "claude"],
        default="codex",
        help="Agent CLI to run.",
    )
    parser.add_argument(
        "--target",
        type=Path,
        default=Path("."),
        help="Project directory the agents should inspect and edit. Defaults to '.'.",
    )
    parser.add_argument(
        "--task",
        help="Task text. Use --task-file for longer instructions.",
    )
    parser.add_argument(
        "--task-file",
        type=Path,
        help="Path to a markdown/text file containing the original task.",
    )
    parser.add_argument(
        "--implementer-dir",
        type=Path,
        default=Path("prompts/implementer"),
        help="Directory of markdown prompts run for implementation.",
    )
    parser.add_argument(
        "--reviewer-dir",
        type=Path,
        default=Path("prompts/reviewer"),
        help="Directory of markdown prompts run for review.",
    )
    parser.add_argument(
        "--runs-dir",
        type=Path,
        default=Path("runs"),
        help="Directory where run artifacts are saved.",
    )
    parser.add_argument(
        "--max-iters",
        type=int,
        default=3,
        help="Maximum implement/review iterations before failing.",
    )
    return parser


def _load_task(args: object) -> str:
    task = getattr(args, "task")
    task_file = getattr(args, "task_file")
    if bool(task) == bool(task_file):
        raise SystemExit("Provide exactly one of --task or --task-file.")

    if task_file:
        return task_file.read_text(encoding="utf-8")
    return task


if __name__ == "__main__":
    raise SystemExit(main())
