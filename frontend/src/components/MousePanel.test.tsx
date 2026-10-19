import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MousePanel } from "./MousePanel";
import { putMouse, resetDepthReference } from "../api";
import { useApp } from "../store";
import type { MouseInfo, MouseSettings, ObjectInfo } from "../protocol";

vi.mock("../api", () => ({ getMouse: vi.fn(), putMouse: vi.fn(), putTracking: vi.fn(), stopAll: vi.fn(), resetDepthReference: vi.fn() }));

const obj = { id: 1, name: "마우스", kind: "object", color: "#88f", state: "tracking", confidence: .9,
  axes: {}, texture: .5, contrast: .5, warnings: [], candidates: 1, candidate_index: 0, box: null, contour: [], debug: {} } as unknown as ObjectInfo;
const settings = { mode: "object", object_id: 1, coordinate_mode: "depth", depth_source: "model", depth_model_range: 3, depth_perspective: true,
  desk_correct: true, hand_region: [.2, .15, .8, .75], object_region: [.1, .1, .9, .9], sens_x: 1, sens_y: 1, smoothing: 1,
  depth_sensitivity: 1.5, depth_gain: 1.4, hand_clicks: true, hand_click_style: "finger", finger_press: .6, finger_track: true, tip_refine: true, tip_drop: .22,
  object_tap_distance: .25, object_hybrid: false, hybrid_detach: .25, hand_control: "depth", pinch_on: .3, invert_y: false, invert_scroll: false,
  touch_sensitivity: 1.5, touch_height: -.2, touch_margin: .025, touch_depth_blend: 1, touch_deadzone: .004, scroll_gain: 20,
  pen_sensitivity: 1.5, pen_depth_blend: 1, pen_relative: true, mirror: false, anchor_cursor: true } as unknown as MouseSettings;
const info = (available: boolean): MouseInfo => ({ settings, status: {}, hands_available: true, hands_running: false, hands_error: null, depth_model_available: available });

beforeEach(() => { vi.resetAllMocks(); useApp.setState({ conn: "closed", objects: [obj], mouseInfo: info(true), devMode: true }); });
afterEach(cleanup);

it("uses object size by default and only shows the depth sensitivity after picking the depth model", async () => {
  useApp.setState({ mouseInfo: { ...info(true), settings: { ...settings, depth_source: "size" } } });
  vi.mocked(putMouse).mockResolvedValue({ ...info(true), settings: { ...settings, depth_source: "model" } });
  render(<MousePanel />);
  const select = screen.getByLabelText(/앞뒤\(깊이\) 신호/) as HTMLSelectElement;
  expect(select.value).toBe("size");                           // 기본은 예전 방식(물체 크기)
  expect(screen.queryByLabelText(/깊이 감도/)).toBeNull();
  fireEvent.change(select, { target: { value: "model" } });
  await waitFor(() => expect(putMouse).toHaveBeenCalledWith(expect.objectContaining({ depth_source: "model" })));
});

it("raises the sensitivity range and retakes the depth reference on request", async () => {
  vi.mocked(putMouse).mockResolvedValue(info(true));
  vi.mocked(resetDepthReference).mockResolvedValue(info(true));
  render(<MousePanel />);
  fireEvent.change(screen.getByLabelText(/깊이 감도/), { target: { value: "6" } });
  await waitFor(() => expect(putMouse).toHaveBeenCalledWith(expect.objectContaining({ depth_model_range: 6 })));
  fireEvent.click(screen.getByRole("button", { name: "깊이 기준 다시 잡기" }));
  await waitFor(() => expect(resetDepthReference).toHaveBeenCalledTimes(1));
});

it("tells the user when the model is missing and size is used instead", () => {
  useApp.setState({ mouseInfo: info(false) });
  render(<MousePanel />);
  expect(screen.getAllByText(/모델 없음|모델이 없어/).length).toBeGreaterThan(0);
});

it("lets the user turn the floor-anchor cursor off (on by default) and says what it does", async () => {
  useApp.setState({ mouseInfo: { ...info(true), settings: { ...settings, depth_source: "size" } } });
  vi.mocked(putMouse).mockResolvedValue({ ...info(true), settings: { ...settings, anchor_cursor: false } });
  render(<MousePanel />);
  const box = screen.getByRole("checkbox", { name: /바닥 기준점으로 커서 움직이기/ }) as HTMLInputElement;
  expect(box.checked).toBe(true);
  fireEvent.click(box);
  await waitFor(() => expect(putMouse).toHaveBeenCalledWith(expect.objectContaining({ anchor_cursor: false })));
});

it('has no one-hand hybrid mode and turns an old saved hybrid setting off', async () => {
  const put = vi.mocked(putMouse).mockImplementation(async (next: Partial<MouseSettings>) => ({ ...useApp.getState().mouseInfo!, settings: next as MouseSettings }) as MouseInfo);
  useApp.setState({ mouseInfo: { ...useApp.getState().mouseInfo!, settings: { ...settings, object_hybrid: true } } });
  render(<MousePanel />);
  expect(screen.queryByRole('radio', { name: '한 손 하이브리드' })).toBeNull();
  expect(screen.getAllByRole('radio').map((r) => r.textContent)).toEqual(['끄기', '맨손 마우스', '물체 마우스']);
  await waitFor(() => expect(put).toHaveBeenCalledWith(expect.objectContaining({ object_hybrid: false })));
});

it('keeps only the simple settings in basic mode', () => {
  useApp.setState({ devMode: false });
  render(<MousePanel />);
  expect(screen.getByLabelText('커서로 쓸 물체')).toBeTruthy();
  expect(screen.queryByRole('checkbox', { name: /손으로 클릭하기/ })).toBeNull();   // 물체 마우스는 손 추적 없음
  expect(screen.queryByLabelText(/앞뒤\(깊이\) 신호/)).toBeNull();
  expect(screen.queryByLabelText(/손 인식 엔진/)).toBeNull();
  expect(screen.queryByText(/검지·중지 끝점 직접 추적/)).toBeNull();
  expect(screen.queryByText(/가장자리 사선 보정/)).toBeNull();
});

it('object mouse has no hand-tracking controls at all (no hand click, sensitivity or contact distance)', () => {
  useApp.setState({ devMode: true });
  render(<MousePanel />);
  expect(screen.queryByText(/검지·중지 끝점 직접 추적/)).toBeNull();
  expect(screen.queryByLabelText(/내려야 하는 거리/)).toBeNull();
  expect(screen.queryByLabelText(/클릭 민감도/)).toBeNull();
  expect(screen.queryByLabelText(/물체 접촉 거리/)).toBeNull();
});

it('lets the hand mouse pick the click style and shows its sensitivity only for the finger style', () => {
  useApp.setState({ mouseInfo: { ...useApp.getState().mouseInfo!, settings: { ...settings, mode: 'hand', hand_click_style: 'finger' } } });
  const { rerender } = render(<MousePanel />);
  expect((screen.getByLabelText('클릭 방식') as HTMLSelectElement).value).toBe('finger');
  expect(screen.getByLabelText(/클릭 민감도/)).toBeTruthy();
  useApp.setState({ mouseInfo: { ...useApp.getState().mouseInfo!, settings: { ...settings, mode: 'hand', hand_click_style: 'pinch' } } });
  rerender(<MousePanel />);
  expect(screen.queryByLabelText(/클릭 민감도/)).toBeNull();
  expect(screen.getByLabelText(/집기 민감도/)).toBeTruthy();
});
