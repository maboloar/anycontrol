import { ActionIcon } from "./ActionIcon";
import { useEffect, useState } from "react";
import type { Profile } from "../protocol";
import { t } from "../i18n";
export function ResetMappingsButton({ draft, edit }: { draft: Profile; edit: (p: Profile, immediate?: boolean) => void }) {
  const [armed, setArmed] = useState(false);
  const count = draft.mappings.length;
  useEffect(() => { setArmed(false); }, [count]);   // 매핑 개수가 바뀔 때만 확인 상태를 푼다 (같은 내용의 새 객체로는 풀리지 않게)
  useEffect(() => { if (!armed) return; const id = window.setTimeout(() => setArmed(false), 4000); return () => window.clearTimeout(id); }, [armed]);
  return <button type="button" className={`danger delete-all ${armed ? "armed" : ""}`} aria-live="polite" disabled={!draft.mappings.length} onBlur={() => setArmed(false)} onClick={() => {
    if (!armed) { setArmed(true); return; }
    edit({ ...draft, mappings: [] }, true); setArmed(false);
  }}><ActionIcon name="trash" />{armed ? t("정말 전체 초기화? 한 번 더 누르세요", "Reset all? Press again") : t("매핑 전체 초기화", "Reset all mappings")}</button>;
}
