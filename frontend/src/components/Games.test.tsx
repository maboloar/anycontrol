import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { RacingDemo } from './RacingDemo';
import { SurvivalDemo } from './SurvivalDemo';
import { PongDemo } from './PongDemo';
import { HockeyDemo } from "./HockeyDemo";
import { FruitDemo } from './FruitDemo';
import { useApp } from '../store';
import { useDraftStore } from "../mappingDraft";
import { sensitivity } from '../mappingSensitivity';
import { buildGameMapping } from "../gameMapping";
import type { ObjectInfo, Profile } from "../protocol";
import { ZERO } from './GamepadView';
import { useGameSession } from "./gameSession";
import { Profiler } from 'react';
const listeners = vi.hoisted(() => new Set<(type: string, data: Record<string, unknown>) => void>());
vi.mock('../connection', () => ({ connection: { onMessage: (fn: (type: string, data: Record<string, unknown>) => void) => { listeners.add(fn); return () => listeners.delete(fn); } } }));
vi.mock('../api', () => ({
  getMapping: vi.fn(async () => ({ profile: useDraftStore.getState().draft, mode: 'observe', warnings: [] })),
  putMapping: vi.fn(async (profile: Profile) => ({ profile, mode: 'observe', warnings: [] })),
}));
const fillRect = vi.fn();
const ctx = new Proxy({}, { get: (_t, key) => key === 'fillRect' ? fillRect : key === 'createLinearGradient' || key === 'createRadialGradient' ? vi.fn(() => ({ addColorStop: vi.fn() })) : vi.fn(), set: () => true });
let tick: FrameRequestCallback | undefined;
let now = 0;
beforeEach(() => {
  now = 1000; tick = undefined; localStorage.clear(); fillRect.mockClear(); useDraftStore.getState().setErr(null);
  vi.spyOn(performance, 'now').mockImplementation(() => now);
  const objects = [{ id: 1, name: 'A', kind: 'object', color: '#f00', state: 'tracking', box: [.2, .3, .4, .5] }, { id: 2, name: 'B', kind: 'object', color: '#0f0', state: 'tracking', box: [.6, .3, .8, .5] }] as ObjectInfo[];
  useApp.setState({ conn: 'closed', objects, handInputEnabled: true });
  let p: Profile = { version: 1, name: 'test', description: '', mappings: [] };
  for (const game of ['race', 'pong', 'fruit', 'survival', 'hockey'] as const) p = buildGameMapping(p, game, game === 'survival' ? 1 : 2, game === 'race' ? 'x' : 'depth', ['#1', '#2']);
  useDraftStore.getState().set(p);
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(ctx as CanvasRenderingContext2D);
  vi.spyOn(HTMLElement.prototype, 'getClientRects').mockReturnValue([{}] as unknown as DOMRectList);
  vi.stubGlobal('requestAnimationFrame', (fn: FrameRequestCallback) => { tick = fn; return 1; });
  vi.stubGlobal('cancelAnimationFrame', () => { tick = undefined; });
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });
const frames = (n: number) => act(() => { for (let i = 0; i < n; i++) { now += 50; const next = tick; tick = undefined; next?.(now); } });
it('racing supports keyboard play, pause, restart and a retained high score without a camera', () => {
  render(<RacingDemo />);
  fireEvent.click(screen.getByRole('button', { name: '주행 시작 / 계속' }));
  const stage = screen.getByLabelText('레이싱 조작 영역');
  fireEvent.keyDown(stage, { key: 'w' }); frames(60); fireEvent.keyUp(stage, { key: 'w' });
  const best = Number(localStorage.getItem('anycontrol.race.best'));
  expect(best).toBeGreaterThan(0);
  fireEvent.keyDown(stage, { key: 'p' });
  const finalBest = Number(localStorage.getItem('anycontrol.race.best'));
  expect(screen.queryByText('준비 / 일시정지')).toBeNull();
  expect(screen.getByRole('button', { name: /시작 \/ 계속/ })).toBeTruthy();
  const score = screen.getByLabelText('레이싱 점수').textContent;
  frames(60); expect(screen.getByLabelText('레이싱 점수').textContent).toBe(score);
  fireEvent.click(screen.getByRole('button', { name: '처음부터' }));
  expect(screen.getByLabelText('레이싱 점수').textContent).toContain('점수 0');
  expect(Number(localStorage.getItem('anycontrol.race.best'))).toBe(finalBest);
});
it('survival runs, stops on emergency or loss of focus, and starts over', () => {
  render(<SurvivalDemo />);
  fireEvent.click(screen.getByRole('button', { name: '생존 시작 / 계속' })); frames(50);
  expect(screen.getByLabelText('좀비 게임 점수').textContent).toContain('웨이브 1/8');
  act(() => window.dispatchEvent(new Event('anycontrol-stop')));
  expect(screen.queryByText('준비 / 일시정지')).toBeNull();
  expect(screen.getByRole('button', { name: /시작 \/ 계속/ })).toBeTruthy();
  const score = screen.getByLabelText('좀비 게임 점수').textContent;
  frames(50); expect(screen.getByLabelText('좀비 게임 점수').textContent).toBe(score);
  fireEvent.click(screen.getByRole('button', { name: '처음부터' }));
  expect(screen.getByLabelText('좀비 게임 점수').textContent).toContain('처치 0');
  fireEvent.blur(window);
  expect(screen.getByRole('button', { name: '생존 시작 / 계속' })).toBeTruthy();
});

it.each([RacingDemo, SurvivalDemo])('does no animation work while idle, paused or minimized', Demo => {
  render(<Demo />);
  fillRect.mockClear(); frames(120);
  expect(fillRect).not.toHaveBeenCalled(); expect(tick).toBeUndefined();
  fireEvent.click(screen.getByRole('button', { name: /시작 \/ 계속/ })); frames(5);
  expect(fillRect).toHaveBeenCalled();
  vi.mocked(HTMLElement.prototype.getClientRects).mockReturnValue([] as unknown as DOMRectList);
  frames(1); fillRect.mockClear(); frames(120);
  expect(fillRect).not.toHaveBeenCalled(); expect(tick).toBeUndefined();
});
it('receives live controller frames without React renders and expires stale input', () => {
  const renders = vi.fn();
  useApp.setState({ conn: 'open' });
  useDraftStore.getState().set(buildGameMapping(useDraftStore.getState().draft!, 'race', 1, 'x', ['#1']));
  render(<Profiler id="race" onRender={renders}><RacingDemo /></Profiler>);
  renders.mockClear();
  const data = { controller: { ...ZERO, mode: 'send', axes: { ...ZERO.axes, rt: 1 }, controls: { 'race.gas': 1, 'race.steer1': 0 } } };
  act(() => { for (let i = 0; i < 60; i++) listeners.forEach(fn => fn('state', data)); });
  expect(renders).not.toHaveBeenCalled();
  now += 600;
  fireEvent.click(screen.getByRole('button', { name: '주행 시작 / 계속' })); frames(20);
  expect(screen.getByRole('status').textContent).toContain('0 km/h');
  act(() => listeners.forEach(fn => fn('state', data))); frames(5);
  expect(screen.getByRole('status').textContent).not.toContain('0 km/h');
});
it('throttles score persistence and flushes the final score on pause', () => {
  const save = vi.spyOn(Storage.prototype, 'setItem');
  render(<SurvivalDemo />);
  fireEvent.click(screen.getByRole('button', { name: '생존 시작 / 계속' })); frames(100);
  expect(save.mock.calls.filter(([key]) => key === 'anycontrol.survival.best').length).toBeLessThanOrEqual(5);
  fireEvent.keyDown(screen.getByLabelText('좀비 게임 조작 영역'), { key: 'p' });
  expect(save.mock.calls.filter(([key]) => key === 'anycontrol.survival.best').length).toBeLessThanOrEqual(6);
});
it('space pauses and resumes every game', () => {
  render(<SurvivalDemo />);
  fireEvent.keyDown(window, { key: ' ' });
  expect(screen.getByRole('button', { name: '일시정지 (Space)' })).toBeTruthy();
  fireEvent.keyDown(window, { key: ' ' });
  expect(screen.getByRole('button', { name: '생존 시작 / 계속' })).toBeTruthy();
});
it.each([PongDemo, FruitDemo])('new game %#: starts, runs and pauses with space', Demo => {
  render(<Demo />);
  fireEvent.keyDown(window, { key: ' ' }); frames(10);
  expect(fillRect).toHaveBeenCalled();
  fireEvent.keyDown(window, { key: ' ' });
  expect(tick).toBeUndefined();
});
it('racing switches to a 2-player split screen', () => {
  render(<RacingDemo />);
  fireEvent.click(screen.getByRole('radio', { name: /2인 분할 화면/ }));
  expect(screen.getByLabelText('레이싱 점수').textContent).toContain('1P');
  fireEvent.keyDown(window, { key: ' ' }); frames(20);
  expect(screen.getByRole('status').textContent).toMatch(/m : \d+ m/);
});

it.each([RacingDemo, PongDemo, FruitDemo, SurvivalDemo, HockeyDemo])('requires explicit mapping before starting', Demo => {
  useDraftStore.getState().set({ version: 1, name: 'empty', description: '', mappings: [] });
  render(<Demo />);
  fireEvent.keyDown(window, { key: ' ' });
  expect(screen.getAllByRole('alert').some(el => el.textContent?.includes('자동 매핑'))).toBe(true);
  expect(screen.queryByRole('button', { name: '일시정지 (Space)' })).toBeNull();
});

it('only creates racing cables on Auto-map and applies the selected steering style', async () => {
  useDraftStore.getState().set({ version: 1, name: 'empty', description: '', mappings: [] });
  useApp.setState({ conn: 'open' });
  render(<RacingDemo />);
  expect(useDraftStore.getState().draft!.mappings).toHaveLength(0);
  fireEvent.change(screen.getByLabelText('자동 매핑 조작법'), { target: { value: 'angle' } });
  fireEvent.click(screen.getByRole('button', { name: '자동 매핑' }));
  await waitFor(() => expect(useDraftStore.getState().draft!.mappings).toHaveLength(3));
  expect(useDraftStore.getState().draft!.mappings[0]!.input).toMatchObject({ source: 'object', object: '#1', axis: 'angle' });
  fireEvent.click(screen.getByRole('button', { name: '주행 시작 / 계속' }));
  expect(screen.getByRole('button', { name: '일시정지 (Space)' })).toBeTruthy();
});

it('hockey supports the two-player mode and explicit mappings', () => {
  render(<HockeyDemo />);
  fireEvent.click(screen.getByRole('radio', { name: '2인 대결' }));
  fireEvent.keyDown(window, { key: ' ' }); frames(4);
  expect(screen.getByRole('button', { name: '일시정지 (Space)' })).toBeTruthy();
  expect(screen.getByRole('status').textContent).toContain('7골');
});

it('uses current mapped values, ignores an unrelated mouse, and immediately stops disabled mappings', () => {
  useApp.setState({ conn: 'open' });
  let read: (name: string) => number = () => 0;
  function Probe() { const s = useGameSession('probe', () => ({ score: 0, over: false })); read = s.demoControl; return null; }
  render(<Probe />);
  const emit = (v: number) => act(() => listeners.forEach(fn => fn('state', { controller: { ...ZERO, mode: 'send', axes: { ...ZERO.axes, left_x: v }, controls: { 'race.steer1': -v } }, mouse: { cursor_active: true, position: [1, 1] } })));
  emit(.7); expect(read('race.steer1')).toBe(.7);
  emit(-.4); expect(read('race.steer1')).toBe(-.4);
  act(() => { const p = useDraftStore.getState().draft!; useDraftStore.getState().set({ ...p, mappings: p.mappings.map(m => m.output.target === 'gamepad_axis' && m.output.axis === 'left_x' ? { ...m, enabled: false } : m) }); });
  expect(read('race.steer1')).toBe(0); expect(read('survival.x')).toBe(0);
});

it('keeps playing when editing mappings elsewhere in the app and clears held local keys', () => {
  render(<RacingDemo />);
  fireEvent.click(screen.getByRole('button', { name: '주행 시작 / 계속' }));
  const input = document.createElement('input'); document.body.append(input);
  fireEvent.blur(screen.getByLabelText('레이싱 조작 영역'), { relatedTarget: input });
  expect(screen.getByRole('button', { name: '일시정지 (Space)' })).toBeTruthy();
  fireEvent.blur(window);
  expect(screen.getByRole('button', { name: '주행 시작 / 계속' })).toBeTruthy();
  input.remove();
});

it.each([RacingDemo, PongDemo, FruitDemo, SurvivalDemo, HockeyDemo])('keeps large play/restart controls in Auto-map and edits both axis sensitivities in the mapping profile', async Demo => {
  useApp.setState({ conn: 'open' });
  render(<Demo />);
  fireEvent.click(screen.getByRole('button', { name: '자동 매핑' }));
  await waitFor(() => expect(screen.getByLabelText('게임 민감도').hasAttribute('disabled')).toBe(false));
  const box = screen.getByRole('region', { name: '게임 자동 매핑' });
  expect(box.contains(screen.getByRole('button', { name: /시작 \/ 계속/ }))).toBe(true);
  expect(box.contains(screen.getByRole('button', { name: '처음부터' }))).toBe(true);
  const before = useDraftStore.getState().draft!.mappings.filter(m => m.output.target === 'gamepad_axis').map(sensitivity);
  const mean = before.reduce((a, b) => a + b, 0) / before.length;
  fireEvent.change(screen.getByLabelText('게임 민감도'), { target: { value: '2' } });
  const mappings = useDraftStore.getState().draft!.mappings.filter(m => m.output.target === 'gamepad_axis');
  expect(mappings.length).toBeGreaterThan(0);
  mappings.forEach((m, i) => expect(sensitivity(m) / before[i]!).toBeCloseTo(2 / mean));
  expect(screen.queryByText('준비 / 일시정지')).toBeNull();
});
it('exposes hockey AI difficulty only for single player and preserves selection across restart', () => {
  render(<HockeyDemo />);
  fireEvent.change(screen.getByLabelText('AI 난이도'), { target: { value: 'easy' } });
  fireEvent.click(screen.getByRole('button', { name: '처음부터' }));
  expect((screen.getByLabelText('AI 난이도') as HTMLSelectElement).value).toBe('easy');
  fireEvent.click(screen.getByRole('radio', { name: '2인 대결' }));
  expect(screen.queryByLabelText('AI 난이도')).toBeNull();
});
