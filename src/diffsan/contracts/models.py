"""Pydantic data contracts for diffsan pipeline modules."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from diffsan.contracts.errors import ErrorInfo  # noqa: TC001

Severity = Literal["info", "low", "medium", "high", "critical"]
Category = Literal[
    "correctness",
    "security",
    "performance",
    "maintainability",
    "style",
    "testing",
    "docs",
    "other",
]


class StrictModel(BaseModel):
    """Base model with strict unknown-field handling."""

    model_config = ConfigDict(extra="forbid")


class ModeConfig(StrictModel):
    ci: bool = False


class LimitsConfig(StrictModel):
    max_diff_chars: int = 200_000
    max_files: int = 60
    max_hunks_per_file: int = 40


class TruncationConfig(StrictModel):
    priority_extensions: list[str] = Field(
        default_factory=lambda: [
            ".py",
            ".js",
            ".ts",
            ".go",
            ".java",
            ".rb",
            ".php",
            ".rs",
        ]
    )
    depriority_extensions: list[str] = Field(
        default_factory=lambda: [".md", ".rst", ".txt", ".lock"]
    )
    include_extensions: list[str] | None = None
    ignore_globs: list[str] = Field(
        default_factory=lambda: ["docs/**", "**/*.generated.*"]
    )


class SecretsConfig(StrictModel):
    enabled: bool = True
    extra_patterns: list[str] = Field(default_factory=list)
    post_warning_to_mr: bool = True


class SkipConfig(StrictModel):
    skip_on_auto_merge: bool = True
    skip_on_same_fingerprint: bool = True


class AgentConfig(StrictModel):
    agent: Literal["cursor", "codex"] = "cursor"
    cursor_command: str | None = None
    codex_command: str | None = None
    proxy_url: str | None = None
    max_json_retries: int = 3
    json_repair_prompt: str = "Return ONLY valid JSON that matches the schema."
    verbosity: Literal["low", "medium", "high"] = "medium"
    skills: list[str] = Field(default_factory=list)
    prompt_template: str | None = None

    @model_validator(mode="after")
    def validate_codex_only_fields(self) -> AgentConfig:
        """Reject Codex-only options for non-Codex agents."""
        if self.proxy_url is not None and self.agent != "codex":
            raise ValueError(
                "agent.proxy_url is only supported when agent.agent='codex'"
            )
        return self


class GitLabConfig(StrictModel):
    enabled: bool = True
    base_url: str = "https://gitlab.com"
    project_id: str | None = None
    mr_iid: int | None = None
    token_env: str = "GITLAB_TOKEN"
    idempotent_summary: bool = False
    summary_note_tag: str = "ai-reviewer"
    retry_max: int = 3


class LoggingConfig(StrictModel):
    level: Literal["error", "warn", "info", "debug"] = "info"
    structured: bool = True


def _default_note_timezone() -> str:
    local_now = datetime.now().astimezone()
    tzinfo = local_now.tzinfo
    if tzinfo is not None:
        key = getattr(tzinfo, "key", None)
        if isinstance(key, str) and key:
            return key

    offset = local_now.strftime("%z")
    if len(offset) == 5 and offset[0] in {"+", "-"}:
        return f"{offset[:3]}:{offset[3:]}"

    tz_name = local_now.strftime("%Z")
    if tz_name:
        return tz_name
    return "UTC"


class AppConfig(StrictModel):
    workdir: str = ".diffsan"
    note_timezone: str = Field(default_factory=_default_note_timezone)
    mode: ModeConfig = Field(default_factory=ModeConfig)
    limits: LimitsConfig = Field(default_factory=LimitsConfig)
    truncation: TruncationConfig = Field(default_factory=TruncationConfig)
    secrets: SecretsConfig = Field(default_factory=SecretsConfig)
    skip: SkipConfig = Field(default_factory=SkipConfig)
    agent: AgentConfig = Field(default_factory=AgentConfig)
    gitlab: GitLabConfig = Field(default_factory=GitLabConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)


class DiffRef(StrictModel):
    target_branch: str | None = None
    source_branch: str | None = None
    base_sha: str | None = None
    head_sha: str | None = None


class DiffSource(StrictModel):
    kind: str = "git-diff"
    ref: DiffRef = Field(default_factory=DiffRef)


class DiffFile(StrictModel):
    path: str
    additions: int = 0
    deletions: int = 0
    is_binary: bool = False


class DiffBundle(StrictModel):
    source: DiffSource = Field(default_factory=DiffSource)
    raw_diff: str
    files: list[DiffFile] = Field(default_factory=list)


class TruncationItem(StrictModel):
    kind: str
    path: str | None = None
    details: str


class TruncationReport(StrictModel):
    truncated: bool = False
    original_chars: int = 0
    final_chars: int = 0
    original_files: int = 0
    final_files: int = 0
    items: list[TruncationItem] = Field(default_factory=list)


class RedactionMatch(StrictModel):
    pattern_name: str
    path: str | None = None
    line_hint: int | None = None
    match_sha256: str
    match_length: int


class RedactionReport(StrictModel):
    enabled: bool = True
    found: bool = False
    matches: list[RedactionMatch] = Field(default_factory=list)
    redaction_token: str = "[REDACTED]"


class PreparedDiff(StrictModel):
    prepared_diff: str
    truncation: TruncationReport = Field(default_factory=TruncationReport)
    redaction: RedactionReport = Field(default_factory=RedactionReport)
    ignored_paths: list[str] = Field(default_factory=list)
    included_paths: list[str] = Field(default_factory=list)


class Fingerprint(StrictModel):
    algo: str = "sha256"
    value: str


class PriorFinding(StrictModel):
    finding_id: str
    path: str
    line_range: str
    title: str
    severity: Severity


class PriorSummary(StrictModel):
    note_id: int | None = None
    text: str


class PriorInlineComment(StrictModel):
    discussion_id: str | None = None
    note_id: int | None = None
    path: str | None = None
    line: int | None = None
    resolved: bool | None = None
    body: str


class PriorDigest(StrictModel):
    prior_fingerprint: Fingerprint | None = None
    findings: list[PriorFinding] = Field(default_factory=list)
    summary_hint: str | None = None
    summaries: list[PriorSummary] = Field(default_factory=list)
    inline_comments: list[PriorInlineComment] = Field(default_factory=list)


class SkipReason(StrictModel):
    code: str
    message: str


class SkipDecision(StrictModel):
    should_skip: bool = False
    reasons: list[SkipReason] = Field(default_factory=list)
    fingerprint: Fingerprint | None = None
    prior_digest: PriorDigest | None = None


class AgentRequestMeta(StrictModel):
    fingerprint: Fingerprint | None = None
    truncation: TruncationReport | None = None
    redaction_found: bool = False
    agent: str = "cursor"
    verbosity: Literal["low", "medium", "high"] = "medium"
    skills: list[str] = Field(default_factory=list)


class AgentRequest(StrictModel):
    prompt: str
    meta: AgentRequestMeta = Field(default_factory=AgentRequestMeta)


class SuggestedPatch(StrictModel):
    format: str
    content: str


class Finding(StrictModel):
    finding_id: str | None = None
    severity: Severity
    category: Category
    path: str
    line_start: int
    line_end: int
    body_markdown: str
    suggested_patch: SuggestedPatch | None = None


class TimingMeta(StrictModel):
    started_at: AwareDatetime
    ended_at: AwareDatetime
    duration_ms: int


class ReviewMeta(StrictModel):
    fingerprint: Fingerprint | None = None
    agent: str = "cursor"
    timings: TimingMeta | None = None
    token_usage: dict[str, Any] = Field(default_factory=dict)
    truncated: bool = False
    redaction_found: bool = False


class AgentReviewOutput(StrictModel):
    summary_markdown: str
    findings: list[Finding] = Field(default_factory=list)


class ReviewOutput(StrictModel):
    summary_markdown: str
    findings: list[Finding] = Field(default_factory=list)
    meta: ReviewMeta = Field(default_factory=ReviewMeta)


class DiscussionPosition(StrictModel):
    position_type: Literal["text"] = "text"
    base_sha: str
    head_sha: str
    start_sha: str
    new_path: str
    new_line: int


class DiscussionPlan(StrictModel):
    path: str
    line_start: int
    line_end: int
    body_markdown: str
    position: DiscussionPosition | None = None
    severity: Severity
    category: Category


class PostPlan(StrictModel):
    summary_markdown: str
    summary_meta_collapsible: str = ""
    discussions: list[DiscussionPlan] = Field(default_factory=list)
    idempotent_summary: bool = False
    prior_summary_note_id: int | None = None


class PostResultItem(StrictModel):
    kind: Literal["summary_note", "discussion"]
    ok: bool
    http_status: int | None = None
    gitlab_id: int | None = None
    retry_count: int = 0
    error: ErrorInfo | None = None


class PostResults(StrictModel):
    ok: bool
    items: list[PostResultItem] = Field(default_factory=list)


class ArtifactPointers(StrictModel):
    workdir: str
    prompt: str = "prompt.txt"
    raw_output: str = "agent.raw.txt"
    review: str = "review.json"


class RunResult(StrictModel):
    ok: bool
    skipped: bool = False
    skip_reasons: list[SkipReason] = Field(default_factory=list)
    fingerprint: Fingerprint | None = None
    error: ErrorInfo | None = None
    artifacts: ArtifactPointers | None = None
