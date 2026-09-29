import { afterEach, beforeEach, expect, it } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { DisplayControls } from './DisplayControls';
import { Panel } from './Panel';

beforeEach(() => { localStorage.clear(); document.documentElement.style.fontSize = ''; });
afterEach(cleanup);
it('resets active and unmounted window sizes without clearing input settings', () => {
  localStorage.setItem('anycontrol.panel.설정.size', JSON.stringify({ width: 300, height: 210 }));
  localStorage.setItem('anycontrol.panel.데모.size', JSON.stringify({ width: 500, height: 320 }));
  localStorage.setItem('anycontrol.input.preference', 'keep');
  render(<><DisplayControls /><Panel title="설정">내용</Panel></>);
  expect(screen.getByRole('region', { name: '설정' }).style.width).toBe('300px');
  fireEvent.click(screen.getByRole('button', { name: '화면 초기화' }));
  expect(screen.getByRole('region', { name: '설정' }).style.width).toBe('');
  expect(localStorage.getItem('anycontrol.panel.데모.size')).toBeNull();
  expect(localStorage.getItem('anycontrol.input.preference')).toBe('keep');
});
it('changes persistent font size and restores minimized panels with display defaults', () => {
  localStorage.setItem('anycontrol.panel.설정', 'collapsed');
  render(<><DisplayControls /><Panel title="설정">내용</Panel></>);
  fireEvent.click(screen.getByRole('button', { name: '글씨 크게' }));
  expect(document.documentElement.style.fontSize).toBe('15px');
  expect(localStorage.getItem('anycontrol.font-size')).toBe('15');
  fireEvent.click(screen.getByRole('button', { name: '글씨 작게' }));
  expect(document.documentElement.style.fontSize).toBe('14px');
  fireEvent.click(screen.getByRole('button', { name: '화면 초기화' }));
  expect(screen.getByRole('button', { name: '설정 최소화' })).toBeTruthy();
  expect(document.documentElement.style.fontSize).toBe('14px');
});
