from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import json
import os
import shlex
import subprocess
import sys


@dataclass(frozen=True)
class AgentCall:
    engine: str
    role: str
    prompt: str
    target: Path
    output_path: Path
    stream_log_path: Path
    metadata_path: Path
    readonly: bool
    schema_path: Path | None = None


@dataclass(frozen=True)
class AgentCallResult:
    returncode: int
    output_text: str
    stream_text: str


class AgentAdapter:
    def run(self, call: AgentCall) -> AgentCallResult:
        command = self._build_command(call)
        call.output_path.parent.mkdir(parents=True, exist_ok=True)
        call.stream_log_path.parent.mkdir(parents=True, exist_ok=True)

        started_at = datetime.now().isoformat(timespec="seconds")
        returncode, stream_text = _run_streaming(
            command=command,
            prompt=call.prompt,
            cwd=call.target if call.engine == "claude" else None,
            stream_log_path=call.stream_log_path,
        )
        finished_at = datetime.now().isoformat(timespec="seconds")

        output_text = _read_output(call.output_path, fallback=stream_text)
        if not call.output_path.exists():
            call.output_path.write_text(output_text, encoding="utf-8")

        metadata = {
            "engine": call.engine,
            "role": call.role,
            "command": command,
            "target": str(call.target),
            "readonly": call.readonly,
            "schema_path": str(call.schema_path) if call.schema_path else None,
            "output_path": str(call.output_path),
            "stream_log_path": str(call.stream_log_path),
            "started_at": started_at,
            "finished_at": finished_at,
            "returncode": returncode,
        }
        call.metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")

        return AgentCallResult(
            returncode=returncode,
            output_text=output_text,
            stream_text=stream_text,
        )

    def _build_command(self, call: AgentCall) -> list[str]:
        if call.engine == "codex":
            return _codex_command(call)
        if call.engine == "claude":
            return _claude_command(call)
        raise ValueError(f"Unsupported engine: {call.engine}")


def _run_streaming(
    *,
    command: list[str],
    prompt: str,
    cwd: Path | None,
    stream_log_path: Path,
) -> tuple[int, str]:
    process = subprocess.Popen(
        command,
        cwd=str(cwd) if cwd else None,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )

    assert process.stdin is not None
    process.stdin.write(prompt)
    process.stdin.close()

    chunks: list[str] = []
    assert process.stdout is not None
    with stream_log_path.open("w", encoding="utf-8") as log_file:
        for line in process.stdout:
            sys.stdout.write(line)
            sys.stdout.flush()
            log_file.write(line)
            chunks.append(line)

    returncode = process.wait()
    return returncode, "".join(chunks)


def _read_output(path: Path, *, fallback: str) -> str:
    if path.exists():
        return path.read_text(encoding="utf-8")
    return fallback


def _codex_command(call: AgentCall) -> list[str]:
    command = [
        "codex",
        "exec",
        "--cd",
        str(call.target),
        "--skip-git-repo-check",
        "--color",
        "always",
        "--output-last-message",
        str(call.output_path),
    ]
    if call.readonly:
        command.extend(["--sandbox", "read-only"])
    else:
        command.append("--full-auto")
    if call.schema_path:
        command.extend(["--output-schema", str(call.schema_path)])
    command.append("-")
    return command


def _claude_command(call: AgentCall) -> list[str]:
    readonly_configured = os.environ.get("LOOPY_CLAUDE_READONLY_COMMAND")
    if call.readonly and readonly_configured:
        return _append_claude_schema(shlex.split(readonly_configured), call)

    configured = os.environ.get("LOOPY_CLAUDE_COMMAND")
    if configured:
        return _append_claude_schema(shlex.split(configured), call)

    command = ["claude", "-p"]
    if call.readonly:
        command.extend(
            [
                "--permission-mode",
                "plan",
                "--disallowedTools",
                "Edit",
                "MultiEdit",
                "Write",
                "NotebookEdit",
            ]
        )
    return _append_claude_schema(command, call)


def _append_claude_schema(command: list[str], call: AgentCall) -> list[str]:
    if not call.schema_path:
        return command

    schema = json.dumps(json.loads(call.schema_path.read_text(encoding="utf-8")))
    return [*command, "--json-schema", schema]
