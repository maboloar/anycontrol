import { hideGuidePrompt, useGuidePrompt } from "../guidePrompt";
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { Topbar } from './Topbar';
import { RealOutputPanel } from './RealOutputPanel';
import { getReal, putReal, stopAll } from '../api';
import { useApp } from '../store';
import type { RealInfo } from '../protocol';
vi.mock('../api', () => ({ getReal: vi.fn(), putReal: vi.fn(), stopAll: vi.fn(), requestRealPermission: vi.fn() }));
vi.mock('./DisplayControls', () => ({ DisplayControls: () => <button>배치 초기화</button> }));
vi.mock('./CameraBuddy', () => ({ HeaderBuddy: () => null }));
const info: RealInfo = { state: 'off', remaining_s: null, trusted: true, stopped_by: null, supports: ['mouse', 'keyboard'] };
beforeEach(() => {
  hideGuidePrompt(); useApp.setState({ tourOpen: false });
  vi.mocked(getReal).mockReset().mockImplementation(() => new Promise(() => {}));
  vi.mocked(putReal).mockReset(); vi.mocked(stopAll).mockReset();
  useApp.setState({ conn: 'open', live: { ...useApp.getInitialState().live, real: info } });
});
afterEach(() => { cleanup(); vi.useRealTimers(); });
it('integrates countdown/on states and the emphasized ESC stop into the existing header', () => {
  useApp.setState({ live: { ...useApp.getInitialState().live, real: { ...info, state: 'arming', remaining_s: 2.5 } } });
  const { container } = render(<Topbar />);
  expect(container.querySelector('.topbar.arming.real-active')).not.toBeNull();
  expect(screen.getByRole('alert').textContent).toContain('3초');
  expect(screen.getByRole('button', { name: '정지 (ESC)' }).className).toBe('topbar-stop');
  expect(container.querySelector('.real-banner')).toBeNull();
  act(() => useApp.setState({ live: { ...useApp.getInitialState().live, real: { ...info, state: 'on' } } }));
  expect(container.querySelector('.topbar.on')).not.toBeNull();
  expect(screen.getByRole('alert').textContent).toContain('실제 입력 켜짐');
});
it('polls while video state is paused and reflects output toggles without a new frame', async () => {
  vi.mocked(putReal).mockResolvedValue({ ...info, state: 'arming', remaining_s: 3 });
  render(<><Topbar /><RealOutputPanel /></>);
  expect(screen.getByRole('heading', { name: /출력/ })).toBeTruthy();
  fireEvent.click(screen.getByRole('radio', { name: '실제 (OS 입력)' }));
  await waitFor(() => expect(screen.getByRole('alert').textContent).toContain('3초'));
  expect(putReal).toHaveBeenCalledWith(true);
});
it('an acknowledged stop stays off when an older poll completes afterwards', async () => {
  let resolve!: (r: RealInfo) => void;
  vi.mocked(getReal).mockImplementationOnce(() => new Promise(r => { resolve = r; }));
  useApp.setState({ live: { ...useApp.getInitialState().live, real: { ...info, state: 'on' } } });
  vi.mocked(stopAll).mockImplementation(async () => { window.dispatchEvent(new Event('anycontrol-stop')); window.dispatchEvent(new Event('anycontrol.real-stopped')); return {} as Awaited<ReturnType<typeof stopAll>>; });
  const { container } = render(<Topbar />);
  fireEvent.click(screen.getByRole('button', { name: '정지 (ESC)' }));
  await act(async () => { await Promise.resolve(); resolve({ ...info, state: 'on' }); });
  expect(stopAll).toHaveBeenCalledOnce(); expect(container.querySelector('.real-active')).toBeNull();
});
it('does not hide the active warning if stopping fails', async () => {
  useApp.setState({ live: { ...useApp.getInitialState().live, real: { ...info, state: 'on' } } });
  vi.mocked(stopAll).mockRejectedValue(new Error('Stop request failed'));
  const { container } = render(<Topbar />);
  fireEvent.click(screen.getByRole('button', { name: '정지 (ESC)' }));
  await waitFor(() => expect(screen.getByText('Stop request failed')).toBeTruthy());
  expect(container.querySelector('.topbar.real-active')).not.toBeNull();
});
it('refreshes the arming state without relying on camera frames', async () => {
  vi.useFakeTimers(); vi.mocked(getReal).mockResolvedValueOnce({ ...info, state: 'arming', remaining_s: 2 }).mockResolvedValue({ ...info, state: 'on' });
  render(<Topbar />);
  await act(async () => { await Promise.resolve(); });
  expect(screen.getByRole('alert').textContent).toContain('2초');
  await act(async () => { await vi.advanceTimersByTimeAsync(300); });
  expect(screen.getByRole('alert').textContent).toContain('실제 입력 켜짐');
});

it('places Guide next to the title and invites after 20 seconds of keyboard/mouse inactivity', async () => {
  vi.useFakeTimers();
  const { container } = render(<Topbar />);
  expect(container.querySelector('.topbar-brand .topbar-title + .help-btn')).not.toBeNull();
  await act(async () => { await vi.advanceTimersByTimeAsync(19_500); });
  expect(screen.queryByText(/처음이신가요/)).toBeNull();
  fireEvent.keyDown(window, { key: 'a' });
  await act(async () => { await vi.advanceTimersByTimeAsync(19_500); });
  expect(screen.queryByText(/처음이신가요/)).toBeNull();
  await act(async () => { await vi.advanceTimersByTimeAsync(500); });
  expect(container.querySelector('.topbar.guide-invite')).not.toBeNull();
  expect(screen.getByText('← 처음이신가요? 안내 버튼을 눌러 시작해 보세요')).toBeTruthy();
  fireEvent.click(screen.getByRole('button', { name: '? 안내' }));
  expect(useApp.getState().tourOpen).toBe(true);
  expect(useGuidePrompt.getState().visible).toBe(false);
});

it('hides backend version in basic mode and shows it below the title only in advanced mode', () => {
  useApp.setState({ devMode: false, serverVersion: '1.8.0' });
  const { container } = render(<Topbar />);
  expect(screen.queryByText('backend v1.8.0')).toBeNull();
  act(() => useApp.setState({ devMode: true }));
  const version = screen.getByText('backend v1.8.0');
  const meta = container.querySelector('.topbar-title .brand + .topbar-meta');
  expect(meta?.contains(version)).toBe(true); expect(meta?.firstElementChild?.className).toContain('dev-badge');   // 고급 모드 배지 → backend 버전
});
