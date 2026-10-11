import { describe, expect, it } from "vitest";
import { initialReplayState, replayReducer as r, tickPlan, type ReplayEvent, type ReplayState } from "./replayMachine";

const run = (events: ReplayEvent[], s: ReplayState = initialReplayState) => events.reduce(r, s);

describe("replay state machine", () => {
  it("loads, plays, pauses and completes", () => {
    expect(run([{ type: "LOADED", completed: false }]).status).toBe("ready");
    expect(run([{ type: "LOADED", completed: false }, { type: "PLAY" }]).status).toBe("playing");
    expect(run([{ type: "LOADED", completed: false }, { type: "PLAY" }, { type: "PAUSE" }]).status).toBe("paused");
    expect(run([{ type: "LOADED", completed: false }, { type: "PLAY" }, { type: "STEP_DONE", completed: false }]).status).toBe("playing");
    expect(run([{ type: "LOADED", completed: false }, { type: "PLAY" }, { type: "STEP_DONE", completed: true }]).status).toBe("completed");
  });

  it("resumes a saved session that already finished as completed", () => {
    expect(run([{ type: "LOADED", completed: true }]).status).toBe("completed");
  });

  it("seeking returns to playing only when it interrupted playback", () => {
    const playing = run([{ type: "LOADED", completed: false }, { type: "PLAY" }]);
    expect(run([{ type: "SEEK" }], playing)).toEqual({ status: "seeking", resume: true });
    expect(run([{ type: "SEEK" }, { type: "SEEK_DONE", completed: false }], playing).status).toBe("playing");
    const paused = run([{ type: "PAUSE" }], playing);
    expect(run([{ type: "SEEK" }, { type: "SEEK_DONE", completed: false }], paused).status).toBe("paused");
    expect(run([{ type: "SEEK" }, { type: "SEEK_DONE", completed: true }], paused).status).toBe("completed");
  });

  it("ignores play while seeking or loading, and allows seeking back after completion", () => {
    expect(run([{ type: "PLAY" }]).status).toBe("loading");
    const seeking = run([{ type: "LOADED", completed: false }, { type: "SEEK" }]);
    expect(run([{ type: "PLAY" }], seeking).status).toBe("seeking");
    const done = run([{ type: "LOADED", completed: true }]);
    expect(run([{ type: "PLAY" }], done).status).toBe("completed");
    expect(run([{ type: "SEEK" }, { type: "SEEK_DONE", completed: false }], done).status).toBe("paused");
  });

  it("a step while paused stays paused", () => {
    expect(run([{ type: "LOADED", completed: false }, { type: "STEP_DONE", completed: false }]).status).toBe("paused");
  });

  it("errors from any state and retries through loading", () => {
    const err = run([{ type: "LOADED", completed: false }, { type: "PLAY" }, { type: "FAIL", message: "offline" }]);
    expect(err).toEqual({ status: "error", message: "offline" });
    expect(run([{ type: "PLAY" }], err).status).toBe("error");
    expect(run([{ type: "RETRY" }], err).status).toBe("loading");
  });

  it("caps request rate at four ticks a second", () => {
    expect(tickPlan(1)).toEqual({ intervalMs: 1000, steps: 1 });
    expect(tickPlan(4)).toEqual({ intervalMs: 250, steps: 1 });
    expect(tickPlan(16)).toEqual({ intervalMs: 250, steps: 4 });
  });
});
