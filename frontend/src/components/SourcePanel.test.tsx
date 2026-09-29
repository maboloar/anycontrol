import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { SourcePanel } from './SourcePanel';
import { useApp } from '../store';
import { getCameras, getSource, putCameraPower, putPlayback, putSource, restartSource } from '../api';

vi.mock('../api', () => ({
  getCameras: vi.fn(), getSource: vi.fn(), putSource: vi.fn().mockResolvedValue({}),
  putPlayback: vi.fn(), putCameraPower: vi.fn(), restartSource: vi.fn(), openDeskViewSetup: vi.fn(),
}));
const normal = { kind: 'camera' as const, index: 1, device_id: 'phone',
  width: 1280, height: 720, fps: 60, mirror: true, desk_view: false };
const phone = { index: 1, unique_id: 'phone', name: 'iPhone', model: '', is_continuity: true,
  is_desk_view: false, companion_id: 'desk', formats: [{ width: 1280, height: 720, max_fps: 60 }] };
const desk = { ...phone, index: 2, unique_id: 'desk', name: 'Desk View', is_continuity: false,
  is_desk_view: true, companion_id: null, parent_id: 'phone' };

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  useApp.setState({ conn: 'open', telemetry: null });
  vi.mocked(getSource).mockResolvedValue({ spec: normal });
  vi.mocked(getCameras).mockResolvedValue([phone, desk]);
  vi.mocked(putPlayback).mockImplementation(async (paused) => ({ paused }));
  vi.mocked(putCameraPower).mockImplementation(async (enabled) => ({ enabled }));
});
afterEach(cleanup);

it('restores the original camera settings when Desk View is turned off', async () => {
  render(<SourcePanel />);
  const toggle = screen.getByRole('checkbox', { name: /Desk View/ });
  await waitFor(() => expect((toggle as HTMLInputElement).disabled).toBe(false));
  expect(screen.queryByRole('button', { name: 'Desk View 설정 열기' })).toBeNull();
  fireEvent.click(toggle);
  await waitFor(() => expect(putSource).toHaveBeenCalledWith({ ...normal, desk_view: true }));
  await waitFor(() => expect((toggle as HTMLInputElement).checked).toBe(true));
  expect(screen.getByRole('button', { name: 'Desk View 설정 열기' })).toBeTruthy();
  fireEvent.click(toggle);
  await waitFor(() => expect(putSource).toHaveBeenLastCalledWith(normal));
  await waitFor(() => expect(screen.queryByRole('button', { name: 'Desk View 설정 열기' })).toBeNull());
});

it('keeps the current source when Desk View is unavailable', async () => {
  vi.mocked(getCameras).mockResolvedValue([{ ...phone, companion_id: null }]);
  render(<SourcePanel />);
  await waitFor(() => expect(getSource).toHaveBeenCalled());
  expect((screen.getByRole('checkbox', { name: /Desk View/ }) as HTMLInputElement).disabled).toBe(true);
  expect(putSource).not.toHaveBeenCalled();
});

it('toggles camera power and playback while mirror uses the current source', async () => {
  render(<SourcePanel />);
  await screen.findByRole('button', { name: '카메라 끄기' });
  fireEvent.click(screen.getByRole('button', { name: '일시정지' }));
  await screen.findByRole('button', { name: '재생' });
  expect(putPlayback).toHaveBeenCalledWith(true);
  fireEvent.click(screen.getByRole('button', { name: '카메라 끄기' }));
  await screen.findByRole('button', { name: '카메라 켜기' });
  expect(putCameraPower).toHaveBeenCalledWith(false);
  expect((screen.getByRole('button', { name: '재생' }) as HTMLButtonElement).disabled).toBe(true);
  fireEvent.click(screen.getByRole('checkbox', { name: '카메라 영상 좌우 반전' }));
  await waitFor(() => expect(putSource).toHaveBeenCalledWith({ ...normal, paused: true, enabled: false, mirror: false }));
  fireEvent.click(screen.getByRole('button', { name: '카메라 켜기' }));
  await screen.findByRole('button', { name: '카메라 끄기' });
  fireEvent.click(screen.getByRole('button', { name: '재생' }));
  await waitFor(() => expect(putPlayback).toHaveBeenLastCalledWith(false));
});

it('controls a developer-provided source without exposing bundled test inputs', async () => {
  const spec = { kind: 'synthetic' as const, width: 1280, height: 720, fps: 30, paused: true };
  vi.mocked(getSource).mockResolvedValue({ spec });
  vi.mocked(restartSource).mockResolvedValue({ spec });
  render(<SourcePanel />);
  await screen.findByRole('button', { name: '재생' });
  expect(screen.queryByRole('button', { name: /합성 장면|test\.mov|pen_test/ })).toBeNull();
  fireEvent.click(screen.getByRole('button', { name: '재생' }));
  await screen.findByRole('button', { name: '일시정지' });
  fireEvent.click(screen.getByRole('button', { name: '처음부터 선택' }));
  await screen.findByRole('button', { name: '재생' });
  expect(restartSource).toHaveBeenCalledOnce();
});
