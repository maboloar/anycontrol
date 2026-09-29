import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { DrawingPad } from "./DrawingPad";
import { clearHandDrawing, putHandDrawing, getAutoCalibration } from "../api";
import { connection } from "../connection";
import { mapHandStrokes, type Stroke } from "../drawing";
import type { FrameState, HandDrawingState, ObjectInfo, PenState } from "../protocol";
import { useApp } from "../store";

vi.mock("../api", () => ({ penAction: vi.fn(), putHandDrawing: vi.fn(), clearHandDrawing: vi.fn(), getAutoCalibration: vi.fn() }));
vi.mock("../connection", () => ({ connection: { onMessage: vi.fn() } }));

const listeners = new Set<(type: string, data: Record<string, unknown>) => void>();
const ctx = {
  fillRect: vi.fn(), beginPath: vi.fn(), moveTo: vi.fn(), lineTo: vi.fn(), stroke: vi.fn(),
  arc: vi.fn(), fill: vi.fn(), fillText: vi.fn(), fillStyle: "", strokeStyle: "", lineWidth: 0, lineCap: "", lineJoin: "",
};
const info = { enabled: true, hands_available: true, hands_error: null };

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  vi.mocked(getAutoCalibration).mockResolvedValue(null);
  listeners.clear();
  vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(ctx as unknown as CanvasRenderingContext2D);
  vi.mocked(connection.onMessage).mockImplementation((fn) => {
    listeners.add(fn);
    return () => { listeners.delete(fn); };
  });
  vi.mocked(putHandDrawing).mockResolvedValue(info);
  vi.mocked(clearHandDrawing).mockResolvedValue(info);
  useApp.setState({ conn: "open", objects: [], live: { mouse: null, pens: {}, mapping: null, controller: null, handDrawing: null } });
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

function state(patch: Partial<HandDrawingState>) {
  const drawing: HandDrawingState = { enabled: true, hand_visible: true, contact: false,
    point: null, pinch_index: .1, current: null, stroke_count: 0, events: [], ...patch };
  const frame: FrameState = { seq: 1, size: [640, 400], objects: [], hand_drawing: drawing };
  act(() => {
    useApp.getState().setLive({ ...useApp.getState().live, handDrawing: drawing });
    listeners.forEach((fn) => fn("state", frame as unknown as Record<string, unknown>));
  });
}

it("lets the user draw without registering a pen and stops tracking on mode exit", async () => {
  render(<DrawingPad />);
  expect(putHandDrawing).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "맨손 검지" }));
  await waitFor(() => expect(putHandDrawing).toHaveBeenCalledWith(true));
  expect(screen.getByRole("img", { name: "검지로 그린 그림" })).toBeTruthy();
  state({ contact: true, point: [.2, .3], current: [[.2, .3]] });
  expect(screen.getByText("맞댐 (그리는 중)")).toBeTruthy();
  state({ contact: false, point: [.2, .3] });
  expect(screen.getByText("떼어 있음")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: /^펜$/ }));
  await waitFor(() => expect(putHandDrawing).toHaveBeenLastCalledWith(false));
});

it("keeps released strokes and starts another stroke without joining the gap", async () => {
  render(<DrawingPad />);
  fireEvent.click(screen.getByRole("button", { name: "맨손 검지" }));
  await waitFor(() => expect(putHandDrawing).toHaveBeenCalledWith(true));
  fireEvent.click(screen.getByRole('checkbox', { name: '펜촉·검지 위치 십자 표시' }));
  const first: Stroke = [[.2, .3], [.3, .3]];
  state({ contact: true, point: [.3, .3], current: first });
  state({ events: [{ type: "up", stroke: first }] });
  ctx.lineTo.mockClear();
  state({ contact: true, point: [.7, .7], current: [[.7, .7]], events: [{ type: "down" }] });
  const [mapped] = mapHandStrokes([first], 640, 400, 24, 1.6);
  expect(ctx.lineTo.mock.calls).toEqual([mapped![1]]); // 새 위치는 점으로 표시하며 이전 획에서 연결하지 않는다.
  ctx.lineTo.mockClear();
  fireEvent.click(screen.getByRole("button", { name: "지우기" }));
  await waitFor(() => expect(clearHandDrawing).toHaveBeenCalledOnce());
  await waitFor(() => expect(ctx.lineTo).not.toHaveBeenCalled());
});

it("disables hand drawing on emergency stop and unmount", async () => {
  const view = render(<DrawingPad />);
  fireEvent.click(screen.getByRole("button", { name: "맨손 검지" }));
  await waitFor(() => expect(putHandDrawing).toHaveBeenCalledWith(true));
  act(() => { window.dispatchEvent(new Event("anycontrol-stop")); });
  expect((screen.getByRole("checkbox", { name: "맨손 그리기 활성화" }) as HTMLInputElement).checked).toBe(false);
  await waitFor(() => expect(putHandDrawing).toHaveBeenLastCalledWith(false));
  fireEvent.click(screen.getByRole("checkbox", { name: "맨손 그리기 활성화" }));
  await waitFor(() => expect(putHandDrawing).toHaveBeenLastCalledWith(true));
  view.unmount();
  expect(putHandDrawing).toHaveBeenLastCalledWith(false);
});

it("shows hand model errors in the hand drawing panel", async () => {
  vi.mocked(putHandDrawing).mockRejectedValueOnce(new Error("409 손 인식 모델이 없습니다"));
  render(<DrawingPad />);
  fireEvent.click(screen.getByRole("button", { name: "맨손 검지" }));
  await waitFor(() => expect(screen.getByRole("alert").textContent).toBe("손 인식 모델이 없습니다"));
});


it('shows the hovering pen in stroke coordinates, toggles it, and clears a lost tip', async () => {
  useApp.setState({ objects: [{ id: 1, kind: 'pen', name: '펜' } as ObjectInfo], autoCalibration: null });
  render(<DrawingPad />);
  await screen.findByRole('img', { name: '펜으로 그린 그림' });
  const emit = (point: [number, number] | null, uncertain = false) => act(() => {
    listeners.forEach(fn => fn('state', { seq: 2, size: [640, 400], objects: [], pens: {
      '1': { tip: [320, 300], draw_point: point, uncertain, contact: false, current: null, events: [] } as unknown as PenState,
    } }));
  });
  ctx.lineTo.mockClear(); emit([.2, .7]);
  expect(ctx.lineTo).toHaveBeenCalledTimes(2);
  const before = ctx.lineTo.mock.calls[0]![0] as number;
  ctx.lineTo.mockClear(); emit([.3, .7]);
  expect(ctx.lineTo.mock.calls[0]![0]).toBeGreaterThan(before);
  fireEvent.click(screen.getByRole('checkbox', { name: '펜촉·검지 위치 십자 표시' }));
  ctx.lineTo.mockClear(); emit([.4, .7]);
  expect(ctx.lineTo).not.toHaveBeenCalled();
  expect(localStorage.getItem('anycontrol.drawing.crosshair')).toBe('off');
  fireEvent.click(screen.getByRole('checkbox', { name: '펜촉·검지 위치 십자 표시' }));
  ctx.lineTo.mockClear(); emit(null, true);
  expect(ctx.lineTo).not.toHaveBeenCalled();
});
