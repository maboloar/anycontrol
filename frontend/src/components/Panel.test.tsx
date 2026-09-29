import { useState } from 'react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { Panel } from './Panel';

beforeEach(() => localStorage.clear());
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });
function Child() {
  const [value, setValue] = useState(0);
  return <button onClick={() => setValue(value + 1)}>내용 {value}</button>;
}
it('keeps child state mounted when reduced to the title row and expanded', () => {
  render(<Panel title="설정"><Child /></Panel>);
  fireEvent.click(screen.getByRole('button', { name: '내용 0' }));
  fireEvent.click(screen.getByRole('button', { name: '설정 최소화' }));
  expect(screen.queryByRole('button', { name: '내용 1' })).toBeNull();
  expect(screen.getByText('내용 1')).toBeTruthy();
  expect(localStorage.getItem('anycontrol.panel.설정')).toBe('collapsed');
  fireEvent.click(screen.getByRole('button', { name: '설정 펼치기' }));
  expect(screen.getByRole('button', { name: '내용 1' })).toBeTruthy();
});
it('restores the minimized preference on the next mount', () => {
  localStorage.setItem('anycontrol.panel.설정', 'collapsed');
  render(<Panel title="설정"><Child /></Panel>);
  expect(screen.getByRole('button', { name: '설정 펼치기' }).getAttribute('aria-expanded')).toBe('false');
});

it('persists resized dimensions, hides the grip while minimized and resets with Home', () => {
  localStorage.setItem('anycontrol.panel.설정.size', JSON.stringify({ width: 300, height: 210 }));
  render(<Panel title="설정"><Child /></Panel>);
  const panel = screen.getByLabelText('설정');
  expect(panel.style.width).toBe('300px'); expect(panel.style.height).toBe('210px');
  fireEvent.click(screen.getByRole('button', { name: '설정 최소화' }));
  expect(panel.style.height).toBe(''); expect(screen.queryByRole('button', { name: '설정 크기 조절' })).toBeNull();
  fireEvent.click(screen.getByRole('button', { name: '설정 펼치기' }));
  expect(panel.style.height).toBe('210px');
  fireEvent.keyDown(screen.getByRole('button', { name: '설정 크기 조절' }), { key: 'Home' });
  expect(panel.style.width).toBe(''); expect(localStorage.getItem('anycontrol.panel.설정.size')).toBeNull();
});

it('drags panel boundaries along one axis and preserves contents and saved dimensions', () => {
  vi.stubGlobal('PointerEvent', MouseEvent);
  render(<Panel title="설정"><Child /></Panel>);
  const panel = screen.getByLabelText('설정');
  vi.spyOn(panel, 'getBoundingClientRect').mockReturnValue({ width: 300, height: 210 } as DOMRect);
  fireEvent.click(screen.getByRole('button', { name: '내용 0' }));
  const bottom = screen.getByRole('button', { name: '설정 아래쪽 경계 크기 조절' });
  fireEvent.pointerDown(bottom, { button: 0, clientX: 100, clientY: 200 });
  fireEvent.pointerMove(bottom, { clientX: 160, clientY: 280 });
  fireEvent.pointerUp(bottom);
  expect(panel.style.width).toBe('300px'); expect(panel.style.height).toBe('290px');
  const left = screen.getByRole('button', { name: '설정 왼쪽 경계 크기 조절' });
  fireEvent.pointerDown(left, { button: 0, clientX: 100, clientY: 200 });
  fireEvent.pointerMove(left, { clientX: 50, clientY: 300 });
  fireEvent.pointerUp(left);
  expect(panel.style.width).toBe('350px'); expect(panel.style.height).toBe('210px');
  expect(JSON.parse(localStorage.getItem('anycontrol.panel.설정.size')!)).toEqual({ width: 350, height: 210 });
  expect(screen.getByRole('button', { name: '내용 1' })).toBeTruthy();
});
