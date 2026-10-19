import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { DevBadge, DevModeToggle } from './DevMode';
import { ObjectPanel } from './ObjectPanel';
import { useApp } from '../store';
import type { ObjectInfo } from '../protocol';

vi.mock('../connection', () => ({ connection: { connect: vi.fn(), close: vi.fn() } }));
vi.mock('../api', () => ({
  getAutoReseg: vi.fn(), putAutoReseg: vi.fn(),
  getTracking: vi.fn(() => Promise.resolve(null)), putTracking: vi.fn(), deleteObject: vi.fn(), setNeutral: vi.fn(),
  pickCandidate: vi.fn(), renameObject: vi.fn(), stopAll: vi.fn(() => Promise.resolve()),
  getObjectThumbnail: vi.fn(() => Promise.resolve({ id: 1, image: null })), forgetObjectMemory: vi.fn(),
  getObjectMemory: vi.fn(() => Promise.resolve({
    id: 1, name: '물체 1', color: '#88f', state: 'tracking', lost_for_s: null, snapshots: [], shape: null, tier1: null,
    reacquire: { enabled: false, last: null, searches: 0, recovered: 0, thresholds: { iou: .72, hu: .5, color: .6 } } })),
}));
const object = { id: 1, name: '물체 1', kind: 'object', color: '#88f', state: 'tracking', confidence: .9,
  axes: { x: 0, y: 0, depth: 0, angle: 0, stretch: 0, contact: 0 }, texture: .5, contrast: .5, warnings: [], candidates: 1,
  candidate_index: 0, box: null, contour: [], debug: {} } as ObjectInfo;

beforeEach(() => { localStorage.clear(); useApp.setState({ devMode: false, memoryOpen: false, objects: [object], selectedId: 1, conn: 'open' }); });
afterEach(cleanup);

it('is labeled advanced mode, shows the title badge only when on', () => {
  render(<><h1 className="brand">AnyControl<DevBadge /></h1><button className="help-btn">? 안내</button><DevModeToggle /></>);
  const toggle = screen.getByRole('button', { name: '고급 모드' });
  expect(toggle.getAttribute('aria-pressed')).toBe('false');
  expect(toggle.textContent).toContain('기본');
  expect(toggle.className).toContain('dev-btn');
  expect(toggle.previousElementSibling?.className).toContain('help-btn');
  expect(document.querySelector('.brand .dev-badge')).toBeNull();
  fireEvent.click(toggle);
  expect(screen.getByRole('button', { name: '고급 모드' }).getAttribute('aria-pressed')).toBe('true');
  expect(document.querySelector('.brand .dev-badge')?.textContent).toBe('고급 모드');
  fireEvent.click(screen.getByRole('button', { name: '고급 모드' }));
  expect(document.querySelector('.brand .dev-badge')).toBeNull();
});

it('keeps the live memory manager in basic mode but hides the detailed numbers', async () => {
  render(<ObjectPanel />);
  fireEvent.click(screen.getByRole('button', { name: '실시간 기억 관리' }));
  expect(await screen.findByLabelText('물체 기억')).toBeTruthy();
  expect(screen.queryByText(/재획득 꺼짐/)).toBeNull();
  act(() => useApp.getState().setDevMode(true));
  expect(await screen.findByText(/재획득 꺼짐/)).toBeTruthy();
  act(() => useApp.getState().setDevMode(false));
  expect(screen.getByLabelText('물체 기억')).toBeTruthy();                       // 고급 모드를 꺼도 기억 관리는 그대로
});

it('remembers developer mode across reloads', () => {
  useApp.getState().setDevMode(true);
  expect(localStorage.getItem('anycontrol.devMode')).toBe('1');
  useApp.getState().setDevMode(false);
  expect(localStorage.getItem('anycontrol.devMode')).toBe('0');
});
