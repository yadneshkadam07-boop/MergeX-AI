"""Progress events for one analysis, and the bus that delivers them.

The UI watches an analysis over Server-Sent Events. Two properties make that
usable rather than merely present:

**Replay.** Every event is kept in a bounded per-analysis buffer with a
monotonic id. A client that reconnects sends ``Last-Event-ID`` and receives
everything it missed before the live stream resumes, so a dropped connection
mid-analysis does not lose the progress history or leave the stepper frozen.
A client connecting *after* an analysis has finished still gets the whole
story and the terminal event, rather than an empty stream that hangs.

**A guaranteed terminal event.** Success and failure both emit one, so the
client always knows to stop listening. A stream that just goes quiet is
indistinguishable from a slow one.

The bus is in-process, which is correct for a single instance. A multi-replica
deployment needs Redis pub/sub behind the same interface; see CLAUDE.md.
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from collections import defaultdict, deque
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Final

from app.core.logging import get_logger

__all__ = [
    "AnalysisEvent",
    "EventBus",
    "EventStatus",
    "Stage",
    "event_bus",
]

log = get_logger("app.events")

# Enough to replay a whole analysis: a run emits roughly two events per stage
# plus a terminal one.
MAX_BUFFERED_EVENTS: Final[int] = 200
# How long a finished analysis's events stay replayable.
BUFFER_TTL_SECONDS: Final[float] = 3600.0
# Sent periodically so proxies do not close an idle connection.
HEARTBEAT_SECONDS: Final[float] = 15.0


class Stage(StrEnum):
    """The pipeline steps a client renders as a stepper."""

    QUEUED = "queued"
    IMPORTING = "importing"
    STACK = "stack"
    API_CONTRACT = "api"
    SCHEMA = "schema"
    SECURITY = "security"
    SYNTHESIS = "synthesis"
    COMPLETE = "complete"


class EventStatus(StrEnum):
    """What happened to a stage."""

    STARTED = "started"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass(frozen=True, slots=True)
class AnalysisEvent:
    """One progress event."""

    id: int
    analysis_id: str
    stage: Stage
    status: EventStatus
    message: str
    created_at: float
    finding_count: int | None = None
    """Findings produced by this stage, when the stage produces findings."""
    total_findings: int | None = None
    data: dict[str, Any] = field(default_factory=dict)

    @property
    def is_terminal(self) -> bool:
        """True for the last event of a run, whatever the outcome."""
        return self.stage is Stage.COMPLETE

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "id": self.id,
            "analysis_id": self.analysis_id,
            "stage": self.stage.value,
            "status": self.status.value,
            "message": self.message,
            "created_at": self.created_at,
        }
        if self.finding_count is not None:
            payload["finding_count"] = self.finding_count
        if self.total_findings is not None:
            payload["total_findings"] = self.total_findings
        if self.data:
            payload["data"] = self.data
        return payload

    def to_sse(self) -> str:
        """Render as an SSE frame.

        The ``id:`` line is what makes reconnection work: the browser echoes
        the last one back in ``Last-Event-ID``.
        """
        body = json.dumps(self.to_dict(), separators=(",", ":"))
        return f"id: {self.id}\nevent: {self.stage.value}\ndata: {body}\n\n"


@dataclass
class _Channel:
    """Buffered history plus live subscribers for one analysis."""

    events: deque[AnalysisEvent] = field(default_factory=lambda: deque(maxlen=MAX_BUFFERED_EVENTS))
    subscribers: set[asyncio.Queue[AnalysisEvent]] = field(default_factory=set)
    next_id: int = 1
    finished_at: float | None = None


class EventBus:
    """In-process publish/subscribe with replay."""

    def __init__(self) -> None:
        self._channels: dict[str, _Channel] = defaultdict(_Channel)

    def publish(
        self,
        analysis_id: str | uuid.UUID,
        stage: Stage,
        status: EventStatus,
        message: str,
        *,
        finding_count: int | None = None,
        total_findings: int | None = None,
        data: dict[str, Any] | None = None,
    ) -> AnalysisEvent:
        """Record an event and deliver it to live subscribers.

        Synchronous on purpose: publishing must never block or fail the
        analysis that is reporting progress. A subscriber whose queue is full
        is a slow client, and dropping its event is better than stalling the
        run -- it can catch up from the buffer on reconnect.
        """
        key = str(analysis_id)
        channel = self._channels[key]

        event = AnalysisEvent(
            id=channel.next_id,
            analysis_id=key,
            stage=stage,
            status=status,
            message=message,
            created_at=time.time(),
            finding_count=finding_count,
            total_findings=total_findings,
            data=data or {},
        )
        channel.next_id += 1
        channel.events.append(event)

        if event.is_terminal:
            channel.finished_at = event.created_at

        for queue in list(channel.subscribers):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:  # pragma: no cover - slow consumer
                log.warning("event_dropped_for_slow_subscriber", analysis_id=key)

        return event

    def history(self, analysis_id: str | uuid.UUID, *, after_id: int = 0) -> list[AnalysisEvent]:
        """Buffered events with an id greater than ``after_id``."""
        channel = self._channels.get(str(analysis_id))
        if channel is None:
            return []
        return [event for event in channel.events if event.id > after_id]

    def is_finished(self, analysis_id: str | uuid.UUID) -> bool:
        channel = self._channels.get(str(analysis_id))
        return channel is not None and channel.finished_at is not None

    async def subscribe(
        self,
        analysis_id: str | uuid.UUID,
        *,
        after_id: int = 0,
        heartbeat_seconds: float = HEARTBEAT_SECONDS,
    ) -> AsyncGenerator[AnalysisEvent | None, None]:
        """Yield missed events, then live ones, until the run finishes.

        Args:
            after_id: The client's ``Last-Event-ID``. Everything after it is
                replayed before live delivery begins.
            heartbeat_seconds: Yields None at this interval when idle, so the
                caller can emit an SSE comment and keep proxies from closing
                the connection.

        The iterator ends after the terminal event, so a client is never left
        waiting on a stream that will produce nothing more.
        """
        key = str(analysis_id)
        channel = self._channels[key]
        queue: asyncio.Queue[AnalysisEvent] = asyncio.Queue(maxsize=MAX_BUFFERED_EVENTS)

        # Register before replaying, so an event published during replay is
        # queued rather than lost in the gap.
        channel.subscribers.add(queue)
        try:
            replayed_to = after_id
            for event in list(channel.events):
                if event.id > after_id:
                    yield event
                    replayed_to = max(replayed_to, event.id)
                    if event.is_terminal:
                        return

            while True:
                if queue.empty() and channel.finished_at is not None:
                    # The run has ended and everything it published has been
                    # delivered. Checking the queue first matters: an analysis
                    # that finishes between the replay above and this loop has
                    # events sitting in the queue, and returning here would
                    # drop them -- the terminal event among them.
                    return

                try:
                    event = await asyncio.wait_for(queue.get(), timeout=heartbeat_seconds)
                except TimeoutError:
                    yield None
                    continue

                if event.id <= replayed_to:
                    # Published during replay and already delivered.
                    continue
                replayed_to = event.id
                yield event
                if event.is_terminal:
                    return
        finally:
            channel.subscribers.discard(queue)

    def prune(self, *, now: float | None = None) -> int:
        """Drop buffers for analyses that finished long ago.

        Without this a long-lived process accumulates one buffer per analysis
        forever.
        """
        current = now if now is not None else time.time()
        stale = [
            key
            for key, channel in self._channels.items()
            if channel.finished_at is not None
            and not channel.subscribers
            and current - channel.finished_at > BUFFER_TTL_SECONDS
        ]
        for key in stale:
            del self._channels[key]
        if stale:
            log.debug("event_buffers_pruned", count=len(stale))
        return len(stale)

    def reset(self) -> None:
        """Forget everything. Used by tests."""
        self._channels.clear()


# The process-wide bus. A single instance is correct here; a multi-replica
# deployment must replace this with Redis pub/sub behind the same interface,
# or a client will connect to a replica that never saw the analysis.
event_bus = EventBus()
