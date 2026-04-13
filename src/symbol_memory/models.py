"""Pydantic models used by symbol_memory."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

SymbolType = Literal["function", "method", "class"]
ValidationSeverity = Literal["error", "warning"]
ValidationStatus = Literal["ok", "warning", "error"]
ValidationStage = Literal["scan", "parse", "resolve", "artifact", "query"]


class SymbolDecoratorMetadata(BaseModel):
    """Manual metadata declared in the `@symbol(...)` decorator."""

    model_config = ConfigDict(extra="forbid", strict=True)

    id: int
    r: list[int]
    role: str
    summary: str
    notes: str | None = None
    tags: list[str] = Field(default_factory=list)
    expose: bool = True
    entrypoint: bool = False

    @field_validator("r")
    @classmethod
    def _validate_relation_ids(cls, value: list[int]) -> list[int]:
        if any(isinstance(item, bool) or not isinstance(item, int) for item in value):
            raise ValueError("Symbol relations must be a list of integer literals")
        return value

    @field_validator("role", "summary")
    @classmethod
    def _validate_required_strings(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Symbol string fields must be non-empty string literals")
        return value

    @field_validator("notes")
    @classmethod
    def _validate_optional_notes(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("Optional symbol string fields must be string literals or None")
        return value

    @field_validator("tags", mode="before")
    @classmethod
    def _normalize_tags(cls, value: list[str] | None) -> list[str]:
        return [] if value is None else value

    @field_validator("tags")
    @classmethod
    def _validate_tags(cls, value: list[str]) -> list[str]:
        if any(not isinstance(item, str) or not item.strip() for item in value):
            raise ValueError("Symbol tags must be a list of non-empty string literals")
        return value


class SymbolRecord(BaseModel):
    """Fully resolved symbol record stored in the index."""

    model_config = ConfigDict(extra="forbid")

    id: int
    name: str
    qualified_name: str
    symbol_type: SymbolType
    role: str
    summary: str
    relation_ids: list[int]
    notes: str | None = None
    tags: list[str] = Field(default_factory=list)
    expose: bool = True
    entrypoint: bool = False
    file_path: str
    start_line: int
    end_line: int
    module_path: str
    parent_class_name: str | None = None
    child_method_ids: list[int] = Field(default_factory=list)


class RelationPreview(BaseModel):
    """Resolved relation preview used in cards and relation tools."""

    model_config = ConfigDict(extra="forbid")

    id: int
    resolved: bool
    name: str | None = None
    role: str | None = None
    summary: str | None = None
    file_path: str | None = None
    start_line: int | None = None
    end_line: int | None = None
    message: str | None = None


class ProjectCounts(BaseModel):
    """High-level index counts."""

    model_config = ConfigDict(extra="forbid")

    total_indexed_symbols: int = 0
    total_functions: int = 0
    total_methods: int = 0
    total_classes: int = 0


class ProjectIndex(BaseModel):
    """Primary machine-readable index."""

    model_config = ConfigDict(extra="forbid")

    project_root: str
    generated_at: str
    counts: ProjectCounts
    symbols_by_id: dict[int, SymbolRecord]
    name_lookup: dict[str, list[int]]
    qualified_name_lookup: dict[str, list[int]]


class ValidationIssue(BaseModel):
    """Single validation issue or warning."""

    model_config = ConfigDict(extra="forbid")

    stage: ValidationStage
    code: str
    severity: ValidationSeverity
    message: str
    symbol_id: int | None = None
    file_path: str | None = None
    line: int | None = None
    column: int | None = None
    field: str | None = None
    hint: str | None = None


class ValidationReport(BaseModel):
    """Aggregated validation result."""

    model_config = ConfigDict(extra="forbid")

    status: ValidationStatus
    error_count: int
    warning_count: int
    issues: list[ValidationIssue] = Field(default_factory=list)

    @classmethod
    def from_issues(cls, issues: Iterable[ValidationIssue]) -> "ValidationReport":
        issue_list = list(issues)
        error_count = sum(1 for issue in issue_list if issue.severity == "error")
        warning_count = sum(1 for issue in issue_list if issue.severity == "warning")
        if error_count:
            status: ValidationStatus = "error"
        elif warning_count:
            status = "warning"
        else:
            status = "ok"
        return cls(
            status=status,
            error_count=error_count,
            warning_count=warning_count,
            issues=issue_list,
        )
