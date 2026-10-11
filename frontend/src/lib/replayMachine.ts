/**
 * Replay player state machine: loading → ready → playing ⇄ paused, seeking, completed, error.
 * Pure: the player component turns timers and API results into events.
 */
export type ReplayState =
  | { status: "loading" }
  | { status: "ready" }
  | { status: "playing" }
  | { status: "paused" }
  | { status: "seeking"; resume: boolean }
  | { status: "completed" }
  | { status: "error"; message: string };

export type ReplayEvent =
  | { type: "LOADED"; completed: boolean }
  | { type: "PLAY" }
  | { type: "PAUSE" }
  | { type: "STEP_DONE"; completed: boolean }
  | { type: "SEEK" }
  | { type: "SEEK_DONE"; completed: boolean }
  | { type: "FAIL"; message: string }
  | { type: "RETRY" };

export const initialReplayState: ReplayState = { status: "loading" };

export function replayReducer(s: ReplayState, e: ReplayEvent): ReplayState {
  if (e.type === "FAIL") return s.status === "error" ? s : { status: "error", message: e.message };
  switch (s.status) {
    case "loading":
      return e.type === "LOADED" ? { status: e.completed ? "completed" : "ready" } : s;
    case "ready":
    case "paused":
      if (e.type === "PLAY") return { status: "playing" };
      if (e.type === "SEEK") return { status: "seeking", resume: false };
      if (e.type === "STEP_DONE") return e.completed ? { status: "completed" } : { status: "paused" };
      return s;
    case "playing":
      if (e.type === "PAUSE") return { status: "paused" };
      if (e.type === "SEEK") return { status: "seeking", resume: true };
      if (e.type === "STEP_DONE" && e.completed) return { status: "completed" };
      return s;
    case "seeking":
      if (e.type === "SEEK_DONE") return { status: e.completed ? "completed" : s.resume ? "playing" : "paused" };
      return s;
    case "completed":
      return e.type === "SEEK" ? { status: "seeking", resume: false } : s;
    case "error":
      return e.type === "RETRY" ? { status: "loading" } : s;
  }
}

export const SPEEDS = [1, 2, 4, 8, 16];

/** Bars per second → timer interval and bars per tick. At most four requests a second, whatever the speed. */
export function tickPlan(speed: number): { intervalMs: number; steps: number } {
  const intervalMs = Math.max(250, Math.round(1000 / speed));
  return { intervalMs, steps: Math.max(1, Math.round((speed * intervalMs) / 1000)) };
}
