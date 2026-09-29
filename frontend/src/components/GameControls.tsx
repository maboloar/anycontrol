import { ActionIcon } from "./ActionIcon";
import { useState } from 'react';
import { requestGameSetup, setNeutral } from '../api';
import { preset } from '../mapping';
import { useApp } from '../store';
import { GamepadView, ZERO } from './GamepadView';

export type GameControlMode = 'position' | 'joystick' | 'race-stick' | 'racing';
/** 게임 로직과 별개로 10Hz 상태를 표시한다. 게임 프레임마다 React를 갱신하지 않는다. */
export function GameControls({ mode, onMode }: { mode: GameControlMode; onMode: (mode: GameControlMode) => void }) {
  const objects = useApp(s => s.objects), selected = useApp(s => s.selectedId);
  const live = useApp(s => s.live), connected = useApp(s => s.conn === 'open');
  const desk = useApp(s => s.calibration?.mode);
  const [busy, setBusy] = useState(false), [err, setErr] = useState('');
  const c = live.controller;
  const pad = connected && c?.mode === 'send' ? { ...c, sent: true } : live.mapping ? { ...live.mapping.computed, sent: false } : ZERO;
  const object = objects.find(o => o.id === selected);
  const setup = async () => {
    if (!object) return;
    setBusy(true); setErr('');
    try {
      const profile = preset(mode === 'position' ? 'zombie' : mode, object.name, desk === 'quad');
      const result = await requestGameSetup(object.id, mode === 'position', profile);
      useApp.getState().setMouseInfo(result.mouse);
      useApp.getState().setMappingInfo(result.mapping);
    } catch (e) { setErr(String(e)); } finally { setBusy(false); }
  };
  const mouse = live.mouse;
  return <aside className="game-controls" aria-label="게임 입력 설정">
    <label>조작 방식<select aria-label="게임 조작 방식" value={mode} onChange={e => onMode(e.target.value as GameControlMode)}>
      {mode === 'position' || mode === 'joystick' ? <><option value="position">위치 대응 (기본)</option><option value="joystick">조이스틱 이동</option></> : <><option value="race-stick">물체 좌우로 조향 (기본)</option><option value="racing">물체 회전으로 조향</option></>}
    </select></label>
    <label>추적 물체<select aria-label="게임 추적 물체" value={selected ?? ''} onChange={e => useApp.getState().select(Number(e.target.value))}>
      {!objects.length && <option value="">영상에서 물체를 등록하세요</option>}
      {objects.map(o => <option key={o.id} value={o.id}>{o.name}</option>)}
    </select></label>
    <button type="button" className="act-go" disabled={busy || !object || !connected} onClick={() => void setup()}><ActionIcon name="link" />이 물체로 게임 연결</button>
    {mode !== 'position' && <button type="button" className="act-config" disabled={!object || busy || !connected} onClick={() => { if (object) void setNeutral(object.id).catch(e => setErr(String(e))); }}><ActionIcon name="target" />현재 위치를 중립으로</button>}
    <p className="small muted">{mode === 'position' ? '물체 마우스 커서 위치에 캐릭터가 대응합니다. 연결하면 화면 XY 절대 위치를 사용합니다. 마우스 패널에서 입력 범위·반전을 조절할 수 있습니다.' : '중립에서 움직인 거리만큼 부드럽게 조작합니다. 매핑 탭에서 범위·감도·반전을 조절할 수 있습니다.'}</p>
    <p className="small muted">연결 버튼은 가상 출력으로 전환하고 게임용 매핑을 적용합니다. 기존 매핑이 필요하면 매핑 탭에서 먼저 저장하세요.</p>
    {mode === 'position' && <div className="position-monitor" aria-label="실시간 위치 컨트롤러">
      <span className={mouse?.cursor_active && connected ? 'cursor-dot' : 'cursor-dot inactive'} style={{ left: `${Math.max(0, Math.min(1, mouse?.x ?? .5)) * 100}%`, top: `${Math.max(0, Math.min(1, mouse?.y ?? .5)) * 100}%` }} />
      <span className="small">{!connected ? '연결 끊김' : mouse?.mode === 'off' || !mouse ? '물체 연결 필요' : mouse.cursor_active ? '위치 대응 중' : '추적 대기'}</span>
    </div>}
    <GamepadView pad={pad} compact />
    {err && <p className="error">{err}</p>}
  </aside>;
}
