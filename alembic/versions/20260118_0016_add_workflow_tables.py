"""Add workflow and skills tables for Atlas Agents Platform.

Revision ID: 20260118_0016
Revises: 20260107_0015
Create Date: 2026-01-18

Tables created:
- workflows: Workflow definitions with LangGraph graph and visual layout
- workflow_executions: Runtime execution tracking
- execution_steps: Individual step execution logs with LLM details
- human_interventions: Human-in-the-loop approval requests
- skills: Registered skill capabilities
- skill_actions: Individual actions within skills
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260118_0016"
down_revision: str | None = "20260107_0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Workflows - workflow definitions
    op.create_table(
        "workflows",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        # Trigger configuration
        sa.Column(
            "trigger_type",
            sa.String(50),
            nullable=False,
            comment="manual, webhook, schedule, event",
        ),
        sa.Column("trigger_config", sa.JSON(), nullable=True),
        # Graph definitions
        sa.Column("graph_definition", sa.JSON(), nullable=False, comment="LangGraph compatible definition"),
        sa.Column("visual_definition", sa.JSON(), nullable=False, comment="React Flow positions for UI"),
        # Versioning
        sa.Column("version", sa.Integer(), default=1, nullable=False),
        sa.Column("is_active", sa.Boolean(), default=True, nullable=False),
        # Timestamps
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("name", name="uq_workflow_name"),
    )
    op.create_index("ix_workflows_trigger_type", "workflows", ["trigger_type"])
    op.create_index("ix_workflows_is_active", "workflows", ["is_active"])

    # Workflow Executions - runtime tracking
    op.create_table(
        "workflow_executions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workflow_id", sa.String(36), sa.ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False),
        # Status tracking
        sa.Column(
            "status",
            sa.String(50),
            nullable=False,
            comment="running, paused, completed, failed, waiting_human",
        ),
        # Context
        sa.Column("trigger_data", sa.JSON(), nullable=True),
        sa.Column("current_state", sa.JSON(), nullable=True, comment="LangGraph state snapshot"),
        sa.Column("current_node", sa.String(255), nullable=True),
        # Timestamps
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        # Error handling
        sa.Column("error_message", sa.Text(), nullable=True),
    )
    op.create_index("ix_workflow_executions_workflow_id", "workflow_executions", ["workflow_id"])
    op.create_index("ix_workflow_executions_status", "workflow_executions", ["status"])
    op.create_index("ix_workflow_executions_started_at", "workflow_executions", ["started_at"])

    # Execution Steps - individual node executions
    op.create_table(
        "execution_steps",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "execution_id",
            sa.String(36),
            sa.ForeignKey("workflow_executions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # Node info
        sa.Column("node_id", sa.String(255), nullable=False),
        sa.Column("node_type", sa.String(50), nullable=False, comment="agent, tool, condition, human"),
        # Data
        sa.Column("input_data", sa.JSON(), nullable=True),
        sa.Column("output_data", sa.JSON(), nullable=True),
        sa.Column("llm_messages", sa.JSON(), nullable=True, comment="Full LLM conversation for debugging"),
        # Metrics
        sa.Column("tokens_used", sa.Integer(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        # Status
        sa.Column("status", sa.String(50), nullable=False, comment="pending, running, completed, failed, skipped"),
        sa.Column("error_message", sa.Text(), nullable=True),
        # Timestamps
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_execution_steps_execution_id", "execution_steps", ["execution_id"])
    op.create_index("ix_execution_steps_node_id", "execution_steps", ["node_id"])
    op.create_index("ix_execution_steps_status", "execution_steps", ["status"])

    # Human Interventions - approval requests
    op.create_table(
        "human_interventions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "execution_id",
            sa.String(36),
            sa.ForeignKey("workflow_executions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "step_id",
            sa.String(36),
            sa.ForeignKey("execution_steps.id", ondelete="CASCADE"),
            nullable=True,
        ),
        # Intervention details
        sa.Column(
            "intervention_type",
            sa.String(50),
            nullable=False,
            comment="approval, input, review, decision",
        ),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("options", sa.JSON(), nullable=True, comment="Available choices if applicable"),
        # Assignment
        sa.Column("assigned_to", sa.String(255), nullable=True),
        # Response
        sa.Column("response", sa.JSON(), nullable=True),
        sa.Column("responded_at", sa.DateTime(timezone=True), nullable=True),
        # Timestamps
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_human_interventions_execution_id", "human_interventions", ["execution_id"])
    op.create_index("ix_human_interventions_intervention_type", "human_interventions", ["intervention_type"])
    op.create_index("ix_human_interventions_assigned_to", "human_interventions", ["assigned_to"])

    # Skills - registered skill capabilities
    op.create_table(
        "skills",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False, unique=True),
        sa.Column("category", sa.String(100), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        # Implementation
        sa.Column("python_module", sa.String(255), nullable=False, comment="Module path for import"),
        # Schemas (JSON Schema format)
        sa.Column("config_schema", sa.JSON(), nullable=True),
        sa.Column("input_schema", sa.JSON(), nullable=True),
        sa.Column("output_schema", sa.JSON(), nullable=True),
        # Settings
        sa.Column("is_enabled", sa.Boolean(), default=True, nullable=False),
        sa.Column("requires_approval", sa.Boolean(), default=False, nullable=False),
        # Timestamps
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_skills_category", "skills", ["category"])
    op.create_index("ix_skills_is_enabled", "skills", ["is_enabled"])

    # Skill Actions - individual actions within skills
    op.create_table(
        "skill_actions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("skill_id", sa.String(36), sa.ForeignKey("skills.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        # Schemas
        sa.Column("input_schema", sa.JSON(), nullable=True),
        sa.Column("output_schema", sa.JSON(), nullable=True),
        # Flags
        sa.Column("is_destructive", sa.Boolean(), default=False, nullable=False),
        sa.UniqueConstraint("skill_id", "name", name="uq_skill_action"),
    )
    op.create_index("ix_skill_actions_skill_id", "skill_actions", ["skill_id"])


def downgrade() -> None:
    op.drop_table("skill_actions")
    op.drop_table("skills")
    op.drop_table("human_interventions")
    op.drop_table("execution_steps")
    op.drop_table("workflow_executions")
    op.drop_table("workflows")
