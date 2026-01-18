from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    role: Mapped[str] = mapped_column(String(16), default="member", nullable=False)
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    external_provider: Mapped[str | None] = mapped_column(String(32), nullable=True)
    external_subject: Mapped[str | None] = mapped_column(String(255), nullable=True)
    system_username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)

    api_keys: Mapped[list[UserAPIKey]] = relationship(back_populates="user", cascade="all, delete-orphan")
    playground_sessions: Mapped[list[PlaygroundSession]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    playground_presets: Mapped[list[PlaygroundPreset]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class UserAPIKey(Base):
    __tablename__ = "user_api_keys"
    __table_args__ = (UniqueConstraint("user_id", "provider", name="uq_user_provider"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    label: Mapped[str | None] = mapped_column(String(120), nullable=True)
    secret: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)

    user: Mapped[User] = relationship(back_populates="api_keys")


class GlobalAPIKey(Base):
    __tablename__ = "global_api_keys"
    __table_args__ = (UniqueConstraint("provider", name="uq_global_provider"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    label: Mapped[str | None] = mapped_column(String(120), nullable=True)
    secret: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)


class SecureSetting(Base):
    __tablename__ = "secure_settings"

    name: Mapped[str] = mapped_column(String(64), primary_key=True)
    encrypted_value: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)


class RolePermission(Base):
    __tablename__ = "role_permissions"

    role: Mapped[str] = mapped_column(String(32), primary_key=True)
    label: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)
    permissions: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)


class ChatSession(Base):
    __tablename__ = "chat_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    session_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    user_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"), nullable=True)
    title: Mapped[str] = mapped_column(String(200), default="New AI Chat", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)
    context_variables: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    # AI Chat fields
    agent_config_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    provider_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    model: Mapped[str | None] = mapped_column(String(128), nullable=True)

    user: Mapped[User | None] = relationship()
    messages: Mapped[list[ChatMessage]] = relationship(
        back_populates="session", cascade="all, delete-orphan", order_by="ChatMessage.created_at"
    )


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    session_id: Mapped[str] = mapped_column(String(36), ForeignKey("chat_sessions.id"), nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False)  # user, assistant, system, tool
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    # AI Chat fields for tool calls
    message_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    tool_call_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    tool_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    session: Mapped[ChatSession] = relationship(back_populates="messages")


class VCenterConfig(Base):
    __tablename__ = "vcenter_configs"
    __table_args__ = (UniqueConstraint("name", name="uq_vcenter_config_name"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    base_url: Mapped[str] = mapped_column(String(255), nullable=False)
    username: Mapped[str] = mapped_column(String(128), nullable=False)
    password_secret: Mapped[str] = mapped_column(String(128), nullable=False)
    verify_ssl: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_esxi: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )


class ModuleConfig(Base):
    __tablename__ = "module_configs"

    module_name: Mapped[str] = mapped_column(String(64), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    config_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )


class ForemanConfig(Base):
    __tablename__ = "foreman_configs"
    __table_args__ = (UniqueConstraint("name", name="uq_foreman_config_name"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    base_url: Mapped[str] = mapped_column(String(255), nullable=False)
    username: Mapped[str] = mapped_column(String(128), nullable=False)
    token_secret: Mapped[str] = mapped_column(String(128), nullable=False)
    verify_ssl: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )


class PuppetConfig(Base):
    """Configuration for a Puppet Git repository source."""

    __tablename__ = "puppet_configs"
    __table_args__ = (UniqueConstraint("name", name="uq_puppet_config_name"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    remote_url: Mapped[str] = mapped_column(String(512), nullable=False)
    branch: Mapped[str] = mapped_column(String(128), default="production", nullable=False)
    ssh_key_secret: Mapped[str | None] = mapped_column(String(128), nullable=True)
    local_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )


class AIActivityLog(Base):
    """Log of all AI API calls for usage tracking and billing."""

    __tablename__ = "ai_activity_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    generation_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, index=True)

    # Provider and model info
    provider: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    model: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    model_provider: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # Token usage
    tokens_prompt: Mapped[int] = mapped_column(default=0, nullable=False)
    tokens_completion: Mapped[int] = mapped_column(default=0, nullable=False)
    tokens_reasoning: Mapped[int] = mapped_column(default=0, nullable=False)
    tokens_total: Mapped[int] = mapped_column(default=0, nullable=False)

    # Cost tracking
    cost_usd: Mapped[float] = mapped_column(default=0.0, nullable=False)

    # Performance metrics
    generation_time_ms: Mapped[int | None] = mapped_column(nullable=True)
    time_to_first_token_ms: Mapped[int | None] = mapped_column(nullable=True)
    tokens_per_second: Mapped[float | None] = mapped_column(nullable=True)

    # Request info
    streamed: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    finish_reason: Mapped[str | None] = mapped_column(String(32), nullable=True)
    cancelled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Context
    user_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"), nullable=True)
    session_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    app_name: Mapped[str | None] = mapped_column(String(64), nullable=True)

    user: Mapped[User | None] = relationship()


class AIModelConfig(Base):
    """Custom model configurations and pricing overrides."""

    __tablename__ = "ai_model_configs"
    __table_args__ = (UniqueConstraint("provider", "model_id", name="uq_provider_model"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    model_id: Mapped[str] = mapped_column(String(128), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(128), nullable=True)

    # Pricing per 1M tokens
    price_input_per_million: Mapped[float] = mapped_column(default=0.0, nullable=False)
    price_output_per_million: Mapped[float] = mapped_column(default=0.0, nullable=False)

    # Model capabilities
    context_window: Mapped[int | None] = mapped_column(nullable=True)
    supports_tools: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    supports_streaming: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    supports_vision: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Status
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_preferred: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )


# ============================================================================
# Atlas Agents Platform - Workflow and Skills Tables
# ============================================================================


class Workflow(Base):
    """Workflow definition with LangGraph graph and visual layout."""

    __tablename__ = "workflows"
    __table_args__ = (UniqueConstraint("name", name="uq_workflow_name"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Trigger configuration
    trigger_type: Mapped[str] = mapped_column(String(50), nullable=False)  # manual, webhook, schedule, event
    trigger_config: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    # Graph definitions
    graph_definition: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)  # LangGraph compatible
    visual_definition: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)  # React Flow positions

    # Versioning
    version: Mapped[int] = mapped_column(default=1, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )

    # Relationships
    executions: Mapped[list[WorkflowExecution]] = relationship(
        back_populates="workflow", cascade="all, delete-orphan"
    )


class WorkflowExecution(Base):
    """Runtime execution tracking for workflows."""

    __tablename__ = "workflow_executions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    workflow_id: Mapped[str] = mapped_column(String(36), ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False)

    # Status tracking
    status: Mapped[str] = mapped_column(String(50), nullable=False)  # running, paused, completed, failed, waiting_human

    # Context
    trigger_data: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    current_state: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)  # LangGraph state snapshot
    current_node: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Timestamps
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Error handling
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Relationships
    workflow: Mapped[Workflow] = relationship(back_populates="executions")
    steps: Mapped[list[ExecutionStep]] = relationship(
        back_populates="execution", cascade="all, delete-orphan", order_by="ExecutionStep.created_at"
    )
    interventions: Mapped[list[HumanIntervention]] = relationship(
        back_populates="execution", cascade="all, delete-orphan"
    )


class ExecutionStep(Base):
    """Individual node execution logs with LLM details."""

    __tablename__ = "execution_steps"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    execution_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("workflow_executions.id", ondelete="CASCADE"), nullable=False
    )

    # Node info
    node_id: Mapped[str] = mapped_column(String(255), nullable=False)
    node_type: Mapped[str] = mapped_column(String(50), nullable=False)  # agent, tool, condition, human

    # Data
    input_data: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    output_data: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    llm_messages: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, nullable=True)  # For debugging

    # Metrics
    tokens_used: Mapped[int | None] = mapped_column(nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(nullable=True)

    # Status
    status: Mapped[str] = mapped_column(String(50), nullable=False)  # pending, running, completed, failed, skipped
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)

    # Relationships
    execution: Mapped[WorkflowExecution] = relationship(back_populates="steps")


class HumanIntervention(Base):
    """Human-in-the-loop approval requests."""

    __tablename__ = "human_interventions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    execution_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("workflow_executions.id", ondelete="CASCADE"), nullable=False
    )
    step_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("execution_steps.id", ondelete="CASCADE"), nullable=True
    )

    # Intervention details
    intervention_type: Mapped[str] = mapped_column(String(50), nullable=False)  # approval, input, review, decision
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    options: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)  # Available choices

    # Assignment
    assigned_to: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Response
    response: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    responded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)

    # Relationships
    execution: Mapped[WorkflowExecution] = relationship(back_populates="interventions")


class Skill(Base):
    """Registered skill capabilities."""

    __tablename__ = "skills"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    category: Mapped[str | None] = mapped_column(String(100), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Implementation
    python_module: Mapped[str] = mapped_column(String(255), nullable=False)  # Module path for import

    # Schemas (JSON Schema format)
    config_schema: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    input_schema: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    output_schema: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    # Settings
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    requires_approval: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)

    # Relationships
    actions: Mapped[list[SkillAction]] = relationship(back_populates="skill", cascade="all, delete-orphan")


class SkillAction(Base):
    """Individual actions within skills."""

    __tablename__ = "skill_actions"
    __table_args__ = (UniqueConstraint("skill_id", "name", name="uq_skill_action"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    skill_id: Mapped[str] = mapped_column(String(36), ForeignKey("skills.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Schemas
    input_schema: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    output_schema: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    # Flags
    is_destructive: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Relationships
    skill: Mapped[Skill] = relationship(back_populates="actions")


# ==============================================================================
# Agent Playground Models
# ==============================================================================


class PlaygroundSession(Base):
    """Ephemeral sessions for agent testing in the playground."""

    __tablename__ = "playground_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    agent_id: Mapped[str] = mapped_column(String(255), nullable=False)
    user_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=True)

    # Session state
    state: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    config_override: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    messages: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)

    # Metrics
    total_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_cost_usd: Mapped[float | None] = mapped_column(Float, default=0.0, nullable=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    # Relationships
    user: Mapped[User | None] = relationship(back_populates="playground_sessions")


class PlaygroundPreset(Base):
    """Saved configuration presets for agent playground."""

    __tablename__ = "playground_presets"
    __table_args__ = (UniqueConstraint("user_id", "name", name="uq_preset_user_name"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    agent_id: Mapped[str] = mapped_column(String(255), nullable=False)

    # Configuration
    config: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)

    # Ownership
    user_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=True)
    is_shared: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    # Relationships
    user: Mapped[User | None] = relationship(back_populates="playground_presets")
