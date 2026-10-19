import { expect, it } from 'vitest';
import type { FrameState } from '../protocol';
import { nextMouse, pressedKeys, type VMouse } from './VirtualIoView';

const start: VMouse = { x: 0.5, y: 0.5, left: false, right: false, source: null };

it('uses absolute hand-mouse coordinates and integrates mapping mouse speed', () => {
  const hand = { mouse: { mode: 'hand', x: 0.2, y: 0.8, left: true, right: false } } as unknown as FrameState;
  expect(nextMouse(start, hand, 0.1)).toEqual({ x: 0.2, y: 0.8, left: true, right: false, source: 'hand' });
  const mapped = { mapping: { live: [], computed: { mouse: { move: [1, -1], scroll: 0, left: false, right: true } } } } as unknown as FrameState;
  const m = nextMouse(start, mapped, 0.1);
  expect(m.x).toBeCloseTo(0.56); expect(m.y).toBeCloseTo(0.44); expect(m.right).toBe(true);
});

it('logs only newly pressed keys', () => {
  const s = (keys: string[]) => ({ mapping: { live: [], computed: { keys } } }) as unknown as FrameState;
  expect(pressedKeys([], s(['w']))).toEqual({ down: ['w'], keys: ['w'] });
  expect(pressedKeys(['w'], s(['w', 'd']))).toEqual({ down: ['d'], keys: ['w', 'd'] });
  const sent = { controller: { mode: 'send', keys: ['a'], key_events: [{ type: 'down', key: 'a' }, { type: 'up', key: 'w' }] } } as unknown as FrameState;
  expect(pressedKeys(['w'], sent).down).toEqual(['a']);
});
