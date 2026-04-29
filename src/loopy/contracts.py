from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ReviewFinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    severity: Literal["blocker", "non_blocking"] = Field(
        description="Use blocker for findings that should keep the loop running."
    )
    summary: str
    details: str | None = None
    files: list[str] = Field(default_factory=list)


class ReviewResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    acceptable: bool
    summary: str
    findings: list[ReviewFinding] = Field(default_factory=list)
    next_instructions: str | None = Field(
        default=None,
        description="Instructions to feed into the next implementation iteration.",
    )
