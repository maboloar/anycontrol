import { beforeEach, expect, it, vi } from 'vitest';
import { connectVideoObject, fittedVideoRect, videoObjectAt } from './videoMapping';
import { toNorm } from './overlay';
import { useApp } from './store';
import type { ObjectInfo } from './protocol';
const object = { id: 7, name: 'Cup', kind: 'object', state: 'tracking', box: [.2, .2, .5, .5], contour: [[.2, .2], [.5, .2], [.2, .5]] } as ObjectInfo;
const connect = vi.fn();
beforeEach(() => { connect.mockReset(); useApp.setState({ objects: [object], selectedId: null, patchDrag: null, patchConnect: connect }); });
const hold = () => useApp.getState().setPatchDrag({ from: { kind: 'fn', id: 'steer' }, x: 0, y: 0, startX: 0, startY: 0, sticky: true });
it('connects a held function cable using the registered card ID', () => {
  hold(); expect(connectVideoObject([.25, .25], [object])?.id).toBe(7);
  expect(connect).toHaveBeenCalledExactlyOnceWith('#7', 'steer');
  expect(useApp.getState().selectedId).toBe(7); expect(useApp.getState().patchDrag).toBeNull();
});
it('does not start a cable from a video object or reverse an object-source cable', () => {
  expect(connectVideoObject([.25, .25], [object])).toBeUndefined();
  useApp.getState().setPatchDrag({ from: { kind: 'obj', name: '#7' }, x: 0, y: 0, startX: 0, startY: 0, sticky: true });
  expect(connectVideoObject([.25, .25], [object])).toBeUndefined(); expect(connect).not.toHaveBeenCalled();
});
it('uses contours rather than empty bounding-box corners and excludes lost objects', () => {
  expect(videoObjectAt([.48, .48], [object])).toBeUndefined();
  expect(videoObjectAt([.25, .25], [{ ...object, kind: 'pen' }])?.id).toBe(7);
  expect(videoObjectAt([.25, .25], [{ ...object, state: 'lost' }])).toBeUndefined();
  expect(videoObjectAt([.25, .25], [{ ...object, contour: [] }])?.id).toBe(7);
});
it('does not connect a stale deleted object or an unknown hand/background target', () => {
  hold(); useApp.setState({ objects: [] });
  expect(connectVideoObject([.25, .25], [object])).toBeUndefined();
  expect(connectVideoObject([.9, .9], [])).toBeUndefined(); expect(connect).not.toHaveBeenCalled();
});
it('resolves mirrored preview coordinates to the same card and last drawn overlapping object', () => {
  const p = toNorm(75, 25, { left: 0, top: 0, width: 100, height: 100 } as DOMRect, true);
  hold(); expect(connectVideoObject(p, [object])?.id).toBe(7);
  expect(videoObjectAt([.25, .25], [object, { ...object, id: 8 }])?.id).toBe(8);
});

it('uses the visible image rectangle when a floating preview has letterboxing', () => {
  const rect = fittedVideoRect(new DOMRect(10, 20, 100, 100), 200, 100);
  expect([rect.left, rect.top, rect.width, rect.height]).toEqual([10, 45, 100, 50]);
  expect(toNorm(35, 70, rect)).toEqual([.25, .5]);
});
