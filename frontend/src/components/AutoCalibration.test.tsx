import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { AutoCalibration } from './AutoCalibration';
import { applyAutoCalibration, autoCalibrationAction, getAutoCalibration, startAutoCalibration } from '../api';
import type { AutoCalibrationState, MouseInfo } from '../protocol';
import { useApp } from '../store';

vi.mock('../api', () => ({ applyAutoCalibration: vi.fn(), autoCalibrationAction: vi.fn(),
  getAutoCalibration: vi.fn(), startAutoCalibration: vi.fn() }));
const id = '1'.repeat(32);
function state(patch: Partial<AutoCalibrationState> = {}): AutoCalibrationState {
  return { id, kind: 'hand', object_id: null, phase: 'ready', index: 0, total: 9, completed: 0,
    step: { key: 'rest', title: '떨림 확인', instruction: '손바닥을 중앙에서 움직이지 말고 유지하세요.', duration: 2 },
    progress: 0, samples: 0, error: null, result: null, ...patch };
}
beforeEach(() => {
  vi.resetAllMocks();
  useApp.setState({ conn: 'open', autoCalibration: null, mouseInfo: null,
    live: { mouse: null, pens: {}, mapping: null, controller: null } });
  vi.mocked(getAutoCalibration).mockResolvedValue(null);
  vi.mocked(startAutoCalibration).mockResolvedValue(state());
  vi.mocked(autoCalibrationAction).mockImplementation(async a => state({ phase: a === 'cancel' ? 'cancelled' : 'recording' }));
});
afterEach(cleanup);

it('guides recording and retries insufficient measurements before applying observed settings', async () => {
  const prepare = vi.fn().mockResolvedValue(undefined);
  render(<AutoCalibration kind="hand" prepare={prepare} />);
  fireEvent.click(screen.getByRole('button', { name: '맨손 마우스 자동 보정' }));
  await waitFor(() => expect(screen.getByRole('dialog')).toBeTruthy());
  expect(prepare).toHaveBeenCalledOnce();
  expect(startAutoCalibration).toHaveBeenCalledWith('hand', null);
  expect(screen.getByText('손바닥을 중앙에서 움직이지 말고 유지하세요.')).toBeTruthy();
  fireEvent.click(screen.getByRole('button', { name: '측정 시작' }));
  await waitFor(() => expect(autoCalibrationAction).toHaveBeenCalledWith('record', id, 'rest'));
  act(() => useApp.getState().setAutoCalibration(state({ phase: 'recording', progress: .5, samples: 15 })));
  expect(screen.getByRole('progressbar').getAttribute('value')).toBe('0.5');
  act(() => useApp.getState().setAutoCalibration(state({ error: '관측이 부족합니다' })));
  expect(screen.getByRole('alert').textContent).toBe('관측이 부족합니다');
  expect(screen.getByRole('button', { name: '이 단계 다시 측정' })).toBeTruthy();
  const review = state({ phase: 'review', completed: 9, index: 8,
    result: { mouse: { pinch_on: .35 }, pen: {}, notes: ['놓기 확인 완료'], metrics: {}, summary: ['집기 문턱 0.35'] } });
  const mouse = { settings: { mode: 'hand', pinch_on: .35 } } as MouseInfo;
  vi.mocked(applyAutoCalibration).mockResolvedValue({ calibration: { ...review, phase: 'complete' }, mouse, pen: null });
  act(() => useApp.getState().setAutoCalibration(review));
  expect(screen.getByText('집기 문턱 0.35')).toBeTruthy();
  fireEvent.click(screen.getByRole('button', { name: '자동 설정 적용' }));
  await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
  expect(applyAutoCalibration).toHaveBeenCalledWith(id);
  expect(useApp.getState().mouseInfo?.settings.pinch_on).toBe(.35);
  expect(screen.getByRole('status').textContent).toBe('자동 보정 설정을 적용했습니다.');
});

it('cancels without applying and prevents competing calibration sessions', async () => {
  render(<AutoCalibration kind="hand" />);
  fireEvent.click(screen.getByRole('button', { name: '맨손 마우스 자동 보정' }));
  await screen.findByRole('dialog');
  fireEvent.click(screen.getByRole('button', { name: '취소' }));
  await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
  expect(autoCalibrationAction).toHaveBeenCalledWith('cancel', id, undefined);
  expect(applyAutoCalibration).not.toHaveBeenCalled();
  act(() => useApp.getState().setAutoCalibration(state({ kind: 'pen', object_id: 1 })));
  expect((screen.getByRole('button', { name: '맨손 마우스 자동 보정' }) as HTMLButtonElement).disabled).toBe(true);
});

it('cancels its active session on unmount and reports server errors', async () => {
  const view = render(<AutoCalibration kind="hand" />);
  fireEvent.click(screen.getByRole('button', { name: '맨손 마우스 자동 보정' }));
  await screen.findByRole('dialog');
  view.unmount();
  expect(autoCalibrationAction).toHaveBeenCalledWith('cancel', id);
  await act(async () => {});
  useApp.setState({ autoCalibration: null });
  vi.mocked(startAutoCalibration).mockRejectedValueOnce(new Error('409 영상을 켜세요'));
  render(<AutoCalibration kind="hand" />);
  fireEvent.click(screen.getByRole('button', { name: '맨손 마우스 자동 보정' }));
  expect((await screen.findByRole('alert')).textContent).toBe('영상을 켜세요');
});

it('shows recognition feedback before recording and live release counts during measurement', async () => {
  vi.mocked(startAutoCalibration).mockResolvedValue(state({ feedback: { level: 'waiting', message: '손 전체를 보여 주세요', cycles: null } }));
  render(<AutoCalibration kind="hand" />);
  fireEvent.click(screen.getByRole('button', { name: '맨손 마우스 자동 보정' })); await screen.findByRole('dialog');
  expect(screen.getByText('손 전체를 보여 주세요')).toBeTruthy();
  expect((screen.getByRole('button', { name: '측정 시작' }) as HTMLButtonElement).disabled).toBe(true);
  act(() => useApp.getState().setAutoCalibration(state({ feedback: { level: 'good', message: '대상이 보입니다', cycles: null } })));
  expect((screen.getByRole('button', { name: '측정 시작' }) as HTMLButtonElement).disabled).toBe(false);
  act(() => useApp.getState().setAutoCalibration(state({ phase: 'recording', feedback: { level: 'good', message: '클릭 후 놓기 2/2회 이상 확인', cycles: 2 } })));
  expect(screen.getByText('클릭 후 놓기 2/2회 이상 확인')).toBeTruthy();
});

it('can skip even without recognition and sends the current step to avoid stale actions', async () => {
  vi.mocked(startAutoCalibration).mockResolvedValue(state({
    feedback: { level: 'waiting', message: '손을 찾지 못했습니다', cycles: null }, attempts_failed: 2,
  }));
  render(<AutoCalibration kind="hand" />);
  fireEvent.click(screen.getByRole('button', { name: '맨손 마우스 자동 보정' }));
  await screen.findByRole('dialog');
  expect((screen.getByRole('button', { name: '측정 시작' }) as HTMLButtonElement).disabled).toBe(true);
  fireEvent.click(screen.getByRole('button', { name: '이 검사 건너뛰기' }));
  await waitFor(() => expect(autoCalibrationAction).toHaveBeenCalledWith('skip', id, 'rest'));
  expect(applyAutoCalibration).not.toHaveBeenCalled();
});
