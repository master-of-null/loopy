# Loopy Agent Map

Loopy is a small prompt-driven development loop for coding agents. Keep the Python harness boring
and put agent behavior in markdown prompt packs.

## Start Here

- `README.md` explains user-facing commands, modes, and artifact layout.
- `docs/ARCHITECTURE.md` maps the loop lifecycle and module boundaries.
- `prompts/` contains the default prompt packs:
  - `implementer/` writes code.
  - `post-hooks/` runs write-capable follow-up hooks after implementation.
  - `evaluator/` performs read-only validation.
  - `reviewer/` performs read-only production review.

## Code Map

- `src/loopy/cli.py` owns argument parsing and command dispatch.
- `src/loopy/runner.py` owns the loop, review-only mode, doc gardening, artifacts, and summaries.
- `src/loopy/adapters.py` shells out to supported agent CLIs.
- `src/loopy/prompts.py` loads markdown prompt files and renders XML payloads.
- `src/loopy/contracts.py` defines structured evaluator/reviewer output.
- `src/loopy/state.py` creates stable run artifact paths.

## Invariants

- Preserve prompt-pack ordering by filename.
- Evaluator and reviewer calls are read-only and must return the structured review contract.
- Implementer and post-hook calls may write, but should stay scoped to the task and loop phase.
- Run artifacts should be explicit and useful to a later agent without relying on CLI session
  memory.
- Add Python only when the harness needs a lifecycle stage, artifact, command, or mechanical
  guarantee. Put role-specific taste and behavior in prompts.
