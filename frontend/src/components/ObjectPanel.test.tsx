import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { ObjectPanel } from './ObjectPanel';
import { pickCandidate, renameObject } from '../api';
import { useApp } from '../store';
import type { ObjectInfo } from '../protocol';
vi.mock('../api', () => ({ getTracking: vi.fn(), putTracking: vi.fn(), deleteObject: vi.fn(), setNeutral: vi.fn(), pickCandidate: vi.fn(), renameObject: vi.fn() }));
const object = { id: 1, name: '물체 1', kind: 'object', color: '#88f', state: 'tracking', confidence: .9,
  axes: { x: 0, y: 0, depth: 0, angle: 0, stretch: 0, contact: 0 }, texture: .5, contrast: .5, warnings: [], candidates: 3, candidate_index: 0, box: null, contour: [], debug: {} } as ObjectInfo;
beforeEach(() => { vi.resetAllMocks(); localStorage.clear(); useApp.setState({ conn: 'closed', objects: [object], selectedId: 1 }); });
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
it.each(['object', 'pen'] as const)('edits a %s name by clicking its tab, saving on blur and cancelling with Escape', async kind => {
  useApp.setState({ objects: [{ ...object, kind }] });
  vi.mocked(renameObject).mockResolvedValue({ ...object, kind, name: '내 컨트롤러' });
  render(<ObjectPanel />);
  fireEvent.click(screen.getByRole('tab', { name: '물체 1' }));
  const input = screen.getByRole('textbox', { name: kind === 'pen' ? '펜 이름' : '물체 이름' });
  fireEvent.change(input, { target: { value: ' 내 컨트롤러 ' } }); fireEvent.blur(input);
  await waitFor(() => expect(useApp.getState().objects[0]?.name).toBe('내 컨트롤러'));
  expect(renameObject).toHaveBeenCalledWith(1, '내 컨트롤러');
  fireEvent.click(screen.getByRole('tab', { name: '내 컨트롤러' }));
  const again = screen.getByRole('textbox');
  fireEvent.change(again, { target: { value: '취소할 이름' } }); fireEvent.keyDown(again, { key: 'Escape' });
  expect(screen.queryByRole('textbox')).toBeNull();
  expect(renameObject).toHaveBeenCalledTimes(1);
});
