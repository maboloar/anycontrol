import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { CameraView } from './CameraView';
import { PatchCables, PatchJack } from './PatchCables';
import { useApp } from '../store';
import type { ObjectInfo } from '../protocol';
const object = vi.hoisted(() => ({ id: 7, name: 'Cup', kind: 'object', state: 'tracking', box: [.2, .2, .5, .5], contour: [] }));
const connect = vi.fn();
vi.mock('../connection', () => ({ connection: { latestState: { objects: [object] }, onFrame: () => () => {} } }));
vi.mock('../api', () => ({ addObject: vi.fn(), reselectObject: vi.fn() }));
vi.mock('./CameraTools', () => ({ CameraTools: () => null }));
vi.mock('./useResizable', () => ({ useResizable: () => ({ style: {}, grip: {} }), ResizeHandle: () => null }));
beforeEach(() => {
  localStorage.clear(); connect.mockReset();
  useApp.setState({ conn: 'open', floatingCamera: true, objects: [object] as unknown as ObjectInfo[], patchDrag: null, patchConnect: connect, selectMode: 'object', reselectId: null });
  vi.stubGlobal('PointerEvent', MouseEvent);
  vi.stubGlobal('requestAnimationFrame', () => 1); vi.stubGlobal('cancelAnimationFrame', () => {});
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(null);
  vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockReturnValue({ left: 0, top: 0, right: 100, bottom: 100, width: 100, height: 100 } as DOMRect);
  HTMLCanvasElement.prototype.setPointerCapture = vi.fn();
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });
const clickVideo = (x = 30, y = 30) => {
  const canvas = screen.getByRole('img', { name: /^카메라 미리보기/ });
  fireEvent.pointerDown(canvas, { button: 0, clientX: x, clientY: y });
  fireEvent.pointerUp(canvas, { button: 0, clientX: x, clientY: y });
};
function View() { return <><CameraView /><PatchCables cables={[]} onCut={() => {}} /><PatchJack side="fn" name="steer" /></>; }
it('keeps a held function cable through window pointer events and connects a video click', () => {
  render(<View />);
  act(() => useApp.getState().setPatchDrag({ from: { kind: 'fn', id: 'steer' }, sticky: true, x: 0, y: 0, startX: 0, startY: 0 }));
  clickVideo(); expect(connect).toHaveBeenCalledExactlyOnceWith('#7', 'steer');
});
it('video-first only selects the object; clicking a function later does not connect it', () => {
  render(<View />); clickVideo();
  expect(useApp.getState().selectedId).toBe(7); expect(useApp.getState().patchDrag).toBeNull();
  fireEvent.pointerDown(screen.getByRole('button', { name: /기능 잭:/ }), { button: 0, clientX: 0, clientY: 0 });
  expect(connect).not.toHaveBeenCalled(); expect(useApp.getState().patchDrag?.from).toEqual({ kind: 'fn', id: 'steer' });
});
it('a background click in cable mode neither registers an object nor loses the held cable', async () => {
  const api = await import('../api');
  render(<View />);
  act(() => useApp.getState().setPatchDrag({ from: { kind: 'fn', id: 'steer' }, sticky: true, x: 0, y: 0, startX: 0, startY: 0 }));
  clickVideo(90, 90); expect(connect).not.toHaveBeenCalled(); expect(api.addObject).not.toHaveBeenCalled();
  expect(useApp.getState().patchDrag?.from.kind).toBe('fn');
});

it('connects from the floating image after resizing and ignores letterbox padding', () => {
  vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockImplementation(function(this: HTMLElement) {
    return this.matches('[data-tour="camera"]') ? new DOMRect(0, -120, 100, 100) : new DOMRect(0, 0, 100, 100);
  });
  render(<View />);
  act(() => useApp.getState().setPatchDrag({ from: { kind: 'fn', id: 'steer' }, sticky: true, x: 0, y: 0, startX: 0, startY: 0 }));
  const floating = screen.getByRole('img', { name: /^실시간 카메라/ });
  fireEvent.pointerDown(floating, { button: 0, clientX: 30, clientY: 10 });
  fireEvent.pointerUp(floating, { button: 0, clientX: 30, clientY: 10 });
  expect(connect).not.toHaveBeenCalled();
  fireEvent.pointerDown(floating, { button: 0, clientX: 30, clientY: 37.5 });
  fireEvent.pointerUp(floating, { button: 0, clientX: 30, clientY: 37.5 });
  expect(connect).toHaveBeenCalledExactlyOnceWith('#7', 'steer');
});
