# Loopy Architecture

Loopy splits responsibility between a small Python harness and markdown prompt packs that are easy
to inspect, replace, and version.

## Lifecycle

Normal runs follow this sequence:

1. A read-only context call inspects the target project and writes `context.md`.
2. Implementer prompts run in filename order and may edit the target project.
3. Post-hook prompts run in filename order and may make follow-up edits such as keeping target
   project documentation current.
4. Evaluator prompts run read-only validation and return structured JSON.
5. Reviewer prompts run read-only production review and return structured JSON.
6. If evaluation or review reports blockers, merged feedback becomes the next iteration's
   `previous_review`.
7. The loop stops when review accepts the work or `--max-iters` is reached.

Review-only runs skip implementation, post-hooks, and evaluation. They capture the requested git
diff, feed that scoped change to the reviewer, and save the normal review artifacts.

Standalone doc-gardening runs gather target project context and run the post-hook prompt pack
against the target repo without an implementation pass.

## Modules

- `cli.py` builds the command-line interface, loads task text, resolves prompt directories, and
  dispatches to the runner.
- `runner.py` coordinates agent calls, merges evaluator/reviewer results, captures git diffs for
  review-only mode, writes run summaries, and owns artifact layout decisions.
- `adapters.py` translates Loopy calls into external agent CLI commands.
- `prompts.py` loads markdown prompt files and renders each call as a stateless XML payload.
- `contracts.py` defines the Pydantic models used to validate evaluator and reviewer JSON.
- `state.py` creates run directories and common artifact paths.

## Prompt Packs

Each markdown file in a prompt directory becomes one agent call, sorted by filename.

- `prompts/implementer/` is write-capable and owns task implementation.
- `prompts/post-hooks/` is write-capable and owns follow-up work after implementation.
- `prompts/evaluator/` is read-only and owns focused validation.
- `prompts/reviewer/` is read-only and owns production-readiness review.

Keep role-specific policy in the prompt pack when possible. Keep the harness focused on lifecycle,
artifacts, and enforcement.

## Artifacts

Every run is saved under `runs/` by default.

- `task.md` stores the original task.
- `context.md` stores reusable target project context.
- `iter-*/implementation-reports.md` stores the implementer and post-hook reports fed to later
  phases.
- `iter-*/evaluation.merged.json` stores merged evaluator output when evaluation runs.
- `iter-*/review.merged.json` stores merged reviewer output when review runs.
- `run.summary.json` and `run.summary.md` provide compact run overviews.

Debug and full artifact modes additionally preserve exact prompt payloads, raw outputs, stream logs,
metadata, schema files, and parsed per-prompt review JSON.
