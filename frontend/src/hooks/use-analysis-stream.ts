import { useCallback, useEffect, useRef, useState } from "react";

import type { AnalysisEvent, EventStatus, Stage } from "@/api/events";
import { STAGES, eventStreamUrl, isTerminal } from "@/api/events";

/**
 * How the connection is doing, as opposed to how the analysis is doing.
 *
 * These are deliberately separate: a dropped connection is not a failed
 * analysis, and showing "analysis failed" because a laptop slept would be a
 * lie about the backend.
 */
export type ConnectionStatus = "idle" | "connecting" | "open" | "reconnecting" | "closed" | "error";

export interface StageState {
  stage: Stage;
  status: EventStatus;
  message: string;
  findingCount: number | null;
}

export interface AnalysisStream {
  events: AnalysisEvent[];
  /** Latest state per stage, for the stepper. */
  stages: Partial<Record<Stage, StageState>>;
  /** Running total reported by the backend, not counted client-side. */
  totalFindings: number;
  connection: ConnectionStatus;
  /** The terminal event, once it arrives. Present on success *and* failure. */
  terminal: AnalysisEvent | null;
  isFinished: boolean;
  /** True when the terminal event says the run failed. */
  isFailed: boolean;
  reconnectAttempts: number;
  lastEventId: number;
  /** Reconnect now, for a "retry" button after the attempts are exhausted. */
  reconnect: () => void;
}

/** Anything `EventSource`-shaped. Injected so tests need no real network. */
export interface EventSourceLike {
  addEventListener(type: string, listener: (event: MessageEvent) => void): void;
  close(): void;
  onopen: ((event: Event) => void) | null;
  onerror: ((event: Event) => void) | null;
}

export type EventSourceFactory = (url: string) => EventSourceLike;

export interface UseAnalysisStreamOptions {
  enabled?: boolean;
  /** Defaults to the global `EventSource`. */
  factory?: EventSourceFactory;
  /** Backoff schedule in milliseconds. One entry per attempt. */
  retryDelays?: number[];
}

/**
 * Exponential-ish backoff, capped. Reconnecting instantly in a tight loop
 * against a backend that is down is how a browser tab melts a laptop.
 */
const DEFAULT_RETRY_DELAYS = [500, 1_000, 2_000, 5_000, 10_000];

function defaultFactory(url: string): EventSourceLike {
  return new EventSource(url);
}

/**
 * Subscribe to one analysis's progress stream.
 *
 * Reconnection is the reason this is a hook rather than three lines in a
 * component. `EventSource` reconnects on its own, but it reconnects to the
 * *original* URL, so a run that progressed while the tab was offline would
 * replay from the beginning and the stepper would jump backwards. This
 * closes the source itself and reopens it with `last_event_id`, so the
 * server sends exactly what was missed and nothing twice.
 *
 * The stream is closed as soon as the terminal event arrives: the run is
 * over and an open connection would hold a server-side subscriber forever.
 */
export function useAnalysisStream(
  analysisId: string | undefined,
  options: UseAnalysisStreamOptions = {},
): AnalysisStream {
  const { enabled = true, factory = defaultFactory, retryDelays = DEFAULT_RETRY_DELAYS } = options;

  const [events, setEvents] = useState<AnalysisEvent[]>([]);
  const [stages, setStages] = useState<Partial<Record<Stage, StageState>>>({});
  const [totalFindings, setTotalFindings] = useState(0);
  const [connection, setConnection] = useState<ConnectionStatus>("idle");
  const [terminal, setTerminal] = useState<AnalysisEvent | null>(null);
  const [reconnectAttempts, setReconnectAttempts] = useState(0);

  // Held in refs and kept out of the effect's dependencies on purpose. A
  // caller that writes `useAnalysisStream(id, { retryDelays: [...] })`
  // creates a new array every render; if the effect depended on it, every
  // render would tear down a working connection and open another.
  const factoryRef = useRef(factory);
  factoryRef.current = factory;
  const retryDelaysRef = useRef(retryDelays);
  retryDelaysRef.current = retryDelays;

  // Refs, not state: these are read inside callbacks that must not be
  // re-created on every event, and writing them must not re-render.
  const lastEventIdRef = useRef(0);
  const sourceRef = useRef<EventSourceLike | null>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const attemptRef = useRef(0);
  const finishedRef = useRef(false);
  const [manualRetry, setManualRetry] = useState(0);

  const cleanUp = useCallback(() => {
    if (timerRef.current !== null) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
    sourceRef.current?.close();
    sourceRef.current = null;
  }, []);

  const reconnect = useCallback(() => {
    attemptRef.current = 0;
    setReconnectAttempts(0);
    setManualRetry((value) => value + 1);
  }, []);

  useEffect(() => {
    if (!analysisId || !enabled) return;

    // A remount (or a manual retry) resumes rather than restarts: the ids
    // already seen are not requested again.
    finishedRef.current = false;
    let disposed = false;

    const connect = () => {
      if (disposed || finishedRef.current) return;

      setConnection(attemptRef.current === 0 ? "connecting" : "reconnecting");
      const source = factoryRef.current(eventStreamUrl(analysisId, lastEventIdRef.current));
      sourceRef.current = source;

      source.onopen = () => {
        if (disposed) return;
        attemptRef.current = 0;
        setReconnectAttempts(0);
        setConnection("open");
      };

      source.onerror = () => {
        if (disposed || finishedRef.current) return;
        // The browser fires `error` both for a failed connection and for a
        // stream the server closed. Either way this source is finished with.
        sourceRef.current?.close();
        sourceRef.current = null;

        const delay = retryDelaysRef.current[attemptRef.current];
        if (delay === undefined) {
          setConnection("error");
          return;
        }
        attemptRef.current += 1;
        setReconnectAttempts(attemptRef.current);
        setConnection("reconnecting");
        timerRef.current = setTimeout(connect, delay);
      };

      const handle = (raw: MessageEvent) => {
        if (disposed) return;
        let event: AnalysisEvent;
        try {
          event = JSON.parse(raw.data as string) as AnalysisEvent;
        } catch {
          // A frame we cannot parse is not worth tearing the stream down for.
          return;
        }

        // Guard against a replay overlapping what we already have.
        if (event.id <= lastEventIdRef.current) return;
        lastEventIdRef.current = event.id;

        setEvents((current) => [...current, event]);
        setStages((current) => ({
          ...current,
          [event.stage]: {
            stage: event.stage,
            status: event.status,
            message: event.message,
            findingCount: event.finding_count ?? null,
          },
        }));
        if (typeof event.total_findings === "number") {
          setTotalFindings(event.total_findings);
        }

        if (isTerminal(event)) {
          finishedRef.current = true;
          setTerminal(event);
          setConnection("closed");
          cleanUp();
        }
      };

      for (const stage of STAGES) {
        source.addEventListener(stage, handle);
      }
      // Servers and proxies may emit unnamed frames; accept those too.
      source.addEventListener("message", handle);
    };

    connect();

    return () => {
      disposed = true;
      cleanUp();
    };
  }, [analysisId, enabled, cleanUp, manualRetry]);

  return {
    events,
    stages,
    totalFindings,
    connection,
    terminal,
    isFinished: terminal !== null,
    isFailed: terminal?.status === "failed",
    reconnectAttempts,
    lastEventId: lastEventIdRef.current,
    reconnect,
  };
}
