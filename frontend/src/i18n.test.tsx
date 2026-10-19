import { afterEach, beforeEach, expect, it } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { DisplayControls } from './components/DisplayControls';
import { Panel } from './components/Panel';
import { getLang, LANG_KEY, setLang, t, useLang } from './i18n';
import { sv } from './serverText';

beforeEach(() => { localStorage.clear(); setLang('ko'); });
afterEach(() => { cleanup(); setLang('ko'); });

function Demo() {
  useLang();
  return <><DisplayControls /><Panel title={t('카메라', 'Camera')} label="카메라">{t('내용', 'Body')}</Panel></>;
}

it('defaults to Korean and switches to English from the globe menu', () => {
  render(<Demo />);
  expect(getLang()).toBe('ko');
  expect(screen.getByRole('region', { name: '카메라' })).toBeTruthy();
  fireEvent.click(screen.getByRole('button', { name: '언어 선택' }));
  fireEvent.click(screen.getByRole('menuitemradio', { name: 'English' }));
  expect(getLang()).toBe('en');
  expect(localStorage.getItem(LANG_KEY)).toBe('en');
  expect(document.documentElement.lang).toBe('en');
  expect(screen.getByRole('region', { name: 'Camera' }).textContent).toContain('Body');
  expect(screen.getByRole('button', { name: 'Reset layout' })).toBeTruthy();
});

it('keeps panel storage keys stable across languages', () => {
  setLang('en');
  render(<Demo />);
  fireEvent.click(screen.getByRole('button', { name: 'Camera collapse' }));
  expect(localStorage.getItem('anycontrol.panel.카메라')).toBe('collapsed');
});

it('translates server messages only in English', () => {
  const msg = '중앙에서 준비하세요. 측정 시작 후 0.5초 기다렸다가 손바닥을 카메라 쪽으로 10–15cm 움직이고 끝 위치를 유지하세요. 검지는 책상에 대고 움직이세요.';
  expect(sv(msg)).toBe(msg);
  setLang('en');
  expect(sv(msg)).toBe('Start at the center. After starting, wait 0.5s, then move your palm toward the camera 10–15cm and hold the end position. Keep your index finger on the desk while moving.');
  expect(sv('물체는 최대 6개까지 등록할 수 있습니다.')).toBe('You can register up to 6 objects.');
  expect(sv('건너뛴 검사: 떨림 확인, 스크롤 확인')).toBe('Skipped checks: Jitter check, Scroll check');
  expect(sv('unknown message')).toBe('Unknown message');
});

it('translates the simplified calibration instructions without requiring a center return', () => {
  setLang('en');
  const msg = '물체를 잘 보이는 편한 위치에 두고 잠깐 멈추세요. 화면 중앙에 맞출 필요는 없어요. 손가락은 집지 말고 편하게 펴세요.';
  expect(sv(msg)).toContain('No need to center');
  expect(sv(msg)).not.toMatch(/[가-힣]/);
  expect(sv('좌우로 움직이기')).toBe('Sweep left and right');
});
