import { cleanup, render, screen, fireEvent } from '@testing-library/react';
import { afterEach, expect, it } from 'vitest';
import { Hud } from './Hud';
import { useApp } from '../store';
afterEach(cleanup);
it('adds a readable info tooltip to every advanced performance row', () => {
  useApp.setState({ devMode: true });
  const { container } = render(<Hud />);
  const rows = container.querySelectorAll('dl > div');
  expect(rows.length).toBe(17);
  for (const row of rows) expect(row.querySelector('.info')).not.toBeNull();
  fireEvent.mouseEnter(rows[5]!.querySelector('.info')!);
  expect(screen.getByRole('tooltip').textContent).toContain('p95');
});
it('keeps basic performance uncluttered and labels quantiles', () => {
  useApp.setState({ devMode: false });
  const { container } = render(<Hud />);
  expect(screen.getByText('p50 / p95')).toBeTruthy();
  expect(container.querySelector('dl .info')).toBeNull();
});
