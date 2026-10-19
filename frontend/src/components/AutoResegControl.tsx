import { useEffect, useState } from "react";
import { getAutoReseg, putAutoReseg, type AutoResegInfo } from "../api";
import { useApp } from "../store";
import { Info } from "./Info";
import { t } from "../i18n";

/** 개발자 모드: 자동 분할 재지정 켜기·끄기와 '오래 가만히 있음' 시간(초). 모든 일반 물체에 공통 (펜 제외). */
export function AutoResegControl() {
  const devMode = useApp((s) => s.devMode);
  const conn = useApp((s) => s.conn);
  const [info, setInfo] = useState<AutoResegInfo | null>(null);
  const [draft, setDraft] = useState("");
  const [err, setErr] = useState("");
  useEffect(() => {
    if (!devMode || conn !== "open") return;
    Promise.resolve(getAutoReseg()).then((i) => { if (i) { setInfo(i); setDraft(String(i.long_s)); } }, (e) => setErr(String(e)));
  }, [devMode, conn]);
  if (!devMode) return null;
  const save = async (body: Partial<AutoResegInfo>) => {
    try { const i = await putAutoReseg(body); setInfo(i); setDraft(String(i.long_s)); setErr(""); }
    catch (e) { setErr(String(e)); }
  };
  const commit = () => {
    const v = Number(draft);
    if (!Number.isFinite(v) || v < 3 || v > 600) { setErr(t("3~600초 사이로 입력하세요.", "Enter 3–600 seconds.")); return; }
    if (info && v !== info.long_s) void save({ long_s: v });
  };
  return <div className="row small dev-row">
    <label className="dev-check">
      <input type="checkbox" checked={!!info?.enabled} disabled={!info} onChange={(e) => void save({ enabled: e.target.checked })} />
      {t("자동 분할 재지정", "Auto re-segmentation")}
    </label>
    <label className="dev-check">{t("오래 정지 기준", "Long stillness")}
      <input type="number" min={3} max={600} step={1} value={draft} disabled={!info} style={{ width: "4.5em" }}
        aria-label={t("오래 정지 기준 (초)", "Long stillness (seconds)")}
        onChange={(e) => setDraft(e.target.value)} onBlur={commit}
        onKeyDown={(e) => { if (e.key === "Enter") commit(); }} />{t("초", "s")}
    </label>
    <Info>{t("놓쳤다가 다시 잡은 뒤 1초 가만히 있으면, 그리고 이 시간만큼 계속 가만히 있을 때마다 지금 화면에서 물체를 다시 분할합니다 (다시 선택과 같음: 이름·매핑·마우스 연결 유지). 모든 일반 물체에 공통이고 펜에는 쓰지 않습니다.",
      "After the object is re-found and stays still for 1 s, and every time it stays still this long, it is re-segmented in the current frame (like Reselect: name, mappings and mouse link kept). Applies to all regular objects, not pens.")}</Info>
    {err && <span className="error">{err}</span>}
  </div>;
}
