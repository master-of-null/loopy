from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import re


@dataclass(frozen=True)
class RunPaths:
    root: Path

    @property
    def context(self) -> Path:
        return self.root / "context.md"

    @property
    def task(self) -> Path:
        return self.root / "task.md"

    def iteration_dir(self, iteration: int) -> Path:
        return self.root / f"iter-{iteration:03d}"


def create_run(runs_dir: Path, task_name: str | None = None) -> RunPaths:
    runs_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    suffix = f"-{_slugify(task_name)}" if task_name else ""
    root = runs_dir / f"{timestamp}{suffix}"
    counter = 1
    while root.exists():
        counter += 1
        root = runs_dir / f"{timestamp}{suffix}-{counter}"

    root.mkdir(parents=True)
    return RunPaths(root=root)


def _slugify(value: str | None) -> str:
    if not value:
        return ""
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", value).strip("-").lower()
    return slug[:48]
