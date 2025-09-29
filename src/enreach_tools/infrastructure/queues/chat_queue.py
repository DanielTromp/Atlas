"""Queue management system for chat API requests to prevent overwhelming OpenAI."""

from __future__ import annotations

import asyncio
import uuid
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any, TypeVar

from enreach_tools.infrastructure.logging import get_logger

logger = get_logger(__name__)

T = TypeVar("T")


class RequestPriority(Enum):
    """Priority levels for chat requests."""
    LOW = 1
    NORMAL = 2
    HIGH = 3
    URGENT = 4


class RequestStatus(Enum):
    """Status of a queued request."""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class QueuedRequest:
    """A request waiting in the chat queue."""
    
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    priority: RequestPriority = RequestPriority.NORMAL
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    started_at: datetime | None = None
    completed_at: datetime | None = None
    status: RequestStatus = RequestStatus.PENDING
    
    # Request details
    session_id: str | None = None
    user_id: str | None = None
    estimated_tokens: int = 0
    
    # Execution
    func: Callable[..., Any] | None = None
    args: tuple[Any, ...] = field(default_factory=tuple)
    kwargs: dict[str, Any] = field(default_factory=dict)
    
    # Results
    result: Any = None
    error: Exception | None = None
    
    # Async coordination
    _future: asyncio.Future[Any] | None = field(default=None, init=False)
    
    def __post_init__(self):
        if self._future is None:
            self._future = asyncio.Future()
    
    @property
    def wait_time_ms(self) -> int:
        """Time spent waiting in queue (milliseconds)."""
        if self.started_at:
            return int((self.started_at - self.created_at).total_seconds() * 1000)
        else:
            return int((datetime.now(UTC) - self.created_at).total_seconds() * 1000)
    
    @property
    def processing_time_ms(self) -> int:
        """Time spent processing (milliseconds)."""
        if self.started_at and self.completed_at:
            return int((self.completed_at - self.started_at).total_seconds() * 1000)
        elif self.started_at:
            return int((datetime.now(UTC) - self.started_at).total_seconds() * 1000)
        else:
            return 0
    
    @property
    def total_time_ms(self) -> int:
        """Total time from creation to completion (milliseconds)."""
        end_time = self.completed_at or datetime.now(UTC)
        return int((end_time - self.created_at).total_seconds() * 1000)
    
    async def wait_for_result(self) -> Any:
        """Wait for the request to complete and return the result."""
        if not self._future:
            raise RuntimeError("Request future not initialized")
        
        return await self._future
    
    def set_result(self, result: Any) -> None:
        """Set the successful result."""
        self.result = result
        self.status = RequestStatus.COMPLETED
        self.completed_at = datetime.now(UTC)
        
        if self._future and not self._future.done():
            self._future.set_result(result)
    
    def set_error(self, error: Exception) -> None:
        """Set an error result."""
        self.error = error
        self.status = RequestStatus.FAILED
        self.completed_at = datetime.now(UTC)
        
        if self._future and not self._future.done():
            self._future.set_exception(error)
    
    def cancel(self) -> None:
        """Cancel the request."""
        self.status = RequestStatus.CANCELLED
        self.completed_at = datetime.now(UTC)
        
        if self._future and not self._future.done():
            self._future.cancel()


class ChatRequestQueue:
    """Queue manager for chat API requests with priority handling."""
    
    def __init__(self, max_concurrent: int = 3, max_queue_size: int = 100):
        self.max_concurrent = max_concurrent
        self.max_queue_size = max_queue_size
        
        # Queue storage by priority
        self._queues: dict[RequestPriority, deque[QueuedRequest]] = {
            priority: deque() for priority in RequestPriority
        }
        
        # Currently processing requests
        self._processing: dict[str, QueuedRequest] = {}
        
        # Completed requests (for metrics)
        self._completed: deque[QueuedRequest] = deque(maxlen=1000)
        
        # Queue management
        self._lock = asyncio.Lock()
        self._processor_task: asyncio.Task[None] | None = None
        self._shutdown = False
        self._pending_tasks: set[asyncio.Task[None]] = set()
        
        # Metrics
        self._total_queued = 0
        self._total_processed = 0
        self._total_failed = 0
    
    async def start(self) -> None:
        """Start the queue processor."""
        if self._processor_task is None or self._processor_task.done():
            self._shutdown = False
            self._processor_task = asyncio.create_task(self._process_queue())
            logger.info("Chat request queue processor started")
    
    async def stop(self) -> None:
        """Stop the queue processor."""
        self._shutdown = True
        if self._processor_task:
            self._processor_task.cancel()
            try:
                await self._processor_task
            except asyncio.CancelledError:
                pass
        for task in list(self._pending_tasks):
            task.cancel()
        for task in list(self._pending_tasks):
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._pending_tasks.clear()
        logger.info("Chat request queue processor stopped")
    
    async def enqueue(
        self,
        func: Callable[..., T],
        *args: Any,
        priority: RequestPriority = RequestPriority.NORMAL,
        session_id: str | None = None,
        user_id: str | None = None,
        estimated_tokens: int = 0,
        **kwargs: Any,
    ) -> QueuedRequest:
        """Add a request to the queue."""
        
        async with self._lock:
            # Check queue size limits
            total_queued = sum(len(q) for q in self._queues.values())
            if total_queued >= self.max_queue_size:
                raise RuntimeError(f"Queue is full (max {self.max_queue_size} requests)")
            
            # Create request
            request = QueuedRequest(
                priority=priority,
                session_id=session_id,
                user_id=user_id,
                estimated_tokens=estimated_tokens,
                func=func,
                args=args,
                kwargs=kwargs,
            )
            
            # Add to appropriate priority queue
            self._queues[priority].append(request)
            self._total_queued += 1
            
            logger.debug(
                "Request queued",
                extra={
                    "event": "chat_request_queued",
                    "request_id": request.id,
                    "priority": priority.name,
                    "session_id": session_id,
                    "user_id": user_id,
                    "estimated_tokens": estimated_tokens,
                    "queue_size": total_queued + 1,
                }
            )
            
            return request
    
    async def _get_next_request(self) -> QueuedRequest | None:
        """Get the next request to process (highest priority first)."""
        async with self._lock:
            # Process in priority order (highest first)
            for priority in sorted(RequestPriority, key=lambda p: p.value, reverse=True):
                queue = self._queues[priority]
                if queue:
                    return queue.popleft()
            return None
    
    async def _process_queue(self) -> None:
        """Main queue processing loop."""
        logger.info("Starting chat request queue processor")
        
        while not self._shutdown:
            try:
                # Check if we can process more requests
                if len(self._processing) >= self.max_concurrent:
                    await asyncio.sleep(0.1)
                    continue
                
                # Get next request
                request = await self._get_next_request()
                if not request:
                    await asyncio.sleep(0.1)
                    continue
                
                # Start processing
                request.status = RequestStatus.PROCESSING
                request.started_at = datetime.now(UTC)
                self._processing[request.id] = request
                
                # Process in background
                task = asyncio.create_task(self._process_request(request))
                self._pending_tasks.add(task)
                task.add_done_callback(self._pending_tasks.discard)
                
            except Exception as exc:
                logger.error(
                    "Error in queue processor",
                    extra={
                        "event": "queue_processor_error",
                        "error": str(exc),
                    }
                )
                await asyncio.sleep(1)
    
    async def _process_request(self, request: QueuedRequest) -> None:
        """Process a single request."""
        
        logger.debug(
            "Processing queued request",
            extra={
                "event": "chat_request_processing",
                "request_id": request.id,
                "wait_time_ms": request.wait_time_ms,
                "session_id": request.session_id,
            }
        )
        
        try:
            # Execute the function
            if not request.func:
                raise RuntimeError("No function to execute")
            
            result = request.func(*request.args, **request.kwargs)
            
            # Handle async functions
            if asyncio.iscoroutine(result):
                result = await result
            
            # Set successful result
            request.set_result(result)
            self._total_processed += 1
            
            logger.debug(
                "Request processed successfully",
                extra={
                    "event": "chat_request_completed",
                    "request_id": request.id,
                    "processing_time_ms": request.processing_time_ms,
                    "total_time_ms": request.total_time_ms,
                }
            )
            
        except Exception as exc:
            # Set error result
            request.set_error(exc)
            self._total_failed += 1
            
            logger.error(
                "Request processing failed",
                extra={
                    "event": "chat_request_failed",
                    "request_id": request.id,
                    "processing_time_ms": request.processing_time_ms,
                    "error": str(exc),
                }
            )
        
        finally:
            # Remove from processing and add to completed
            async with self._lock:
                self._processing.pop(request.id, None)
                self._completed.append(request)
    
    async def get_queue_stats(self) -> dict[str, Any]:
        """Get current queue statistics."""
        async with self._lock:
            total_queued = sum(len(q) for q in self._queues.values())
            
            # Calculate average wait times
            recent_completed = [r for r in self._completed if r.completed_at and 
                             (datetime.now(UTC) - r.completed_at).total_seconds() < 3600]
            
            avg_wait_time = 0
            avg_processing_time = 0
            if recent_completed:
                avg_wait_time = sum(r.wait_time_ms for r in recent_completed) / len(recent_completed)
                avg_processing_time = sum(r.processing_time_ms for r in recent_completed) / len(recent_completed)
            
            return {
                "queue_size": total_queued,
                "processing_count": len(self._processing),
                "max_concurrent": self.max_concurrent,
                "total_queued": self._total_queued,
                "total_processed": self._total_processed,
                "total_failed": self._total_failed,
                "avg_wait_time_ms": int(avg_wait_time),
                "avg_processing_time_ms": int(avg_processing_time),
                "queue_by_priority": {
                    priority.name: len(queue) for priority, queue in self._queues.items()
                },
                "processing_requests": [
                    {
                        "id": req.id,
                        "session_id": req.session_id,
                        "priority": req.priority.name,
                        "processing_time_ms": req.processing_time_ms,
                    }
                    for req in self._processing.values()
                ],
            }
    
    async def cancel_session_requests(self, session_id: str) -> int:
        """Cancel all pending requests for a session."""
        cancelled_count = 0
        
        async with self._lock:
            # Cancel pending requests
            for priority_queue in self._queues.values():
                to_remove = []
                for i, request in enumerate(priority_queue):
                    if request.session_id == session_id and request.status == RequestStatus.PENDING:
                        request.cancel()
                        to_remove.append(i)
                        cancelled_count += 1
                
                # Remove cancelled requests (reverse order to maintain indices)
                for i in reversed(to_remove):
                    del priority_queue[i]
        
        if cancelled_count > 0:
            logger.info(
                f"Cancelled {cancelled_count} pending requests for session",
                extra={
                    "event": "session_requests_cancelled",
                    "session_id": session_id,
                    "cancelled_count": cancelled_count,
                }
            )
        
        return cancelled_count


# Global queue instance
_GLOBAL_QUEUE_STATE: dict[str, ChatRequestQueue | None] = {"instance": None}


async def get_chat_queue() -> ChatRequestQueue:
    """Get the global chat request queue instance."""
    queue = _GLOBAL_QUEUE_STATE.get("instance")
    if queue is None:
        queue = ChatRequestQueue()
        await queue.start()
        _GLOBAL_QUEUE_STATE["instance"] = queue

    return queue


async def queue_chat_request(
    func: Callable[..., T],
    *args: Any,
    priority: RequestPriority = RequestPriority.NORMAL,
    session_id: str | None = None,
    user_id: str | None = None,
    estimated_tokens: int = 0,
    **kwargs: Any,
) -> T:
    """Queue a chat request and wait for the result."""
    
    queue = await get_chat_queue()
    
    request = await queue.enqueue(
        func,
        *args,
        priority=priority,
        session_id=session_id,
        user_id=user_id,
        estimated_tokens=estimated_tokens,
        **kwargs,
    )
    
    # Wait for the result
    return await request.wait_for_result()


__all__ = [
    "ChatRequestQueue",
    "QueuedRequest",
    "RequestPriority",
    "RequestStatus",
    "get_chat_queue",
    "queue_chat_request",
]
