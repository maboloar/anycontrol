import { useEffect, useState } from "react";
import { getTouchSettings, putTouchSettings, type TouchSettings } from "../api";
import { t } from "../i18n";
import { useApp } from "../store";
import { Info } from "./Info";

/** 터치 민감도 슬라이더. kind=object: 물체 터치(손 영역에서 얼마나 모습이 바뀌어야 닿음), grid: 바닥 터치(손끝이 바닥에 얼마나 가까워야 닿음). */
export function TouchSensitivity({ kind = "object" }: { kind?: "object" }) {
  const conn = useApp((s) => s.conn);
  const [st, setSt] = useState<TouchSettings | null>(null);
  useEffect(() => { if (conn === "open") Promise.resolve(getTouchSettings()).then((r) => r && setSt(r), () => undefined); }, [conn]);
  if (!st) return null;
  const key = "object_sensitivity";
  void kind;
  const v = st[key];
  return (
    <label className="touch-sens small">
      {t("물체 터치 민감도", "Object touch sensitivity")} {Math.round(v * 100)}%
      <input type="range" min={0} max={1} step={0.05} value={v}
        onChange={(e) => { const n = Number(e.target.value); setSt({ ...st, [key]: n }); void putTouchSettings({ [key]: n }).then(setSt, () => undefined); }} />
      <Info>{t("물체를 계속 지켜보다가 물체 앞에 손이 나타나 모습이 바뀌면 닿음으로 봅니다(물체 뒤로 간 손·다른 물건·조명 변화는 무시). 화면에 손이 인식되고 손바닥·손가락 옆면 등 손 영역이 물체에 겹쳐야 합니다. 맨손 잭 활성화와는 무관합니다. 고급 모드의 터치 감지 표시 토글로 진단 영역과 변화 막대를 볼 수 있습니다. 높이면 조금만 가려도 닿습니다.", "Watches the object and counts a touch when a hand appears in front of it and changes its look (a hand behind it, other things and lighting changes are ignored). A detected palm, finger side or other hand area must overlap the object. This is independent of the hand jack switch. Enable Touch diagnostics in advanced mode to see the watched area and change bar. Higher = a little cover is enough.")}</Info>
    </label>
  );
}
