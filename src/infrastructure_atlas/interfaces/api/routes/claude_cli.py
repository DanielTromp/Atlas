"""API routes for Claude CLI integration.

Simple wrapper to call `claude --dangerously-skip-permissions <query>`.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/claude", tags=["claude"])


class ClaudeRequest(BaseModel):
    """Request to run Claude CLI."""

    query: str = Field(..., description="The query/prompt to send to Claude")
    working_dir: str | None = Field(None, description="Working directory for Claude")
    timeout: int = Field(300, description="Timeout in seconds (default 5 minutes)")


class ClaudeResponse(BaseModel):
    """Response from Claude CLI."""

    success: bool
    output: str
    error: str | None = None
    return_code: int


def _get_claude_path() -> str | None:
    """Find the claude executable."""
    return shutil.which("claude")


@router.get("/status")
async def claude_status() -> dict[str, Any]:
    """Check if Claude CLI is available."""
    claude_path = _get_claude_path()
    if not claude_path:
        return {
            "available": False,
            "message": "Claude CLI not found in PATH",
        }

    # Try to get version
    try:
        proc = await asyncio.create_subprocess_exec(
            claude_path,
            "--version",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=10)
        version = stdout.decode().strip() if stdout else "unknown"
        return {
            "available": True,
            "path": claude_path,
            "version": version,
        }
    except Exception as e:
        return {
            "available": True,
            "path": claude_path,
            "version": f"error getting version: {e}",
        }


@router.post("/run", response_model=ClaudeResponse)
async def run_claude(request: ClaudeRequest) -> ClaudeResponse:
    """
    Run Claude CLI with a query.

    Uses --dangerously-skip-permissions to allow autonomous operation.
    """
    claude_path = _get_claude_path()
    if not claude_path:
        raise HTTPException(
            status_code=503,
            detail="Claude CLI not installed or not in PATH",
        )

    # Build command
    cmd = [
        claude_path,
        "--dangerously-skip-permissions",
        "-p",  # Print mode - just output, no interactive
        request.query,
    ]

    logger.info(f"Running Claude CLI: {' '.join(cmd[:3])}...")

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=request.working_dir,
        )

        stdout, stderr = await asyncio.wait_for(
            proc.communicate(),
            timeout=request.timeout,
        )

        output = stdout.decode() if stdout else ""
        error = stderr.decode() if stderr else None

        return ClaudeResponse(
            success=proc.returncode == 0,
            output=output,
            error=error if error else None,
            return_code=proc.returncode or 0,
        )

    except asyncio.TimeoutError:
        raise HTTPException(
            status_code=504,
            detail=f"Claude CLI timed out after {request.timeout} seconds",
        )
    except Exception as e:
        logger.exception("Claude CLI error")
        raise HTTPException(
            status_code=500,
            detail=f"Claude CLI error: {e}",
        )


@router.post("/analyze-suggestion")
async def analyze_suggestion(
    suggestion_id: str,
    create_test: bool = False,
) -> dict[str, Any]:
    """
    Have Claude analyze a suggestion and optionally create a test setup.

    Args:
        suggestion_id: The ID of the suggestion to analyze
        create_test: Whether to also generate test code
    """
    # TODO: Fetch suggestion from database and pass to Claude
    # For now, just return a placeholder

    query = f"Analyze suggestion {suggestion_id}"
    if create_test:
        query += " and create a test setup for it"

    # This will be implemented when we have the suggestion data
    return {
        "status": "not_implemented",
        "message": "Use /claude/run directly for now with your suggestion details",
    }
