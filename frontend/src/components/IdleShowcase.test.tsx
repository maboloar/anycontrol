import { hideGuidePrompt, useGuidePrompt } from "../guidePrompt";
import { resetAllSettings } from "../resetSettings";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { IdleShowcase, liveActivity } from "./IdleShowcase";
import { getPresence } from "../api";
import { useApp } from "../store";

vi.mock("../resetSettings", () => ({ resetAllSettings: vi.fn().mockResolvedValue(undefined) }));
vi.mock("../api", () => ({ getPresence: vi.fn() }));
beforeEach(() => { vi.useFakeTimers(); hideGuidePrompt(); vi.mocked(resetAllSettings).mockClear(); useApp.setState({ idleShowcase: true, idleSeconds: 120 }); vi.mocked(getPresence).mockResolvedValue({ ready: true, present: false }); });
afterEach(() => { cleanup(); vi.useRealTimers(); });

it("darkens with the placeholder after 120 s without input and closes on mouse movement", async () => {
  render(<IdleShowcase />);
  await act(async () => { await vi.advanceTimersByTimeAsync(119_000); });
  expect(screen.queryByText("시연영상placeholder")).toBeNull();
  await act(async () => { await vi.advanceTimersByTimeAsync(2_000); });
  expect(screen.getByText("시연영상placeholder")).toBeTruthy();
  expect(resetAllSettings).toHaveBeenCalledTimes(1);
  expect(getPresence).toHaveBeenCalledWith(true);                 // 뜬 순간의 장면을 배경으로
  await act(async () => { fireEvent.pointerMove(window); await Promise.resolve(); });
  expect(useGuidePrompt.getState()).toMatchObject({ visible: true, returning: true });
  expect(screen.queryByText("시연영상placeholder")).toBeNull();
});

it("closes when the camera sees a person come close", async () => {
  render(<IdleShowcase />);
  await act(async () => { await vi.advanceTimersByTimeAsync(121_000); });
  expect(screen.getByText("시연영상placeholder")).toBeTruthy();
  vi.mocked(getPresence).mockResolvedValue({ ready: true, present: true, near: 0.3 });
  await act(async () => { await vi.advanceTimersByTimeAsync(800); });
  expect(screen.queryByText("시연영상placeholder")).toBeNull();
  expect(useGuidePrompt.getState().visible).toBe(true);
});

it("never shows when turned off in advanced mode", async () => {
  useApp.setState({ idleShowcase: false });
  render(<IdleShowcase />);
  await act(async () => { await vi.advanceTimersByTimeAsync(120_000); });
  expect(screen.queryByText("시연영상placeholder")).toBeNull();
});

it("counts camera input (cursor movement, mapping values) as activity", () => {
  const base = { mouse: { mode: "object", cursor_active: true, x: 0.5, y: 0.5 }, pens: {}, mapping: null, controller: null } as never;
  expect(liveActivity(base, { ...(base as object), mouse: { mode: "object", cursor_active: true, x: 0.55, y: 0.5 } } as never)).toBe(true);
  expect(liveActivity(base, base)).toBe(false);
});
