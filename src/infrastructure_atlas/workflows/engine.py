"""Workflow engine for LangGraph-based workflow execution.

The WorkflowEngine manages the lifecycle of workflow executions:
- Loading workflow definitions
- Creating and running graphs
- Handling interrupts for human-in-the-loop
- Persisting state via checkpointing
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph
from langgraph.graph.state import CompiledStateGraph

from infrastructure_atlas.infrastructure.logging import get_logger
from infrastructure_atlas.workflows.state import WorkflowState, create_initial_state

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

logger = get_logger(__name__)


class WorkflowEngine:
    """Engine for executing LangGraph workflows.

    The engine:
    - Compiles workflow definitions into executable graphs
    - Manages checkpointing for state persistence
    - Handles human-in-the-loop interrupts
    - Tracks execution in the database

    Example usage:
        engine = WorkflowEngine()

        # Create and run a workflow
        execution_id = engine.execute(
            workflow_id="esd_triage_v1",
            trigger_type="webhook",
            trigger_data={"ticket_id": "ESD-1234"},
        )

        # Check status
        status = engine.get_status(execution_id)

        # Resume after human input
        engine.resume(execution_id, {"approved": True})
    """

    def __init__(
        self,
        db_session: Session | None = None,
        checkpointer: MemorySaver | None = None,
    ):
        """Initialize the workflow engine.

        Args:
            db_session: Optional SQLAlchemy session for persistence
            checkpointer: Optional LangGraph checkpointer (defaults to MemorySaver)
        """
        self._db_session = db_session
        self._checkpointer = checkpointer or MemorySaver()
        self._compiled_workflows: dict[str, CompiledStateGraph] = {}
        self._node_registry: dict[str, Callable] = {}

    def register_node(self, name: str, func: Callable[[dict[str, Any]], dict[str, Any]]) -> None:
        """Register a node function for use in workflows.

        Args:
            name: Node name
            func: Node function that takes state and returns updated state
        """
        self._node_registry[name] = func
        logger.debug(f"Registered workflow node: {name}")

    def compile_workflow(
        self,
        workflow_id: str,
        nodes: list[str],
        edges: list[tuple[str, str]],
        conditional_edges: list[tuple[str, Callable, dict[str, str]]] | None = None,
        interrupt_before: list[str] | None = None,
    ) -> CompiledStateGraph:
        """Compile a workflow definition into an executable graph.

        Args:
            workflow_id: Unique workflow identifier
            nodes: List of node names (must be registered)
            edges: List of (from_node, to_node) edges
            conditional_edges: List of (from_node, condition_func, {result: target}) tuples
            interrupt_before: Nodes to pause before for human input

        Returns:
            Compiled LangGraph StateGraph
        """
        # Create the graph with WorkflowState
        builder = StateGraph(WorkflowState)

        # Add nodes
        for node_name in nodes:
            if node_name not in self._node_registry:
                raise ValueError(f"Node '{node_name}' not registered")
            builder.add_node(node_name, self._node_registry[node_name])

        # Set entry point (first node)
        if nodes:
            builder.set_entry_point(nodes[0])

        # Add edges
        for from_node, to_node in edges:
            if to_node == "END":
                builder.add_edge(from_node, END)
            else:
                builder.add_edge(from_node, to_node)

        # Add conditional edges
        if conditional_edges:
            for from_node, condition_func, path_map in conditional_edges:
                # Convert "END" string to actual END constant
                converted_map = {}
                for result, target in path_map.items():
                    converted_map[result] = END if target == "END" else target
                builder.add_conditional_edges(from_node, condition_func, converted_map)

        # Compile with checkpointing and interrupts
        compiled = builder.compile(
            checkpointer=self._checkpointer,
            interrupt_before=interrupt_before or [],
        )

        self._compiled_workflows[workflow_id] = compiled
        logger.info(f"Compiled workflow: {workflow_id}", extra={"nodes": len(nodes)})

        return compiled

    def execute(
        self,
        workflow_id: str,
        trigger_type: str,
        trigger_data: dict[str, Any] | None = None,
        initial_state: dict[str, Any] | None = None,
    ) -> str:
        """Execute a workflow.

        Args:
            workflow_id: ID of compiled workflow to execute
            trigger_type: How the workflow was triggered
            trigger_data: Optional trigger payload
            initial_state: Optional additional initial state

        Returns:
            Execution ID for tracking
        """
        if workflow_id not in self._compiled_workflows:
            raise ValueError(f"Workflow '{workflow_id}' not compiled")

        execution_id = str(uuid.uuid4())
        graph = self._compiled_workflows[workflow_id]

        # Create initial state
        state = create_initial_state(
            workflow_id=workflow_id,
            execution_id=execution_id,
            trigger_type=trigger_type,
            trigger_data=trigger_data,
        )

        # Merge any additional initial state
        if initial_state:
            state.update(initial_state)

        # Create thread config for checkpointing
        config = {"configurable": {"thread_id": execution_id}}

        logger.info(
            f"Starting workflow execution: {execution_id}",
            extra={
                "workflow_id": workflow_id,
                "trigger_type": trigger_type,
            },
        )

        # Record execution start if we have a DB session
        if self._db_session:
            self._record_execution_start(workflow_id, execution_id, trigger_type, trigger_data)

        try:
            # Run the workflow
            result = graph.invoke(state, config)

            # Update execution record
            if self._db_session:
                self._record_execution_complete(execution_id, result)

            logger.info(f"Workflow execution completed: {execution_id}")
            return execution_id

        except Exception as e:
            logger.error(f"Workflow execution failed: {execution_id}: {e!s}")
            if self._db_session:
                self._record_execution_error(execution_id, str(e))
            raise

    def resume(
        self,
        execution_id: str,
        human_response: dict[str, Any],
    ) -> dict[str, Any]:
        """Resume a paused workflow after human input.

        Args:
            execution_id: ID of paused execution
            human_response: Human's response/decision

        Returns:
            Final workflow state
        """
        config = {"configurable": {"thread_id": execution_id}}

        # Get the graph (need to find which workflow this execution belongs to)
        state = self.get_state(execution_id)
        workflow_id = state.get("workflow_id")

        if workflow_id not in self._compiled_workflows:
            raise ValueError(f"Workflow '{workflow_id}' not found for execution")

        graph = self._compiled_workflows[workflow_id]

        # Update state with human response
        update = {
            "human_response": human_response,
            "requires_human": False,
        }

        logger.info(f"Resuming workflow execution: {execution_id}")

        # Resume with the update
        result = graph.invoke(update, config)

        if self._db_session:
            self._record_execution_complete(execution_id, result)

        return result

    def get_state(self, execution_id: str) -> dict[str, Any]:
        """Get current state of an execution.

        Args:
            execution_id: Execution ID

        Returns:
            Current state dict
        """
        config = {"configurable": {"thread_id": execution_id}}
        snapshot = self._checkpointer.get(config)

        if snapshot is None:
            raise ValueError(f"Execution '{execution_id}' not found")

        return dict(snapshot.values)

    def get_status(self, execution_id: str) -> dict[str, Any]:
        """Get execution status summary.

        Args:
            execution_id: Execution ID

        Returns:
            Status dict with state and metadata
        """
        try:
            state = self.get_state(execution_id)
            return {
                "execution_id": execution_id,
                "workflow_id": state.get("workflow_id"),
                "status": "waiting_human" if state.get("requires_human") else "running",
                "current_phase": state.get("current_phase"),
                "errors": state.get("errors", []),
            }
        except ValueError:
            return {
                "execution_id": execution_id,
                "status": "not_found",
            }

    def list_executions(
        self,
        workflow_id: str | None = None,
        status: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """List workflow executions.

        Args:
            workflow_id: Optional filter by workflow
            status: Optional filter by status
            limit: Maximum results

        Returns:
            List of execution summaries
        """
        if not self._db_session:
            return []

        from infrastructure_atlas.db.models import WorkflowExecution

        query = self._db_session.query(WorkflowExecution)

        if workflow_id:
            query = query.filter(WorkflowExecution.workflow_id == workflow_id)
        if status:
            query = query.filter(WorkflowExecution.status == status)

        query = query.order_by(WorkflowExecution.started_at.desc()).limit(limit)

        return [
            {
                "id": ex.id,
                "workflow_id": ex.workflow_id,
                "status": ex.status,
                "current_node": ex.current_node,
                "started_at": ex.started_at.isoformat() if ex.started_at else None,
                "completed_at": ex.completed_at.isoformat() if ex.completed_at else None,
            }
            for ex in query.all()
        ]

    # =========================================================================
    # Database recording methods
    # =========================================================================

    def _record_execution_start(
        self,
        workflow_id: str,
        execution_id: str,
        trigger_type: str,
        trigger_data: dict[str, Any] | None,
    ) -> None:
        """Record execution start in database."""
        from infrastructure_atlas.db.models import WorkflowExecution

        execution = WorkflowExecution(
            id=execution_id,
            workflow_id=workflow_id,
            status="running",
            trigger_data=trigger_data,
            started_at=datetime.now(UTC),
        )
        self._db_session.add(execution)
        self._db_session.commit()

    def _record_execution_complete(
        self,
        execution_id: str,
        final_state: dict[str, Any],
    ) -> None:
        """Record execution completion."""
        from infrastructure_atlas.db.models import WorkflowExecution

        execution = self._db_session.get(WorkflowExecution, execution_id)
        if execution:
            execution.status = "completed"
            execution.current_state = final_state
            execution.completed_at = datetime.now(UTC)
            self._db_session.commit()

    def _record_execution_error(
        self,
        execution_id: str,
        error_message: str,
    ) -> None:
        """Record execution error."""
        from infrastructure_atlas.db.models import WorkflowExecution

        execution = self._db_session.get(WorkflowExecution, execution_id)
        if execution:
            execution.status = "failed"
            execution.error_message = error_message
            execution.completed_at = datetime.now(UTC)
            self._db_session.commit()


def create_workflow_engine(db_session: Session | None = None) -> WorkflowEngine:
    """Factory function to create a WorkflowEngine.

    Args:
        db_session: Optional database session

    Returns:
        Configured WorkflowEngine instance
    """
    return WorkflowEngine(db_session=db_session)
