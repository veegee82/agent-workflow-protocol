"""AWP Observability models (Layer 6) — Metrics, Tracing, Audit, Health, Evaluation."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from .evaluation import EvaluationConfig


class LoggingConfig(BaseModel):
    """Logging configuration."""

    level: str = "INFO"
    format: str = "json"  # json | text | structured
    destination: str = "stdout"  # stdout | file | otlp
    log_agent_io: bool = True
    log_state_transitions: bool = True
    log_llm_prompts: bool = True
    log_tool_calls: bool = True
    path: str = "logs"

    model_config = {"extra": "allow"}


class CustomMetric(BaseModel):
    """Custom metric definition."""

    name: str
    type: str = "counter"  # counter | gauge | histogram
    description: str = ""
    labels: list[str] = Field(default_factory=list)

    model_config = {"extra": "allow"}


class MetricsConfig(BaseModel):
    """Metrics collection configuration."""

    enabled: bool = False
    collector: str = "internal"  # internal | prometheus | otlp
    export_interval: int = 60  # seconds
    include: list[str] = Field(
        default_factory=lambda: [
            "agent_duration",
            "tool_calls",
            "llm_tokens",
            "error_rate",
            "memory_usage",
        ]
    )
    custom_metrics: list[CustomMetric] = Field(default_factory=list)
    endpoint: Optional[str] = None

    model_config = {"extra": "allow"}


class TracingConfig(BaseModel):
    """Distributed tracing configuration."""

    enabled: bool = False
    exporter: str = "internal"  # internal | otlp | jaeger | zipkin
    sample_rate: float = 1.0
    propagation: str = "w3c"  # w3c | b3 | jaeger
    endpoint: Optional[str] = None
    service_name: Optional[str] = None


class AuditConfig(BaseModel):
    """Audit trail configuration."""

    enabled: bool = False
    format: str = "jsonl"  # jsonl | json
    hash_chain: bool = True  # Each entry contains hash of previous
    include_events: list[str] = Field(
        default_factory=lambda: [
            "agent_start",
            "agent_complete",
            "tool_call",
            "state_change",
            "error",
            "security_event",
        ]
    )
    include_inputs: bool = False
    include_outputs: bool = False
    path: str = "logs/audit"
    retention_days: int = 90

    model_config = {"extra": "allow"}


class LivenessFailureConfig(BaseModel):
    """What to do when liveness checks fail."""

    max_consecutive: int = 3
    action: str = "pause_and_notify"  # pause_and_notify | abort | ignore


class ReadinessConfig(BaseModel):
    """Readiness check — before workflow starts."""

    checks: list[str] = Field(
        default_factory=lambda: [
            "llm_provider_reachable",
            "tools_available",
        ]
    )
    timeout: int = 10
    on_failure: str = "abort"  # abort | warn | skip


class LivenessConfig(BaseModel):
    """Liveness check — during workflow execution."""

    interval: int = 30
    timeout: int = 5
    checks: list[str] = Field(
        default_factory=lambda: [
            "llm_provider_reachable",
            "memory_backend_writable",
        ]
    )
    on_failure: LivenessFailureConfig = Field(
        default_factory=lambda: LivenessFailureConfig()
    )


class HealthCheckConfig(BaseModel):
    """Health check configuration."""

    readiness: ReadinessConfig = Field(default_factory=lambda: ReadinessConfig())
    liveness: LivenessConfig = Field(default_factory=lambda: LivenessConfig())


class OutputContractExtra(BaseModel):
    """One workflow-specific Layer-0 output-contract check.

    Loaded by :class:`awp.runtime.critique.l0_validator.L0Validator`
    via ``importlib``. ``implementation`` is ``module.path:AttrName``
    where ``AttrName`` is either a class (instantiated without args)
    or a pre-built callable conforming to
    :class:`awp.runtime.critique.contracts.OutputContractCheck`.
    """

    name: str
    implementation: str  # "module.path:ClassOrCallable"

    model_config = {"extra": "allow"}


class OutputContractConfig(BaseModel):
    """Layer-0 output-contract chain (R34).

    Runs a chain of fast, bit-level checks over every worker output
    BEFORE the LLM critique gate fires. Defined in
    :mod:`awp.runtime.critique.l0_validator`.

    ``checks`` accepts the special token ``"default"`` which expands to
    the 6 bundled checks (``no_placeholder``, ``no_text_loop``,
    ``file_size_delta``, ``no_duplicate_headings``,
    ``balanced_delimiters``, ``json_valid_if_claimed``). Individual
    check names may also be listed to filter down the set.

    ``extra`` lets workflow authors add their own checks without
    modifying AWP core. Each entry MUST point at a callable implementing
    the :class:`OutputContractCheck` protocol.

    ``enabled: false`` disables the L0 gate entirely — the gate chain
    falls through to the existing critique / placeholder / file / eval
    chain unchanged.
    """

    enabled: bool = True
    checks: list[str] = Field(default_factory=lambda: ["default"])
    extra: list[OutputContractExtra] = Field(default_factory=list)

    model_config = {"extra": "allow"}


class ObservabilityConfig(BaseModel):
    """Complete observability configuration (Layer 6)."""

    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    metrics: MetricsConfig = Field(default_factory=MetricsConfig)
    tracing: TracingConfig = Field(default_factory=TracingConfig)
    audit: AuditConfig = Field(default_factory=AuditConfig)
    health: HealthCheckConfig = Field(default_factory=HealthCheckConfig)
    evaluation: Optional[EvaluationConfig] = None
    output_contract: OutputContractConfig = Field(default_factory=OutputContractConfig)

    model_config = {"extra": "allow"}
