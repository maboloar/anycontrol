import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { ObjectPanel } from './ObjectPanel';
import { forgetObjectMemory, getObjectMemory, getObjectThumbnail, getTracking, pickCandidate, putTracking, renameObject } from '../api';
import { useApp } from '../store';
import type { ObjectInfo } from '../protocol';
vi.mock('../api', () => ({ getTracking: vi.fn(), putTracking: vi.fn(), deleteObject: vi.fn(), setNeutral: vi.fn(), pickCandidate: vi.fn(), renameObject: vi.fn(), getObjectMemory: vi.fn(), getObjectThumbnail: vi.fn(() => Promise.resolve({ id: 1, image: null })), forgetObjectMemory: vi.fn(), getAutoReseg: vi.fn(), putAutoReseg: vi.fn() }));
const object = { id: 1, name: '물체 1', kind: 'object', color: '#88f', state: 'tracking', confidence: .9,
  axes: { x: 0, y: 0, depth: 0, angle: 0, stretch: 0, contact: 0 }, texture: .5, contrast: .5, warnings: [], candidates: 3, candidate_index: 0, box: null, contour: [], debug: {} } as ObjectInfo;
beforeEach(() => { vi.resetAllMocks(); localStorage.clear(); useApp.setState({ conn: 'closed', objects: [object], selectedId: 1, devMode: true, memoryOpen: false }); });
afterEach(cleanup);
it('advances past a failed candidate and immediately displays a successful replacement', async () => {
  vi.mocked(pickCandidate).mockRejectedValueOnce(new Error('422 invalid mask')).mockResolvedValueOnce({ ...object, id: 2, candidate_index: 2 });
  render(<ObjectPanel />);
  fireEvent.click(screen.getByRole('button', { name: '다른 분할 후보 (1/3)' }));
  await screen.findByRole('alert');
  expect(pickCandidate).toHaveBeenCalledWith(1, 1);
  fireEvent.click(screen.getByRole('button', { name: '다른 분할 후보 (2/3)' }));
  await waitFor(() => expect(useApp.getState().selectedId).toBe(2));
  expect(pickCandidate).toHaveBeenLastCalledWith(1, 2);
  expect(screen.getByRole('button', { name: '다른 분할 후보 (3/3)' })).toBeTruthy();
});
it.each(['object', 'pen'] as const)('selects a %s tab without editing, then renames via the name button, saving on blur and cancelling with Escape', async kind => {
  useApp.setState({ objects: [{ ...object, kind }] });
  vi.mocked(renameObject).mockResolvedValue({ ...object, kind, name: '내 컨트롤러' });
  render(<ObjectPanel />);
  fireEvent.click(screen.getByRole('tab', { name: kind === 'pen' ? '물체 1 Beta' : '물체 1' }));
  expect(screen.queryByRole('textbox')).toBeNull();
  fireEvent.click(screen.getByRole('button', { name: '물체 1' }));
  const input = screen.getByRole('textbox', { name: kind === 'pen' ? '펜 이름' : '물체 이름' });
  fireEvent.change(input, { target: { value: ' 내 컨트롤러 ' } }); fireEvent.blur(input);
  await waitFor(() => expect(useApp.getState().objects[0]?.name).toBe('내 컨트롤러'));
  expect(renameObject).toHaveBeenCalledWith(1, '내 컨트롤러');
  fireEvent.click(screen.getByRole('button', { name: '내 컨트롤러' }));
  const again = screen.getByRole('textbox');
  fireEvent.change(again, { target: { value: '취소할 이름' } }); fireEvent.keyDown(again, { key: 'Escape' });
  expect(screen.queryByRole('textbox')).toBeNull();
  expect(renameObject).toHaveBeenCalledTimes(1);
});

it('deletes all objects only after a second click on the armed button', async () => {
  const { deleteObject } = await import('../api');
  vi.mocked(deleteObject).mockResolvedValue(undefined);
  useApp.setState({ objects: [object, { ...object, id: 2, name: '펜 1', kind: 'pen' }] });
  render(<ObjectPanel />);
  fireEvent.click(screen.getByRole('button', { name: /모두 삭제 \(2\)/ }));
  expect(deleteObject).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: /2개 정말 삭제할까요\?/ }));
  await waitFor(() => expect(deleteObject).toHaveBeenCalledTimes(2));
});

it('shows the remembered views, shape and colors on demand and refreshes while open', async () => {
  const { getObjectMemory } = await import('../api');
  vi.mocked(getObjectMemory).mockResolvedValue({
    id: 1, name: '물체 1', color: '#88f', state: 'lost', lost_for_s: 1.5,
    snapshots: [{ kind: 'registration', t: 0, age_s: 3, image: 'data:image/jpeg;base64,AA==', info: { area: 1200 } },
      { kind: 'anchor', t: 1, age_s: 2, image: 'data:image/jpeg;base64,AA==', info: { iou: 0.9 } }],
    shape: { template: 'data:image/png;base64,AA==', elongation: 2.1, area: 1200, hu: [0.1, 0.2], palette: [{ hex: '#336699', weight: 0.8 }] },
    tier1: { anchors: 1, recent: 4, max_anchors: 3 },
    reacquire: { enabled: true, last: null, searches: 5, recovered: 0, thresholds: { iou: 0.72, hu: 0.5, color: 0.6 } },
  });
  vi.useFakeTimers({ shouldAdvanceTime: true });
  try {
    render(<ObjectPanel />);
    expect(getObjectMemory).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: '실시간 기억 관리' }));
    expect(await screen.findByRole('img', { name: '등록 모습 3s' })).toBeTruthy();
    expect(screen.getByRole('img', { name: 'AI 앵커 2s' })).toBeTruthy();
    expect(screen.getByRole('img', { name: '모양 기억' })).toBeTruthy();
    expect(screen.getByText(/놓친 지 1.5초/)).toBeTruthy();
    expect(getObjectMemory).toHaveBeenCalledWith(1);
    const calls = vi.mocked(getObjectMemory).mock.calls.length;
    await vi.advanceTimersByTimeAsync(1100);
    expect(vi.mocked(getObjectMemory).mock.calls.length).toBeGreaterThan(calls);
    fireEvent.click(screen.getByRole('button', { name: '실시간 기억 닫기' }));
    expect(screen.queryByRole('img', { name: '모양 기억' })).toBeNull();
  } finally {
    vi.useRealTimers();
  }
});

it('keeps the replaced (new id) object selected after another candidate, not the first one', async () => {
  const second = { ...object, id: 2, name: '두번째', candidates: 3 } as ObjectInfo;
  useApp.setState({ objects: [object, second], selectedId: 2 });
  vi.mocked(pickCandidate).mockResolvedValue({ ...second, id: 5, candidate_index: 1 });
  render(<ObjectPanel />);
  fireEvent.click(screen.getByRole('button', { name: '다른 분할 후보 (1/3)' }));
  await waitFor(() => expect(useApp.getState().selectedId).toBe(5));
  expect(useApp.getState().objects.map(o => o.id)).toEqual([1, 5]);
});

it('follows the replacement when the server state arrives before the candidate response', async () => {
  const second = { ...object, id: 2, name: '두번째', candidates: 3 } as ObjectInfo;
  useApp.setState({ objects: [object, second], selectedId: 2 });
  let resolve!: (o: ObjectInfo) => void;
  vi.mocked(pickCandidate).mockReturnValue(new Promise<ObjectInfo>(r => { resolve = r; }));
  render(<ObjectPanel />);
  fireEvent.click(screen.getByRole('button', { name: '다른 분할 후보 (1/3)' }));
  useApp.getState().setObjects([object, { ...second, id: 5 } as ObjectInfo]); // 10Hz 서버 상태가 응답보다 먼저 도착
  expect(useApp.getState().selectedId).toBe(5);
  resolve({ ...second, id: 5 } as ObjectInfo);
  await waitFor(() => expect(useApp.getState().replacingId).toBeNull());
  expect(useApp.getState().selectedId).toBe(5);
});

it('does not jump to the first object when the selected one is simply deleted', () => {
  useApp.setState({ objects: [object, { ...object, id: 2 } as ObjectInfo], selectedId: 2 });
  useApp.getState().setObjects([object]);
  expect(useApp.getState().selectedId).toBe(1);
});

it('keeps object memory open when another object is selected or its candidate changes', async () => {
  const { getObjectMemory } = await import('../api');
  vi.mocked(getObjectMemory).mockResolvedValue({
    id: 1, name: '물체 1', color: '#88f', state: 'tracking', lost_for_s: null, snapshots: [], shape: null, tier1: null,
    reacquire: { enabled: false, last: null, searches: 0, recovered: 0, thresholds: { iou: .72, hu: .5, color: .6 } },
  });
  useApp.setState({ memoryOpen: false, objects: [object, { ...object, id: 2, name: '두번째' } as ObjectInfo], selectedId: 1 });
  render(<ObjectPanel />);
  fireEvent.click(screen.getByRole('button', { name: '실시간 기억 관리' }));
  await screen.findByLabelText('물체 기억');
  fireEvent.click(screen.getByRole('tab', { name: '두번째' }));
  expect(screen.getByRole('button', { name: '실시간 기억 닫기' }).getAttribute('aria-pressed')).toBe('true');
  expect(await screen.findByLabelText('물체 기억')).toBeTruthy();
  expect(getObjectMemory).toHaveBeenLastCalledWith(2);
  fireEvent.click(screen.getByRole('button', { name: '실시간 기억 닫기' }));
  expect(screen.queryByLabelText('물체 기억')).toBeNull();
});

it('shows the spike-guard (EMA) toggle, on by default, and sends the choice', async () => {
  useApp.setState({ conn: 'open' });
  vi.mocked(getTracking).mockResolvedValue({ hand_occlusion: false, hands_available: false, ema: true });
  vi.mocked(putTracking).mockResolvedValue({ hand_occlusion: false, hands_available: false, ema: false });
  render(<ObjectPanel />);
  const box = await screen.findByRole('checkbox', { name: /튐 억제/ }) as HTMLInputElement;
  expect(box.checked).toBe(true);
  fireEvent.click(box);
  await waitFor(() => expect(putTracking).toHaveBeenCalledWith({ ema: false }));
  await waitFor(() => expect((screen.getByRole('checkbox', { name: /튐 억제/ }) as HTMLInputElement).checked).toBe(false));
});

it('deletes only the checked live memories (the registered view has no checkbox)', async () => {
  const mem = {
    id: 1, name: '물체 1', color: '#88f', state: 'tracking', lost_for_s: null,
    snapshots: [{ kind: 'registration', t: 0, age_s: 3, image: 'data:image/jpeg;base64,AA==', info: {} },
      { kind: 'anchor', t: 1.5, age_s: 2, image: 'data:image/jpeg;base64,AA==', info: {} },
      { kind: 'reacquired', t: 2.25, age_s: 1, image: 'data:image/jpeg;base64,AA==', info: {} }],
    shape: null, tier1: null, reacquire: { enabled: true, last: null, searches: 0, recovered: 0, thresholds: { iou: .72, hu: .5, color: .6 } },
  };
  vi.mocked(getObjectMemory).mockResolvedValue(mem as never);
  vi.mocked(forgetObjectMemory).mockResolvedValue({ ...mem, snapshots: [mem.snapshots[0]!, mem.snapshots[2]!], removed: 1 } as never);
  useApp.setState({ devMode: false });
  render(<ObjectPanel />);
  fireEvent.click(screen.getByRole('button', { name: '실시간 기억 관리' }));
  await screen.findByRole('img', { name: 'AI 앵커 2s' });
  expect(screen.queryByRole('checkbox', { name: /등록 모습/ })).toBeNull();
  const del = screen.getByRole('button', { name: /선택한 기억 삭제/ }) as HTMLButtonElement;
  expect(del.disabled).toBe(true);
  fireEvent.click(screen.getByRole('checkbox', { name: /AI 앵커 2초 전 선택/ }));
  fireEvent.click(screen.getByRole('button', { name: '선택한 기억 삭제 (1)' }));
  await waitFor(() => expect(forgetObjectMemory).toHaveBeenCalledWith(1, [{ kind: 'anchor', t: 1.5 }]));
  expect(await screen.findByText('1개를 지웠습니다.')).toBeTruthy();
});

it('shows each object as a photo card from its registered view', async () => {
  vi.mocked(getObjectThumbnail).mockResolvedValue({ id: 1, image: 'data:image/jpeg;base64,BB==' });
  useApp.setState({ devMode: false });
  render(<ObjectPanel />);
  const tab = screen.getByRole('tab', { name: '물체 1' });
  await waitFor(() => expect(tab.querySelector('img')?.getAttribute('src')).toBe('data:image/jpeg;base64,BB=='));
  expect(screen.getByText('좌우')).toBeTruthy();                        // 축 값은 기본 모드에서도 보인다
});

it('always offers a hand card with an illustration and a working enable switch', async () => {
  useApp.setState({ objects: [], conn: 'open', devMode: false, handInputEnabled: true });
  vi.mocked(getTracking).mockResolvedValue({ hand_input_enabled: true, hand_occlusion: false, hands_available: true });
  vi.mocked(putTracking).mockResolvedValue({ hand_input_enabled: false, hand_occlusion: false, hands_available: true });
  render(<ObjectPanel />);
  expect(screen.getByRole('img', { name: '맨손 그림' })).toBeTruthy();
  fireEvent.click(await screen.findByRole('button', { name: '활성화됨' }));
  await waitFor(() => expect(useApp.getState().handInputEnabled).toBe(false));
  expect(putTracking).toHaveBeenCalledWith({ hand_input_enabled: false });
  expect(screen.getByRole('button', { name: '비활성화됨' }).getAttribute('aria-pressed')).toBe('false');
});
