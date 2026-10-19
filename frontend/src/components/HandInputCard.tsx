import { useEffect, useState } from "react";
import { getTracking, putTracking } from "../api";
import { useApp } from "../store";
import { t } from "../i18n";
import { PatchJack } from "./PatchCables";
export function HandInputCard() {
  const enabled = useApp(s => s.handInputEnabled), conn = useApp(s => s.conn);
  const [busy, setBusy] = useState(false), [err, setErr] = useState("");
  useEffect(() => { let alive = true; if (conn === "open") getTracking().then(i => { if (alive) useApp.setState({ handInputEnabled: i?.hand_input_enabled !== false }); }, e => { if (alive) setErr(String(e)); }); return () => { alive = false; }; }, [conn]);
  return <div className={`hand-input-card ${enabled ? "on" : ""}`}>
    <svg viewBox="0 0 80 80" width="52" height="52" fill="none" aria-label={t("맨손 그림", "Hand illustration")} role="img">
      <path d="M25 41V20c0-7 9-7 9 0v18-25c0-7 9-7 9 0v25-20c0-7 9-7 9 0v23-13c0-7 9-7 9 0v24c0 15-9 23-22 23-9 0-15-6-20-15L9 44c-4-7 4-12 9-6l7 8" fill="#c8d9f4" stroke="#5684c6" strokeWidth="3" strokeLinejoin="round" />
    </svg>
    <div><b>{t("맨손 매핑", "Hand mapping")}</b><small>{t("이동 XY · 집게 매핑", "XY motion / pinch mapping")}</small></div>
    <button type="button" title={t("잭 매핑에만 적용 · 물체 터치와 맨손 마우스는 별도", "Affects hand jack mappings only; object touch and hand mouse are independent")} aria-pressed={enabled} disabled={busy || conn !== "open"} onClick={async () => {
      setBusy(true); try { const i = await putTracking({ hand_input_enabled: !enabled }); useApp.setState({ handInputEnabled: i?.hand_input_enabled !== false }); setErr(""); }
      catch (e) { setErr(String(e)); } finally { setBusy(false); }
    }}>{enabled ? t("활성화됨", "Enabled") : t("비활성화됨", "Disabled")}</button>
    <PatchJack side="obj" name="@hand" color="#8aafff" />
    {err && <span role="alert" className="error small">{err}</span>}
  </div>;
}
