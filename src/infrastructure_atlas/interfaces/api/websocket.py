"""WebSocket endpoint for real-time workflow execution updates.

Provides:
- Real-time execution status updates
- Step completion notifications
- Human intervention requests
- Error notifications

Usage:
    Connect to: ws://{host}/ws/executions/{execution_id}

    Messages sent (server -> client):
    - {"type": "status", "status": "running", ...}
    - {"type": "step", "step": {...}}
    - {"type": "intervention", "intervention": {...}}
    - {"type": "error", "message": "..."}
    - {"type": "complete", "summary": {...}}
"""

from __future__ import annotations

import asyncio
import json
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any
from weakref import WeakSet

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy import select

from infrastructure_atlas.db import get_sessionmaker
from infrastructure_atlas.db.models import (
    ExecutionStep,
    HumanIntervention,
    WorkflowExecution,
)
from infrastructure_atlas.infrastructure.logging import get_logger

router = APIRouter()
logger = get_logger(__name__)

# Connection manager for WebSocket clients
# Maps execution_id -> set of WebSocket connections
_connections: dict[str, WeakSet[WebSocket]] = defaultdict(WeakSet)
_connections_lock = asyncio.Lock()


async def broadcast_to_execution(execution_id: str, message: dict[str, Any]) -> int:
    """Broadcast a message to all clients watching an execution.

    Args:
        execution_id: The execution ID
        message: Message dict to send

    Returns:
        Number of clients that received the message
    """
    async with _connections_lock:
        connections = _connections.get(execution_id, set())
        if not connections:
            return 0

        sent = 0
        dead_connections = []

        for ws in connections:
            try:
                await ws.send_json(message)
                sent += 1
            except Exception:
                dead_connections.append(ws)

        # Clean up dead connections
        for ws in dead_connections:
            connections.discard(ws)

        return sent


async def notify_status_change(execution_id: str, status: str, **extra: Any) -> None:
    """Notify clients of an execution status change."""
    await broadcast_to_execution(
        execution_id,
        {
            "type": "status",
            "execution_id": execution_id,
            "status": status,
            "timestamp": datetime.now(UTC).isoformat(),
            **extra,
        },
    )


async def notify_step_complete(execution_id: str, step: dict[str, Any]) -> None:
    """Notify clients of a step completion."""
    await broadcast_to_execution(
        execution_id,
        {
            "type": "step",
            "execution_id": execution_id,
            "step": step,
            "timestamp": datetime.now(UTC).isoformat(),
        },
    )


async def notify_intervention_required(
    execution_id: str,
    intervention: dict[str, Any],
) -> None:
    """Notify clients that human intervention is required."""
    await broadcast_to_execution(
        execution_id,
        {
            "type": "intervention",
            "execution_id": execution_id,
            "intervention": intervention,
            "timestamp": datetime.now(UTC).isoformat(),
        },
    )


async def notify_error(execution_id: str, message: str) -> None:
    """Notify clients of an error."""
    await broadcast_to_execution(
        execution_id,
        {
            "type": "error",
            "execution_id": execution_id,
            "message": message,
            "timestamp": datetime.now(UTC).isoformat(),
        },
    )


async def notify_complete(execution_id: str, summary: dict[str, Any]) -> None:
    """Notify clients that execution is complete."""
    await broadcast_to_execution(
        execution_id,
        {
            "type": "complete",
            "execution_id": execution_id,
            "summary": summary,
            "timestamp": datetime.now(UTC).isoformat(),
        },
    )


@router.websocket("/ws/executions/{execution_id}")
async def websocket_execution(websocket: WebSocket, execution_id: str):
    """WebSocket endpoint for watching a workflow execution.

    Clients connect to receive real-time updates about:
    - Status changes (running, paused, waiting_human, completed, failed)
    - Step completions
    - Human intervention requests
    - Errors

    Args:
        websocket: FastAPI WebSocket connection
        execution_id: ID of the execution to watch
    """
    await websocket.accept()

    # Register connection
    async with _connections_lock:
        _connections[execution_id].add(websocket)

    logger.info(
        f"WebSocket connected for execution: {execution_id}",
        extra={"execution_id": execution_id},
    )

    try:
        # Send initial state
        initial_state = await _get_execution_state(execution_id)
        if initial_state:
            await websocket.send_json({
                "type": "init",
                "execution_id": execution_id,
                **initial_state,
            })
        else:
            await websocket.send_json({
                "type": "error",
                "message": "Execution not found",
            })
            await websocket.close()
            return

        # Keep connection alive and handle incoming messages
        while True:
            try:
                # Wait for client messages (ping/pong, commands)
                data = await asyncio.wait_for(
                    websocket.receive_text(),
                    timeout=30.0,  # 30 second timeout for keepalive
                )

                # Parse and handle message
                try:
                    message = json.loads(data)
                    await _handle_client_message(websocket, execution_id, message)
                except json.JSONDecodeError:
                    await websocket.send_json({
                        "type": "error",
                        "message": "Invalid JSON",
                    })

            except TimeoutError:
                # Send keepalive ping
                try:
                    await websocket.send_json({"type": "ping"})
                except Exception:
                    break

    except WebSocketDisconnect:
        logger.info(
            f"WebSocket disconnected for execution: {execution_id}",
            extra={"execution_id": execution_id},
        )
    except Exception as e:
        logger.error(
            f"WebSocket error for execution {execution_id}: {e!s}",
            extra={"execution_id": execution_id},
        )
    finally:
        # Unregister connection
        async with _connections_lock:
            if execution_id in _connections:
                _connections[execution_id].discard(websocket)
                if not _connections[execution_id]:
                    del _connections[execution_id]


async def _get_execution_state(execution_id: str) -> dict[str, Any] | None:
    """Get the current state of an execution for initial WebSocket message."""
    Sessionmaker = get_sessionmaker()

    with Sessionmaker() as session:
        execution = session.get(WorkflowExecution, execution_id)
        if not execution:
            return None

        # Get recent steps
        steps = session.execute(
            select(ExecutionStep)
            .where(ExecutionStep.execution_id == execution_id)
            .order_by(ExecutionStep.created_at.desc())
            .limit(10)
        ).scalars().all()

        # Get pending intervention
        pending_intervention = None
        if execution.status == "waiting_human":
            intervention = session.execute(
                select(HumanIntervention)
                .where(
                    HumanIntervention.execution_id == execution_id,
                    HumanIntervention.response.is_(None),
                )
            ).scalar()

            if intervention:
                pending_intervention = {
                    "id": intervention.id,
                    "type": intervention.intervention_type,
                    "prompt": intervention.prompt,
                    "options": intervention.options,
                }

        return {
            "status": execution.status,
            "current_node": execution.current_node,
            "started_at": execution.started_at.isoformat() if execution.started_at else None,
            "recent_steps": [
                {
                    "id": s.id,
                    "node_id": s.node_id,
                    "status": s.status,
                    "created_at": s.created_at.isoformat() if s.created_at else None,
                }
                for s in reversed(steps)
            ],
            "pending_intervention": pending_intervention,
        }


async def _handle_client_message(
    websocket: WebSocket,
    execution_id: str,
    message: dict[str, Any],
) -> None:
    """Handle incoming message from WebSocket client."""
    msg_type = message.get("type")

    if msg_type == "pong":
        # Keepalive response, ignore
        pass

    elif msg_type == "refresh":
        # Client requesting state refresh
        state = await _get_execution_state(execution_id)
        if state:
            await websocket.send_json({
                "type": "refresh",
                "execution_id": execution_id,
                **state,
            })

    elif msg_type == "subscribe":
        # Already subscribed by connecting
        await websocket.send_json({
            "type": "subscribed",
            "execution_id": execution_id,
        })

    else:
        await websocket.send_json({
            "type": "error",
            "message": f"Unknown message type: {msg_type}",
        })


def get_connection_count(execution_id: str) -> int:
    """Get the number of active WebSocket connections for an execution."""
    return len(_connections.get(execution_id, set()))


def get_all_connection_counts() -> dict[str, int]:
    """Get connection counts for all active executions."""
    return {eid: len(conns) for eid, conns in _connections.items() if conns}


# ============================================================================
# Playground WebSocket Support
# ============================================================================

# Connection manager for playground sessions
# Maps session_id -> set of WebSocket connections
_playground_connections: dict[str, WeakSet[WebSocket]] = defaultdict(WeakSet)
_playground_connections_lock = asyncio.Lock()


async def broadcast_to_playground_session(session_id: str, message: dict[str, Any]) -> int:
    """Broadcast a message to all clients watching a playground session.

    Args:
        session_id: The playground session ID
        message: Message dict to send

    Returns:
        Number of clients that received the message
    """
    async with _playground_connections_lock:
        connections = _playground_connections.get(session_id, set())
        if not connections:
            return 0

        sent = 0
        dead_connections = []

        for ws in connections:
            try:
                await ws.send_json(message)
                sent += 1
            except Exception:
                dead_connections.append(ws)

        # Clean up dead connections
        for ws in dead_connections:
            connections.discard(ws)

        return sent


async def notify_playground_event(
    session_id: str,
    event_type: str,
    data: dict[str, Any] | None = None,
) -> None:
    """Notify playground clients of an event.

    Args:
        session_id: The playground session ID
        event_type: Type of event (message_start, message_delta, tool_start, etc.)
        data: Event data
    """
    await broadcast_to_playground_session(
        session_id,
        {
            "type": event_type,
            "session_id": session_id,
            "data": data or {},
            "timestamp": datetime.now(UTC).isoformat(),
        },
    )


@router.websocket("/ws/playground/{session_id}")
async def websocket_playground(websocket: WebSocket, session_id: str):
    """WebSocket endpoint for playground session real-time updates.

    Clients connect to receive real-time updates about:
    - Agent typing indicators
    - Tool execution events
    - Message chunks (streaming)
    - State updates
    - Errors

    Message types sent (server -> client):
    - {"type": "message_start", "data": {"agent_id": "..."}}
    - {"type": "message_delta", "data": {"content": "..."}}
    - {"type": "message_end", "data": {"tokens": ..., "cost_usd": ...}}
    - {"type": "tool_start", "data": {"tool": "...", "args": {...}}}
    - {"type": "tool_end", "data": {"tool": "...", "result": "...", "duration_ms": ...}}
    - {"type": "state_update", "data": {"state": {...}}}
    - {"type": "error", "data": {"error": "..."}}

    Args:
        websocket: FastAPI WebSocket connection
        session_id: ID of the playground session to watch
    """
    await websocket.accept()

    # Register connection
    async with _playground_connections_lock:
        _playground_connections[session_id].add(websocket)

    logger.info(
        f"Playground WebSocket connected for session: {session_id}",
        extra={"session_id": session_id},
    )

    try:
        # Send initial connection confirmation
        await websocket.send_json({
            "type": "connected",
            "session_id": session_id,
            "timestamp": datetime.now(UTC).isoformat(),
        })

        # Keep connection alive and handle incoming messages
        while True:
            try:
                # Wait for client messages (ping/pong, commands)
                data = await asyncio.wait_for(
                    websocket.receive_text(),
                    timeout=30.0,  # 30 second timeout for keepalive
                )

                # Parse and handle message
                try:
                    message = json.loads(data)
                    await _handle_playground_client_message(websocket, session_id, message)
                except json.JSONDecodeError:
                    await websocket.send_json({
                        "type": "error",
                        "data": {"error": "Invalid JSON"},
                    })

            except TimeoutError:
                # Send keepalive ping
                try:
                    await websocket.send_json({"type": "ping"})
                except Exception:
                    break

    except WebSocketDisconnect:
        logger.info(
            f"Playground WebSocket disconnected for session: {session_id}",
            extra={"session_id": session_id},
        )
    except Exception as e:
        logger.error(
            f"Playground WebSocket error for session {session_id}: {e!s}",
            extra={"session_id": session_id},
        )
    finally:
        # Unregister connection
        async with _playground_connections_lock:
            if session_id in _playground_connections:
                _playground_connections[session_id].discard(websocket)
                if not _playground_connections[session_id]:
                    del _playground_connections[session_id]


async def _handle_playground_client_message(
    websocket: WebSocket,
    session_id: str,
    message: dict[str, Any],
) -> None:
    """Handle incoming message from playground WebSocket client."""
    msg_type = message.get("type")

    if msg_type == "pong":
        # Keepalive response, ignore
        pass

    elif msg_type == "subscribe":
        # Already subscribed by connecting
        await websocket.send_json({
            "type": "subscribed",
            "session_id": session_id,
        })

    else:
        await websocket.send_json({
            "type": "error",
            "data": {"error": f"Unknown message type: {msg_type}"},
        })


def get_playground_connection_count(session_id: str) -> int:
    """Get the number of active WebSocket connections for a playground session."""
    return len(_playground_connections.get(session_id, set()))


__all__ = [
    "broadcast_to_execution",
    "broadcast_to_playground_session",
    "get_all_connection_counts",
    "get_connection_count",
    "get_playground_connection_count",
    "notify_complete",
    "notify_error",
    "notify_intervention_required",
    "notify_playground_event",
    "notify_status_change",
    "notify_step_complete",
    "router",
]
