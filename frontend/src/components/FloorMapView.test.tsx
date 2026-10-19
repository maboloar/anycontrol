import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { FloorMapView } from "./FloorMapView";
import { ObjectPanel } from "./ObjectPanel";
import { getFloorMap } from "../api";
import { useApp } from "../store";
import type { FloorMapData, ObjectInfo } from "../protocol";

vi.mock("../api", () => ({
  getFloorMap: vi.fn(), getTracking: vi.fn(() => Promise.resolve(null)), putTracking: vi.fn(), deleteObject: vi.fn(),
  setNeutral: vi.fn(), pickCandidate: vi.fn(), renameObject: vi.fn(), getObjectMemory: vi.fn(), getObjectThumbnail: vi.fn(() => Promise.resolve({ id: 1, image: null })),
}));
const base = { id: 1, name: "펜 1", kind: "pen", color: "#f80", state: "tracking", confidence: .9,
  axes: { x: 0, y: 0, depth: 0, angle: 0, stretch: 0, contact: 0 }, texture: .5, contrast: .5, warnings: [], candidates: 1,
  candidate_index: 0, box: null, contour: [], debug: {} } as ObjectInfo;
const ready: FloorMapData = { ready: true, size: [1280, 720], k: 2.9, c: -480, a: 40, sigma: 0.12, samples: 220, anchors: 3, roll_deg: 1.8,
  image: "data:image/png;base64,AA==", overlay: "data:image/png;base64,AA==", tip: [0.25, 0.8], hover: 0.05, contact: true };

beforeEach(() => {
  vi.resetAllMocks();
  localStorage.clear();
  vi.mocked(getFloorMap).mockResolvedValue(ready);
  useApp.setState({ devMode: true, floorMapOpen: false, floorOverlay: false, floorMap: null, previewMirror: false, objects: [base], selectedId: 1, conn: "closed" });
});
afterEach(cleanup);

it("shows the floor gradient button only for pens in developer mode, styled like the other dev buttons", async () => {
  const { rerender } = render(<ObjectPanel />);
  const btn = await screen.findByRole("button", { name: "바닥 그라데이션 맵 보기" });
  expect(btn.className).toContain("dev-btn");
  act(() => useApp.setState({ objects: [{ ...base, kind: "object" }] }));
  rerender(<ObjectPanel />);
  expect(screen.queryByRole("button", { name: /바닥/ })).toBeNull();
  act(() => useApp.setState({ objects: [base] }));
  rerender(<ObjectPanel />);
  act(() => useApp.getState().setDevMode(false));
  expect(screen.queryByRole("button", { name: /바닥/ })).toBeNull();
});

it("opens the map, polls it, draws the tip marker, and toggles the camera overlay", async () => {
  render(<ObjectPanel />);
  fireEvent.click(await screen.findByRole("button", { name: "바닥 그라데이션 맵 보기" }));
  expect(await screen.findByRole("img", { name: /바닥 맵/ })).toBeTruthy();
  expect(getFloorMap).toHaveBeenCalledWith(1);
  expect(screen.getByText(/좌우 기울기 1.8°/)).toBeTruthy();
  expect(screen.getByText(/터치 보정 3점/)).toBeTruthy();
  const tip = document.querySelector(".floor-tip") as HTMLElement;
  expect(tip.className).toContain("on");                       // 접촉 중
  expect(tip.style.left).toBe("25%");
  const box = screen.getByRole("checkbox", { name: /카메라 영상 위에 겹쳐 보기/ });
  fireEvent.click(box);
  expect(useApp.getState().floorOverlay).toBe(true);
  fireEvent.click(screen.getByRole("button", { name: "바닥 맵 닫기" }));
  expect(useApp.getState().floorOverlay).toBe(false);          // 닫으면 겹침도 꺼진다
  expect(useApp.getState().floorMap).toBeNull();
});

it("mirrors the marker and image when the preview is mirrored", async () => {
  useApp.setState({ previewMirror: true });
  render(<FloorMapView id={1} />);
  await screen.findByRole("img", { name: /바닥 맵/ });
  expect((document.querySelector(".floor-tip") as HTMLElement).style.left).toBe("75%");
  expect((screen.getByRole("img", { name: /바닥 맵/ }) as HTMLImageElement).style.transform).toBe("scaleX(-1)");
});

it.each([
  ["contact_method", /접촉 판정 \(실험\)’을 켜면/],
  ["learning", /책상 면 학습 중/],
])("explains why there is no map yet (%s)", async (reason, text) => {
  vi.mocked(getFloorMap).mockResolvedValue({ ready: false, reason } as FloorMapData);
  render(<FloorMapView id={1} />);
  expect(await screen.findByText(text)).toBeTruthy();
  expect(screen.getByRole("checkbox", { name: /겹쳐 보기/ }).hasAttribute("disabled")).toBe(true);
});

it("turning developer mode off closes the map and clears the overlay", () => {
  useApp.setState({ floorMapOpen: true, floorOverlay: true, floorMap: ready });
  act(() => useApp.getState().setDevMode(false));
  const s = useApp.getState();
  expect([s.floorMapOpen, s.floorOverlay, s.floorMap]).toEqual([false, false, null]);
});
