import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { AnalysisEvent, Stage } from "@/api/events";
import type { EventSourceLike } from "@/hooks/use-analysis-stream";
import { useAnalysisStream } from "@/hooks/use-analysis-stream";

/**
 * A controllable stand-in for `EventSource`.
 *
 * jsdom has no `EventSource`, which is convenient: the hook takes a factory,
 * so these tests drive the stream frame by frame and can simulate a drop at
 * any point rather than hoping to catch one.
 */
class FakeEventSource implements EventSourceLike {
  static instances: FakeEventSource[] = [];

  readonly url: string;
  readonly listeners = new Map<string, ((event: MessageEvent) => void)[]>();
  onopen: ((event: Event) => void) | null = null;
  onerror: ((event: Event) => void) | null = null;
  closed = false;

  constructor(url: string) {
    this.url = url;
    FakeEventSource.instances.push(this);
  }

  addEventListener(type: string, listener: (event: MessageEvent) => void): void {
    const existing = this.listeners.get(type) ?? [];
    this.listeners.set(type, [...existing, listener]);
  }

  close(): void {
    this.closed = true;
  }

  open(): void {
    act(() => this.onopen?.(new Event("open")));
  }

  /** Deliver one server event on its named channel, as the backend does. */
  emit(event: AnalysisEvent): void {
    const listeners = this.listeners.get(event.stage) ?? [];
    act(() => {
      for (const listener of listeners) {
        listener({ data: JSON.stringify(event) } as MessageEvent);
      }
    });
  }

  emitRaw(type: string, data: string): void {
    const listeners = this.listeners.get(type) ?? [];
    act(() => {
      for (const listener of listeners) {
        listener({ data } as MessageEvent);
      }
    });
  }

  /** Simulate the connection dropping. */
  fail(): void {
    act(() => this.onerror?.(new Event("error")));
  }

  get lastEventIdParam(): number {
    const value = new URL(this.url, "http://localhost").searchParams.get("last_event_id");
    return value === null ? 0 : Number(value);
  }
}

const factory = (url: string): EventSourceLike => new FakeEventSource(url);

function event(overrides: Partial<AnalysisEvent> & { id: number; stage: Stage }): AnalysisEvent {
  return {
    analysis_id: "a-1",
    status: "completed",
    message: "",
    created_at: 0,
    ...overrides,
  };
}

const latest = () =>
  FakeEventSource.instances[FakeEventSource.instances.length - 1] as FakeEventSource;

function render(options: Parameters<typeof useAnalysisStream>[1] = {}) {
  return renderHook(() => useAnalysisStream("a-1", { factory, retryDelays: [10, 20], ...options }));
}

beforeEach(() => {
  FakeEventSource.instances = [];
  vi.useRealTimers();
});

describe("connecting", () => {
  it("opens a stream for the analysis", () => {
    const { result } = render();

    expect(FakeEventSource.instances).toHaveLength(1);
    expect(latest().url).toContain("/api/v1/analyses/a-1/events");
    expect(result.current.connection).toBe("connecting");
  });

  it("asks for no replay on a first connection", () => {
    render();

    expect(latest().url).not.toContain("last_event_id");
  });

  it("reports an open connection", () => {
    const { result } = render();

    latest().open();

    expect(result.current.connection).toBe("open");
  });

  it("does not connect when disabled", () => {
    renderHook(() => useAnalysisStream("a-1", { factory, enabled: false }));

    expect(FakeEventSource.instances).toHaveLength(0);
  });

  it("does not connect without an analysis id", () => {
    renderHook(() => useAnalysisStream(undefined, { factory }));

    expect(FakeEventSource.instances).toHaveLength(0);
  });

  it("closes the stream when the component unmounts", () => {
    const { unmount } = render();
    const source = latest();

    unmount();

    expect(source.closed).toBe(true);
  });
});

describe("receiving events", () => {
  it("collects events in order", () => {
    const { result } = render();
    latest().open();

    latest().emit(event({ id: 1, stage: "queued", status: "started", message: "Queued." }));
    latest().emit(event({ id: 2, stage: "stack", message: "React + FastAPI" }));

    expect(result.current.events.map((item) => item.id)).toEqual([1, 2]);
  });

  it("tracks the latest state per stage", () => {
    const { result } = render();

    latest().emit(event({ id: 1, stage: "api", status: "started", message: "Running" }));
    latest().emit(
      event({ id: 2, stage: "api", status: "completed", message: "Done", finding_count: 5 }),
    );

    expect(result.current.stages.api).toEqual({
      stage: "api",
      status: "completed",
      message: "Done",
      findingCount: 5,
    });
  });

  it("records a skipped stage as skipped", () => {
    const { result } = render();

    latest().emit(event({ id: 1, stage: "schema", status: "skipped", message: "No migrations" }));

    expect(result.current.stages.schema?.status).toBe("skipped");
  });

  it("takes the running total from the server", () => {
    const { result } = render();

    latest().emit(event({ id: 1, stage: "api", finding_count: 3, total_findings: 3 }));
    latest().emit(event({ id: 2, stage: "security", finding_count: 4, total_findings: 7 }));

    expect(result.current.totalFindings).toBe(7);
  });

  it("ignores a frame it cannot parse", () => {
    const { result } = render();

    latest().emitRaw("stack", "not json");

    expect(result.current.events).toHaveLength(0);
    expect(result.current.connection).not.toBe("error");
  });

  it("ignores an event it has already seen", () => {
    const { result } = render();

    latest().emit(event({ id: 1, stage: "stack" }));
    latest().emit(event({ id: 1, stage: "stack" }));

    expect(result.current.events).toHaveLength(1);
  });
});

describe("the terminal event", () => {
  it("marks the run finished and closes the stream", () => {
    const { result } = render();
    const source = latest();

    source.emit(event({ id: 1, stage: "complete", message: "Done.", total_findings: 5 }));

    expect(result.current.isFinished).toBe(true);
    expect(result.current.isFailed).toBe(false);
    expect(result.current.connection).toBe("closed");
    expect(source.closed).toBe(true);
  });

  it("reports a failed run as failed, not as a dropped connection", () => {
    const { result } = render();

    latest().emit(
      event({ id: 1, stage: "complete", status: "failed", message: "Repository not found." }),
    );

    expect(result.current.isFinished).toBe(true);
    expect(result.current.isFailed).toBe(true);
    expect(result.current.terminal?.message).toBe("Repository not found.");
  });

  it("does not reconnect after the run has finished", async () => {
    render();
    const source = latest();

    source.emit(event({ id: 1, stage: "complete" }));
    source.fail(); // the browser fires `error` when the server closes

    await new Promise((resolve) => setTimeout(resolve, 60));
    expect(FakeEventSource.instances).toHaveLength(1);
  });
});

describe("reconnecting", () => {
  it("resumes from the last event it saw", async () => {
    const { result } = render();
    latest().open();
    latest().emit(event({ id: 1, stage: "queued", status: "started" }));
    latest().emit(event({ id: 2, stage: "importing" }));
    latest().emit(event({ id: 3, stage: "stack" }));

    latest().fail();

    await waitFor(() => expect(FakeEventSource.instances).toHaveLength(2));
    // The whole point: the server is told where to resume, so the stepper
    // does not replay from the beginning and jump backwards.
    expect(latest().lastEventIdParam).toBe(3);
    expect(result.current.events).toHaveLength(3);
  });

  it("keeps the events it already had", async () => {
    const { result } = render();
    latest().emit(event({ id: 1, stage: "api", finding_count: 2, total_findings: 2 }));

    latest().fail();
    await waitFor(() => expect(FakeEventSource.instances).toHaveLength(2));
    latest().open();
    latest().emit(event({ id: 2, stage: "security", finding_count: 1, total_findings: 3 }));

    expect(result.current.events.map((item) => item.id)).toEqual([1, 2]);
    expect(result.current.totalFindings).toBe(3);
    expect(result.current.stages.api?.findingCount).toBe(2);
  });

  it("reports that it is reconnecting", async () => {
    const { result } = render();
    latest().open();

    latest().fail();

    await waitFor(() => expect(result.current.connection).toBe("reconnecting"));
    expect(result.current.reconnectAttempts).toBe(1);
  });

  it("clears the attempt count once reconnected", async () => {
    const { result } = render();
    latest().fail();

    await waitFor(() => expect(FakeEventSource.instances).toHaveLength(2));
    latest().open();

    expect(result.current.reconnectAttempts).toBe(0);
    expect(result.current.connection).toBe("open");
  });

  it("gives up after the configured attempts rather than looping forever", async () => {
    const { result } = render({ retryDelays: [5] });

    latest().fail();
    await waitFor(() => expect(FakeEventSource.instances).toHaveLength(2));
    latest().fail();

    await waitFor(() => expect(result.current.connection).toBe("error"));
    expect(FakeEventSource.instances).toHaveLength(2);
  });

  it("can be retried by hand after giving up", async () => {
    const { result } = render({ retryDelays: [5] });
    latest().fail();
    await waitFor(() => expect(FakeEventSource.instances).toHaveLength(2));
    latest().fail();
    await waitFor(() => expect(result.current.connection).toBe("error"));

    act(() => result.current.reconnect());

    await waitFor(() => expect(FakeEventSource.instances).toHaveLength(3));
    expect(latest().lastEventIdParam).toBe(0);
  });

  it("does not deliver a replayed event twice", async () => {
    const { result } = render();
    latest().emit(event({ id: 1, stage: "stack" }));
    latest().emit(event({ id: 2, stage: "api" }));

    latest().fail();
    await waitFor(() => expect(FakeEventSource.instances).toHaveLength(2));
    // A server that over-replays must not corrupt the view.
    latest().emit(event({ id: 2, stage: "api" }));
    latest().emit(event({ id: 3, stage: "schema" }));

    expect(result.current.events.map((item) => item.id)).toEqual([1, 2, 3]);
  });
});
