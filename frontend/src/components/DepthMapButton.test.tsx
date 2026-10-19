import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { DepthMapButton } from "./CameraTools";
import { getDepthMap, getSceneMap } from "../api";
import { useApp } from "../store";

vi.mock("../api", () => ({ getDepthMap: vi.fn(), getSceneMap: vi.fn() }));

beforeEach(() => { vi.resetAllMocks(); localStorage.clear(); useApp.setState({ devMode: true, depthMapOverlay: false, depthMap: null, depthMapKind: "depth" }); });
afterEach(cleanup);

it("is a developer-only button that turns the depth map overlay on and off", async () => {
  vi.mocked(getDepthMap).mockResolvedValue({ ready: true, ms: 33, overlay: "data:image/png;base64,AA==", image: "data:image/png;base64,AA==" });
  const { rerender } = render(<DepthMapButton />);
  const btn = screen.getByRole("button", { name: "깊이 맵 보기" });
  expect(btn.className).toContain("dev-btn");
  expect(getDepthMap).not.toHaveBeenCalled();                 // 켜기 전에는 서버에 부담을 주지 않는다
  fireEvent.click(btn);
  await waitFor(() => expect(useApp.getState().depthMap?.ready).toBe(true));
  expect(screen.getByRole("button", { name: "깊이 맵 끄기" }).getAttribute("aria-pressed")).toBe("true");
  fireEvent.click(screen.getByRole("button", { name: "깊이 맵 끄기" }));
  expect(useApp.getState().depthMap).toBeNull();
  act(() => useApp.getState().setDevMode(false));
  rerender(<DepthMapButton />);
  expect(screen.queryByRole("button", { name: /깊이 맵/ })).toBeNull();
});

it("clears the overlay when developer mode is turned off", () => {
  useApp.setState({ depthMapOverlay: true, depthMap: { ready: true, overlay: "data:image/png;base64,AA==" } });
  act(() => useApp.getState().setDevMode(false));
  expect(useApp.getState().depthMapOverlay).toBe(false);
  expect(useApp.getState().depthMap).toBeNull();
});

it("can switch to the background-model view and keeps polling that endpoint", async () => {
  vi.mocked(getDepthMap).mockResolvedValue({ ready: true, ms: 33, overlay: "data:image/png;base64,AA==" });
  vi.mocked(getSceneMap).mockResolvedValue({ ready: true, overlay: "data:image/png;base64,BB==", info: { valid: true, changed: 0, shift: [0, 0], gain: 1, depth: true } });
  render(<DepthMapButton />);
  fireEvent.click(screen.getByRole("button", { name: "깊이 맵 보기" }));
  await waitFor(() => expect(getDepthMap).toHaveBeenCalled());
  fireEvent.change(screen.getByRole("combobox", { name: "겹쳐 볼 것" }), { target: { value: "scene" } });
  await waitFor(() => expect(useApp.getState().depthMap?.overlay).toBe("data:image/png;base64,BB=="));
  expect(screen.getByRole("status").textContent).toContain("배경 모델");
  fireEvent.change(screen.getByRole("slider", { name: "겹침 진하기" }), { target: { value: "0.5" } });
  expect(useApp.getState().depthMapOpacity).toBe(0.5);
});
