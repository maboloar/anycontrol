import { ActionIcon } from "./ActionIcon";
import { t } from "../i18n";

/** 게임 공통 버튼 줄: 시작/계속·일시정지, 처음부터, 상태 문구. Space 로도 일시정지·계속. */
export function GameButtons({ s, over, status, startLabel, children }: {
  s: { warning?: string; paused: boolean; play: (restart?: boolean) => void; pause: () => void };
  over: boolean; status: React.ReactNode; startLabel?: string; children?: React.ReactNode;
}) {
  return <div className="row game-actions">
    <button type="button" className={s.paused || over ? "act-go" : "act-pause"} onClick={() => s.paused || over ? s.play() : s.pause()}>
      <ActionIcon name={s.paused || over ? 'play' : 'pause'} />{over ? t('다시 도전', 'Try again') : s.paused ? (startLabel ?? t('시작 / 계속', 'Start / Resume')) : t('일시정지 (Space)', 'Pause (Space)')}</button>
    <button type="button" className="act-reset" onClick={() => s.play(true)}><ActionIcon name="reset" />{t("처음부터", "Restart")}</button>
    {s.warning && <p className="warn" role="alert">{s.warning}</p>}
    {children}
    {(!s.paused || over) && <span className="small" role="status">{status}</span>}
    
  </div>;
}
