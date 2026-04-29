# Loopy

Loopy is a small prompt-driven iterate/review runner for coding agents.

The intended loop is:

1. Gather one shared project context string.
2. Run every markdown file in `prompts/implementer/`, in filename order.
3. Run every markdown file in `prompts/reviewer/`, in filename order.
4. Validate reviewer output with Pydantic.
5. Stop when every reviewer result is acceptable, or fail after `--max-iters`.

## Usage

Install the local checkout as an editable user tool:

```bash
uv tool install --editable /Users/gabo/Workspace/loopy
```

Then run Loopy from any project directory:

```bash
loopy \
  --engine codex \
  --task-file task.md \
  --max-iters 3
```

By default, `--target` is `.`, so the agents inspect and edit the directory where you run `loopy`.

You can also pass a short task inline:

```bash
loopy --engine codex --task "Add a health check endpoint."
```

## Prompts

Implementation prompts live in:

```text
prompts/implementer/
```

Review prompts live in:

```text
prompts/reviewer/
```

Each markdown file is injected into the agent call with the same high-level payload:

```xml
<iteration_goal>
Initial implementation pass. Build the original task as completely as practical...
</iteration_goal>

<original_task>
...
</original_task>

<project_context>
...
</project_context>

<previous_review>
...
</previous_review>

<current_iteration_implementation_reports>
...
</current_iteration_implementation_reports>

<prompt_file name="001-review.md">
...
</prompt_file>
```

The project context prompt is built into the runner. It is gathered once at the beginning of the run
and reused as an in-memory string for every implementer and reviewer call.

On iteration 1, `<iteration_goal>` tells agents this is the initial implementation pass. On later
iterations, it tells agents to focus on the previous review's blockers and next instructions while
preserving the original task.

Reviewer calls receive the current iteration's implementation reports. These reports are intended as
context about what the implementer claims changed and validated; reviewers should still inspect the
repository state directly before returning the review contract.

## Review Contract

Reviewer calls must return JSON matching this shape:

```json
{
  "acceptable": false,
  "summary": "Short review summary.",
  "findings": [
    {
      "severity": "blocker",
      "summary": "What must be fixed.",
      "details": "Optional details.",
      "files": ["optional/path.py"]
    }
  ],
  "next_instructions": "Optional instructions for the next implementation pass."
}
```

With `--engine codex`, Loopy also passes Codex a generated JSON schema through
`codex exec --output-schema`.

## Run Artifacts

Every run is saved under `runs/`, which is gitignored:

```text
runs/
  20260429-093100-add-health-check-endpoint/
    task.md
    context.md
    context.prompt.xml
    context.stream.log
    review.schema.json
    iter-001/
      implementer-001-implement.prompt.xml
      implementer-001-implement.output.md
      implementer-001-implement.stream.log
      implementation-reports.md
      reviewer-001-review.prompt.xml
      reviewer-001-review.output.md
      reviewer-001-review.review.json
      review.merged.json
```

## Claude

Claude support is intentionally thin until the local CLI shape is confirmed. By default Loopy runs:

```bash
claude -p
```

For read-only calls, including context gathering and reviewers, Loopy runs Claude with plan mode and
edit tools denied:

```bash
claude -p --permission-mode plan --disallowedTools Edit MultiEdit Write NotebookEdit
```

You can override the Claude command with:

```bash
LOOPY_CLAUDE_COMMAND="claude -p" uv run loopy --engine claude ...
```

If your Claude setup needs a specific permission mode for non-interactive edits, include that flag in
`LOOPY_CLAUDE_COMMAND`.

You can override only read-only Claude calls with:

```bash
LOOPY_CLAUDE_READONLY_COMMAND="claude -p --permission-mode plan" loopy --engine claude ...
```
