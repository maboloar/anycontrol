import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { connectVideoObject } from '../videoMapping';
import { StrictMode } from 'react';
import { GamepadView, padFromState, ZERO } from './GamepadView';
import { MappingPanel } from './MappingPanel';
import { PatchCables } from './PatchCables';
import { useApp } from '../store';
import { useDraftStore } from '../mappingDraft';
import { allFns, cables, connect as connectMapping, inferredFns, PATCH_FNS, registerFns, loadCustomJacks } from '../patch';
import type { FrameState, ObjectInfo, Profile } from '../protocol';
const edit = vi.hoisted(() => vi.fn());
vi.mock('../mappingDraft', async importOriginal => {
  const m = await importOriginal<typeof import('../mappingDraft')>();
  return { ...m, useMappingDraft: () => ({ draft: m.useDraftStore(s => s.draft), edit, err: null }) };
});
vi.mock('../api', () => ({ getTouchSettings: vi.fn(async () => ({ object_sensitivity: .7 })), listProfiles: vi.fn(async () => []), putOutputMode: vi.fn(), saveProfile: vi.fn(), loadProfile: vi.fn(), deleteProfile: vi.fn(), learnStart: vi.fn(), learnStop: vi.fn() }));
vi.mock('./VirtualIoView', () => ({ VirtualIoView: () => null }));
vi.mock('../connection', () => ({ connection: { onMessage: () => () => {} } }));
const empty: Profile = { version: 1, name: 'test', description: '', mappings: [] };
beforeEach(() => {
  localStorage.clear(); registerFns('test', []); edit.mockReset();
  useApp.setState({ conn: 'open', devMode: false, objects: [{ id: 1, name: 'Cup', kind: 'object', state: 'tracking' }] as ObjectInfo[], mappingInfo: { profile: empty, mode: 'observe', warnings: [], hands_available: true } });
  useDraftStore.getState().set(empty);
  edit.mockImplementation(p => useDraftStore.getState().set(p));
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });
it('uses the same add label/style and creates a row plus cable when adding above', async () => {
  const { container } = render(<MappingPanel />);
  await waitFor(() => expect(screen.getAllByRole('button', { name: '+ 매핑 추가' })).toHaveLength(2));
  const buttons = screen.getAllByRole('button', { name: '+ 매핑 추가' });
  expect(buttons[0]!.className).toBe(buttons[1]!.className);
  fireEvent.click(buttons[0]!);
  const form = screen.getByRole('group', { name: '매핑 추가' });
  fireEvent.change(within(form).getByLabelText('설명'), { target: { value: '점프' } });
  fireEvent.change(within(form).getByLabelText('출력 종류'), { target: { value: 'key' } });
  fireEvent.change(within(form).getByLabelText('키'), { target: { value: 'enter' } });
  fireEvent.click(within(form).getByRole('button', { name: '추가' }));
  const p = useDraftStore.getState().draft!;
  expect(p.mappings).toHaveLength(1); expect(p.mappings[0]!.input).toEqual({ source: 'object', object: '#1', axis: 'x' });
  expect(cables(p, allFns())).toHaveLength(1);
  expect(container.querySelectorAll('.map-row')).toHaveLength(2);
  expect(container.querySelector('.patch-fn.on')?.textContent).toContain('점프');
  expect(screen.getAllByRole('button', { name: '보여 주며 설정' })[0]!.className).not.toContain('act-');
  expect(screen.getAllByRole('button', { name: '매핑 해제' })).toHaveLength(2);
});
it('derives a missing jack and wire when a row output changes, and removes it with the row', () => {
  const { container } = render(<MappingPanel />);
  fireEvent.click(screen.getAllByRole('button', { name: '+ 매핑 추가' })[1]!);
  fireEvent.change(screen.getByRole('combobox', { name: '출력 종류' }), { target: { value: 'gamepad_button' } });
  fireEvent.change(screen.getByRole('combobox', { name: '버튼' }), { target: { value: 'b' } });
  fireEvent.click(screen.getByRole('button', { name: '추가' }));
  expect(container.querySelector('.patch-fn.on [data-jack]')?.getAttribute('data-jack')).toContain('fn:auto-');
  const p = useDraftStore.getState().draft!;
  expect(cables(p, allFns())).toHaveLength(1);
  fireEvent.click(screen.getAllByRole('button', { name: '매핑 해제' })[1]!);
  expect(container.querySelector('.patch-fn.on')).toBeNull();
  expect(container.querySelector('[data-jack^="fn:auto-"]')).toBeNull();
});
it('creates an inferred wire for a loaded pen-contact mapping', () => {
  const p: Profile = { ...empty, mappings: [{ id: 'pen', label: 'Pen Enter', enabled: true, input: { source: 'pen', object: '#1' }, output: { target: 'key', key: 'enter' }, transform: { range: [0, 1], deadzone: 0, curve: 'linear', expo: 0, invert: false, smoothing_ms: 0, on: .6, off: .35, mode: "absolute", on_lost: 'release', lost_ms: 0 } }] };
  const inferred = inferredFns(p, PATCH_FNS);
  expect(cables(p, [...PATCH_FNS, ...inferred])).toHaveLength(1);
});
it('middle-click disconnects a cable while left-click selects it', () => {
  vi.stubGlobal('CSS', { escape: (s: string) => s });
  vi.stubGlobal('requestAnimationFrame', () => 1); vi.stubGlobal('cancelAnimationFrame', () => {});
  vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockReturnValue({ left: 1, top: 1, width: 20, height: 20 } as DOMRect);
  Object.defineProperty(document, 'elementsFromPoint', { configurable: true, value: () => [] });
  const selected = vi.fn(), removed = vi.fn();
  const { container } = render(<><button data-jack="obj:#1" /><button data-jack="fn:steer" /><PatchCables cables={[{ id: 'm1', object: '#1', fn: 'steer' }]} onCut={selected} onDisconnect={removed} /></>);
  const hit = container.querySelector('.cable-hit')!;
  expect(hit).not.toBeNull();
  fireEvent.click(hit); expect(selected).toHaveBeenCalledExactlyOnceWith('m1');
  act(() => { hit.dispatchEvent(new MouseEvent('auxclick', { button: 1, bubbles: true, cancelable: true })); });
  expect(removed).toHaveBeenCalledExactlyOnceWith('m1');
});

it('defaults to an object arriving after panel mount while preserving an explicit hand choice', () => {
  useApp.setState({ objects: [] });
  render(<MappingPanel />);
  act(() => useApp.setState({ objects: [{ id: 1, name: 'Cup', kind: 'object' }] as ObjectInfo[] }));
  fireEvent.click(screen.getAllByRole('button', { name: '+ 매핑 추가' })[0]!);
  let source = screen.getByRole('combobox', { name: '물체' }) as HTMLSelectElement;
  expect(source.value).toBe('#1');
  fireEvent.change(screen.getByRole('combobox', { name: '입력 종류' }), { target: { value: 'hand' } });
  act(() => useApp.setState({ objects: [{ id: 2, name: 'Book', kind: 'object' }] as ObjectInfo[] }));
  source = screen.getByRole('combobox', { name: '입력 종류' }) as HTMLSelectElement;
  expect(source.value).toBe('hand');
});
it('keeps derived jacks registered after Strict Mode effect replay', () => {
  const p = { ...empty, mappings: [{ id: 'b', label: 'B', enabled: true, input: { source: 'hand' as const, gesture: 'pinch' as const }, output: { target: 'gamepad_button' as const, button: 'b' as const }, transform: { mode: 'absolute' as const, range: [0, 1] as [number, number], deadzone: 0, curve: 'linear' as const, expo: 0, invert: false, smoothing_ms: 0, on: .6, off: .35, on_lost: 'release' as const, lost_ms: 0 } }] };
  useDraftStore.getState().set(p);
  render(<StrictMode><MappingPanel /></StrictMode>);
  expect(cables(p, allFns())).toHaveLength(1);
});
it.each(['observe', 'send'])('renders the same virtual pad axes/buttons used by games in %s mode', mode => {
  const axes = { ...ZERO.axes, left_x: .75, left_y: -.5, rt: .4 };
  const buttons = { ...ZERO.buttons, a: true };
  const state = { controller: { ...ZERO, axes, buttons, mode }, mapping: { computed: { axes, buttons, keys: [], controls: {}, mouse: { move: [0, 0], scroll: 0, left: false, right: false } }, live: [] } } as unknown as FrameState;
  const { container } = render(<GamepadView pad={padFromState(state)} />);
  const stick = container.querySelector('[aria-label="왼쪽 스틱"] .pad-stick')!;
  expect(stick.getAttribute('cx')).toBe('92'); expect(stick.getAttribute('cy')).toBe('84');
  expect(container.querySelector('svg')!.getAttribute('aria-label')).toContain('A');
});

it('an explicitly selected existing cable can be reassigned by clicking another video object', () => {
  vi.stubGlobal('CSS', { escape: (s: string) => s });
  const rafs: FrameRequestCallback[] = [];
  vi.stubGlobal('requestAnimationFrame', (fn: FrameRequestCallback) => { rafs.push(fn); return 1; }); vi.stubGlobal('cancelAnimationFrame', () => {});
  vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockReturnValue(new DOMRect(0, 0, 20, 20));
  Object.defineProperty(document, 'elementsFromPoint', { configurable: true, value: () => [] });
  useApp.setState({ objects: [
    { id: 1, name: 'A', kind: 'object', state: 'tracking', box: [.1, .2, .4, .5], contour: [] },
    { id: 2, name: 'B', kind: 'object', state: 'tracking', box: [.6, .2, .9, .5], contour: [] },
  ] as unknown as ObjectInfo[] });
  useDraftStore.getState().set(connectMapping(empty, '#1', 'steer'));
  const { container } = render(<><button data-jack="obj:#1" /><MappingPanel /></>);
  act(() => { rafs.splice(0).forEach(fn => fn(0)); });
  fireEvent.click(container.querySelector('.cable-hit')!);
  expect(useApp.getState().patchDrag?.from).toEqual({ kind: 'fn', id: 'steer' });
  act(() => { connectVideoObject([.7, .3], useApp.getState().objects); });
  const p = useDraftStore.getState().draft!;
  expect(p.mappings).toHaveLength(1); expect(p.mappings[0]!.input).toMatchObject({ object: '#2' });
});

it.each([0, 1])('creates every hand input through the same add flow %s and synchronizes both editors', index => {
  render(<MappingPanel />);
  fireEvent.click(screen.getAllByRole('button', { name: '+ 매핑 추가' })[index]!);
  const form = screen.getByRole('group', { name: '매핑 추가' });
  fireEvent.change(within(form).getByLabelText('입력 종류'), { target: { value: 'hand' } });
  expect([...within(form).getByLabelText('제스처').querySelectorAll('option')].map(o => o.value)).toEqual(['x', 'y', 'pinch', 'pinch_middle']);
  fireEvent.change(within(form).getByLabelText('제스처'), { target: { value: 'pinch_middle' } });
  fireEvent.change(within(form).getByLabelText('출력 종류'), { target: { value: 'key' } });
  fireEvent.change(within(form).getByLabelText('키'), { target: { value: 'enter' } });
  fireEvent.click(within(form).getByRole('button', { name: '추가' }));
  expect(useDraftStore.getState().draft!.mappings[0]!.input).toEqual({ source: 'hand', gesture: 'pinch_middle' });
  const gestures = screen.getAllByLabelText('제스처') as HTMLSelectElement[];
  expect(gestures).toHaveLength(2); expect(gestures.every(e => e.value === 'pinch_middle')).toBe(true);
  fireEvent.change(gestures[0]!, { target: { value: 'x' } });
  expect((screen.getAllByLabelText('제스처')[1] as HTMLSelectElement).value).toBe('x');
  const sliders = screen.getAllByLabelText('매핑 민감도');
  fireEvent.change(sliders[1]!, { target: { value: '2' } });
  expect((screen.getAllByLabelText('매핑 민감도')[0] as HTMLInputElement).value).toBe('2');
  expect(useDraftStore.getState().draft!.mappings[0]!.transform.range).toEqual([-.15, .15]);
  fireEvent.click(screen.getAllByRole('button', { name: '세부 설정' })[0]!);
  expect(screen.getByText('놓쳤을 때')).toBeTruthy();
});

it.each([0, 1])('preserves named custom hand jacks and restores the chosen gesture/settings when reconnecting (%s)', index => {
  render(<MappingPanel />);
  fireEvent.click(screen.getAllByRole('button', { name: '+ 매핑 추가' })[index]!);
  const form = screen.getByRole('group', { name: '매핑 추가' });
  fireEvent.change(within(form).getByLabelText('설명'), { target: { value: '중지 스위치' } });
  fireEvent.change(within(form).getByLabelText('입력 종류'), { target: { value: 'hand' } });
  fireEvent.change(within(form).getByLabelText('제스처'), { target: { value: 'pinch_middle' } });
  fireEvent.change(within(form).getByLabelText('출력 종류'), { target: { value: 'key' } });
  fireEvent.click(within(form).getByRole('button', { name: '추가' }));
  const jack = loadCustomJacks()[0]!;
  expect(jack.handGesture).toBe('pinch_middle');
  const current = useDraftStore.getState().draft!;
  const reconnected = connectMapping({ ...current, mappings: [] }, '@hand', jack.id).mappings[0]!;
  expect(reconnected.input).toEqual({ source: 'hand', gesture: 'pinch_middle' });
  expect(reconnected.transform).toEqual(current.mappings[0]!.transform);
});
it('blocks adding an invalid keyboard key without silently submitting the previous valid key', () => {
  render(<MappingPanel />);
  fireEvent.click(screen.getAllByRole('button', { name: '+ 매핑 추가' })[0]!);
  const form = screen.getByRole('group', { name: '매핑 추가' });
  fireEvent.change(within(form).getByLabelText('출력 종류'), { target: { value: 'key' } });
  fireEvent.change(within(form).getByLabelText('키'), { target: { value: 'invalid-key' } });
  expect((within(form).getByRole('button', { name: '추가' }) as HTMLButtonElement).disabled).toBe(true);
  fireEvent.change(within(form).getByLabelText('설명'), { target: { value: 'Jump' } });
  expect((within(form).getByRole('button', { name: '추가' }) as HTMLButtonElement).disabled).toBe(true);
  fireEvent.change(within(form).getByLabelText('키'), { target: { value: 'enter' } });
  fireEvent.click(within(form).getByRole('button', { name: '추가' }));
  expect(useDraftStore.getState().draft!.mappings[0]!.output).toEqual({ target: 'key', key: 'enter' });
});
