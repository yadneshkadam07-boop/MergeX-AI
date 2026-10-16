"""The progress event bus.

The interesting behaviour is all about a client that is not listening at the
moment something happens: one that reconnects mid-analysis, one that connects
after the run already finished, and one that connects to an analysis that has
just started. Each must end up with the full story and a terminal event,
because a stream that simply goes quiet is indistinguishable from a slow one.
"""

from __future__ import annotations

import asyncio
import json
import uuid

import pytest

from app.core.events import (
    BUFFER_TTL_SECONDS,
    MAX_BUFFERED_EVENTS,
    AnalysisEvent,
    EventBus,
    EventStatus,
    Stage,
)

pytestmark = pytest.mark.anyio

ANALYSIS = "11111111-1111-1111-1111-111111111111"


@pytest.fixture
def bus() -> EventBus:
    return EventBus()


def run_through(bus: EventBus, analysis_id: str = ANALYSIS, *, fail: bool = False) -> None:
    """Publish the event sequence of a complete analysis."""
    bus.publish(analysis_id, Stage.QUEUED, EventStatus.STARTED, "Queued.")
    bus.publish(analysis_id, Stage.IMPORTING, EventStatus.STARTED, "Cloning.")
    bus.publish(analysis_id, Stage.IMPORTING, EventStatus.COMPLETED, "Cloned.")
    bus.publish(analysis_id, Stage.STACK, EventStatus.COMPLETED, "React + FastAPI.")
    for stage in (Stage.API_CONTRACT, Stage.SCHEMA, Stage.SECURITY):
        bus.publish(analysis_id, stage, EventStatus.STARTED, f"{stage.value} started.")
        bus.publish(
            analysis_id,
            stage,
            EventStatus.COMPLETED,
            f"{stage.value} done.",
            finding_count=2,
        )
    bus.publish(analysis_id, Stage.SYNTHESIS, EventStatus.COMPLETED, "Scored.")
    if fail:
        bus.publish(analysis_id, Stage.COMPLETE, EventStatus.FAILED, "Clone failed.")
    else:
        bus.publish(analysis_id, Stage.COMPLETE, EventStatus.COMPLETED, "Done.", total_findings=6)


async def drain(
    bus: EventBus, analysis_id: str = ANALYSIS, *, after_id: int = 0
) -> list[AnalysisEvent]:
    """Collect a subscription to its end, ignoring heartbeats."""
    collected: list[AnalysisEvent] = []
    async for event in bus.subscribe(analysis_id, after_id=after_id, heartbeat_seconds=5.0):
        if event is not None:
            collected.append(event)
    return collected


class TestEventShape:
    def test_ids_are_monotonic_per_analysis(self, bus: EventBus) -> None:
        run_through(bus)

        ids = [event.id for event in bus.history(ANALYSIS)]

        assert ids == list(range(1, len(ids) + 1))

    def test_ids_are_independent_between_analyses(self, bus: EventBus) -> None:
        bus.publish("a", Stage.STACK, EventStatus.STARTED, "a")
        bus.publish("b", Stage.STACK, EventStatus.STARTED, "b")

        assert bus.history("a")[0].id == 1
        assert bus.history("b")[0].id == 1

    def test_a_uuid_and_its_string_are_the_same_channel(self, bus: EventBus) -> None:
        identifier = uuid.uuid4()
        bus.publish(identifier, Stage.STACK, EventStatus.STARTED, "x")

        assert len(bus.history(str(identifier))) == 1

    def test_the_sse_frame_carries_an_id_and_an_event_name(self, bus: EventBus) -> None:
        event = bus.publish(
            ANALYSIS,
            Stage.API_CONTRACT,
            EventStatus.COMPLETED,
            "4 issues.",
            finding_count=4,
            total_findings=9,
        )

        frame = event.to_sse()

        assert frame.startswith(f"id: {event.id}\n")
        assert "event: api\n" in frame
        assert frame.endswith("\n\n")
        body = json.loads(frame.split("data: ", 1)[1])
        assert body["stage"] == "api"
        assert body["status"] == "completed"
        assert body["finding_count"] == 4
        assert body["total_findings"] == 9

    def test_absent_counts_are_omitted_rather_than_null(self, bus: EventBus) -> None:
        event = bus.publish(ANALYSIS, Stage.STACK, EventStatus.STARTED, "Detecting.")

        body = json.loads(event.to_sse().split("data: ", 1)[1])

        assert "finding_count" not in body
        assert "total_findings" not in body

    def test_the_payload_is_json_serialisable(self, bus: EventBus) -> None:
        event = bus.publish(
            ANALYSIS,
            Stage.STACK,
            EventStatus.COMPLETED,
            "Detected.",
            data={"frontend": "react", "backend": "fastapi"},
        )

        assert json.loads(event.to_sse().split("data: ", 1)[1])["data"]["backend"] == "fastapi"

    def test_only_complete_is_terminal(self, bus: EventBus) -> None:
        run_through(bus)

        terminal = [event for event in bus.history(ANALYSIS) if event.is_terminal]

        assert len(terminal) == 1
        assert terminal[0].stage is Stage.COMPLETE

    def test_every_pipeline_stage_is_streamed(self, bus: EventBus) -> None:
        """The requirement names these five stages explicitly."""
        run_through(bus)

        streamed = {event.stage for event in bus.history(ANALYSIS)}

        assert {
            Stage.STACK,
            Stage.API_CONTRACT,
            Stage.SCHEMA,
            Stage.SECURITY,
            Stage.SYNTHESIS,
        } <= streamed


class TestHistory:
    def test_an_unknown_analysis_has_no_history(self, bus: EventBus) -> None:
        assert bus.history("nope") == []

    def test_asking_an_unknown_analysis_does_not_create_a_channel(self, bus: EventBus) -> None:
        """A 404 probe must not leak a buffer per request."""
        bus.history("nope")
        bus.is_finished("nope")

        assert bus.prune(now=0.0) == 0
        assert bus._channels == {}

    def test_after_id_filters(self, bus: EventBus) -> None:
        run_through(bus)

        assert [event.id for event in bus.history(ANALYSIS, after_id=9)] == [10, 11, 12]

    def test_after_the_last_id_is_empty(self, bus: EventBus) -> None:
        run_through(bus)
        last = bus.history(ANALYSIS)[-1].id

        assert bus.history(ANALYSIS, after_id=last) == []

    def test_the_buffer_is_bounded(self, bus: EventBus) -> None:
        for index in range(MAX_BUFFERED_EVENTS + 50):
            bus.publish(ANALYSIS, Stage.STACK, EventStatus.STARTED, str(index))

        history = bus.history(ANALYSIS)

        assert len(history) == MAX_BUFFERED_EVENTS
        assert history[-1].message == str(MAX_BUFFERED_EVENTS + 49)


class TestSubscribe:
    async def test_a_late_client_receives_the_whole_run(self, bus: EventBus) -> None:
        """Connecting after the analysis finished still tells the full story."""
        run_through(bus)

        collected = await drain(bus)

        assert len(collected) == 12
        assert collected[-1].is_terminal

    async def test_a_late_client_is_not_left_hanging(self, bus: EventBus) -> None:
        """The iterator must end rather than wait for events that never come."""
        run_through(bus)

        collected = await asyncio.wait_for(drain(bus), timeout=1.0)

        assert collected[-1].stage is Stage.COMPLETE

    async def test_a_live_client_receives_events_as_they_happen(self, bus: EventBus) -> None:
        received: list[AnalysisEvent] = []

        async def listen() -> None:
            async for event in bus.subscribe(ANALYSIS, heartbeat_seconds=5.0):
                if event is not None:
                    received.append(event)

        task = asyncio.create_task(listen())
        await asyncio.sleep(0)  # let the subscriber register
        run_through(bus)
        await asyncio.wait_for(task, timeout=2.0)

        assert [event.stage for event in received][-1] is Stage.COMPLETE
        assert len(received) == 12

    async def test_a_reconnecting_client_gets_exactly_what_it_missed(self, bus: EventBus) -> None:
        """The reconnection requirement, end to end."""
        bus.publish(ANALYSIS, Stage.QUEUED, EventStatus.STARTED, "Queued.")
        bus.publish(ANALYSIS, Stage.IMPORTING, EventStatus.STARTED, "Cloning.")
        first_connection = await asyncio.wait_for(collect_until_quiet(bus, after_id=0), timeout=2.0)
        last_seen = first_connection[-1].id

        # The analysis continues while the client is away.
        bus.publish(ANALYSIS, Stage.STACK, EventStatus.COMPLETED, "React + FastAPI.")
        bus.publish(
            ANALYSIS, Stage.API_CONTRACT, EventStatus.COMPLETED, "2 issues.", finding_count=2
        )
        bus.publish(ANALYSIS, Stage.COMPLETE, EventStatus.COMPLETED, "Done.")

        resumed = await asyncio.wait_for(drain(bus, after_id=last_seen), timeout=2.0)

        assert [event.id for event in resumed] == [3, 4, 5]
        assert resumed[-1].is_terminal
        # Nothing is delivered twice.
        assert {event.id for event in first_connection}.isdisjoint({event.id for event in resumed})

    async def test_a_reconnection_after_the_end_still_terminates(self, bus: EventBus) -> None:
        run_through(bus)

        resumed = await asyncio.wait_for(drain(bus, after_id=10), timeout=1.0)

        assert [event.id for event in resumed] == [11, 12]

    async def test_an_event_published_during_replay_is_not_lost(self, bus: EventBus) -> None:
        """The subscriber registers before replaying, closing the race."""
        bus.publish(ANALYSIS, Stage.QUEUED, EventStatus.STARTED, "Queued.")
        received: list[AnalysisEvent] = []

        iterator = bus.subscribe(ANALYSIS, heartbeat_seconds=5.0)
        received.append(await anext(iterator))  # type: ignore[arg-type]
        # Published while the consumer is between yields.
        bus.publish(ANALYSIS, Stage.STACK, EventStatus.COMPLETED, "Detected.")
        bus.publish(ANALYSIS, Stage.COMPLETE, EventStatus.COMPLETED, "Done.")

        async for event in iterator:
            if event is not None:
                received.append(event)

        assert [event.id for event in received] == [1, 2, 3]

    async def test_a_heartbeat_is_yielded_when_idle(self, bus: EventBus) -> None:
        """Without this a proxy closes a quiet connection mid-analysis."""
        bus.publish(ANALYSIS, Stage.QUEUED, EventStatus.STARTED, "Queued.")
        heartbeats = 0

        async for event in bus.subscribe(ANALYSIS, heartbeat_seconds=0.01):
            if event is None:
                heartbeats += 1
                if heartbeats == 2:
                    bus.publish(ANALYSIS, Stage.COMPLETE, EventStatus.COMPLETED, "Done.")

        assert heartbeats == 2

    async def test_a_failed_run_emits_a_terminal_event_too(self, bus: EventBus) -> None:
        """Failure must not look like a stream that merely stopped."""
        run_through(bus, fail=True)

        collected = await asyncio.wait_for(drain(bus), timeout=1.0)

        assert collected[-1].is_terminal
        assert collected[-1].status is EventStatus.FAILED

    async def test_two_clients_both_receive_everything(self, bus: EventBus) -> None:
        async def listen() -> list[AnalysisEvent]:
            events: list[AnalysisEvent] = []
            async for event in bus.subscribe(ANALYSIS, heartbeat_seconds=5.0):
                if event is not None:
                    events.append(event)
            return events

        first = asyncio.create_task(listen())
        second = asyncio.create_task(listen())
        await asyncio.sleep(0)
        run_through(bus)
        results = await asyncio.wait_for(asyncio.gather(first, second), timeout=2.0)

        assert [event.id for event in results[0]] == [event.id for event in results[1]]
        assert len(results[0]) == 12

    async def test_a_subscriber_is_deregistered_when_it_leaves(self, bus: EventBus) -> None:
        run_through(bus)

        await drain(bus)

        assert bus._channels[ANALYSIS].subscribers == set()

    async def test_events_for_another_analysis_are_not_delivered(self, bus: EventBus) -> None:
        other = "22222222-2222-2222-2222-222222222222"
        run_through(bus, other)
        run_through(bus)

        collected = await drain(bus)

        assert all(event.analysis_id == ANALYSIS for event in collected)


async def collect_until_quiet(bus: EventBus, *, after_id: int = 0) -> list[AnalysisEvent]:
    """Read the buffered events, then disconnect on the first heartbeat.

    This is what a browser tab being closed mid-analysis looks like from the
    bus's point of view.
    """
    collected: list[AnalysisEvent] = []
    async for event in bus.subscribe(ANALYSIS, after_id=after_id, heartbeat_seconds=0.01):
        if event is None:
            break
        collected.append(event)
    return collected


class TestFinishedAndPrune:
    def test_a_run_is_not_finished_until_the_terminal_event(self, bus: EventBus) -> None:
        bus.publish(ANALYSIS, Stage.SYNTHESIS, EventStatus.COMPLETED, "Scored.")

        assert bus.is_finished(ANALYSIS) is False

    def test_the_terminal_event_marks_it_finished(self, bus: EventBus) -> None:
        run_through(bus)

        assert bus.is_finished(ANALYSIS) is True

    def test_a_failed_run_is_also_finished(self, bus: EventBus) -> None:
        run_through(bus, fail=True)

        assert bus.is_finished(ANALYSIS) is True

    def test_an_unknown_analysis_is_not_finished(self, bus: EventBus) -> None:
        assert bus.is_finished("nope") is False

    def test_a_stale_buffer_is_pruned(self, bus: EventBus) -> None:
        run_through(bus)
        later = bus._channels[ANALYSIS].finished_at or 0.0

        pruned = bus.prune(now=later + BUFFER_TTL_SECONDS + 1)

        assert pruned == 1
        assert bus.history(ANALYSIS) == []

    def test_a_recent_buffer_is_kept(self, bus: EventBus) -> None:
        """A client may still reconnect to an analysis that just finished."""
        run_through(bus)

        assert bus.prune() == 0
        assert len(bus.history(ANALYSIS)) == 12

    def test_a_running_analysis_is_never_pruned(self, bus: EventBus) -> None:
        bus.publish(ANALYSIS, Stage.STACK, EventStatus.STARTED, "Detecting.")

        assert bus.prune(now=1e12) == 0

    async def test_a_buffer_with_a_listener_is_not_pruned(self, bus: EventBus) -> None:
        """Pruning under a live subscriber would silently truncate its stream."""
        bus.publish(ANALYSIS, Stage.QUEUED, EventStatus.STARTED, "Queued.")
        bus.publish(ANALYSIS, Stage.COMPLETE, EventStatus.COMPLETED, "Done.")
        iterator = bus.subscribe(ANALYSIS, heartbeat_seconds=5.0)
        await anext(iterator)

        pruned = bus.prune(now=1e12)
        await iterator.aclose()

        assert pruned == 0

    def test_reset_clears_everything(self, bus: EventBus) -> None:
        run_through(bus)

        bus.reset()

        assert bus.history(ANALYSIS) == []
        assert bus.is_finished(ANALYSIS) is False
