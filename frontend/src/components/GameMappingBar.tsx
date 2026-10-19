import type { ReactNode } from "react";
import { GAME_AXES, gameFns, requiredControls } from "../gameFunctions";
import { sensitivity, withSensitivity } from "../mappingSensitivity";
import { useEffect, useState } from "react";
import { useMappingDraft, useDraftStore } from "../mappingDraft";
import { useApp } from "../store";
import { buildGameMapping, mappingWarning, useGameMappingView } from "../gameMapping";
import type { GameId, GameStyle } from "../gameFunctions";
import { t } from "../i18n";
import { objectLabel } from "../objectRefs";
export function useGameMapping(game: GameId, players: number) {
  const { draft, edit, err } = useMappingDraft();
  const objects = useApp(s => s.objects), handEnabled = useApp(s => s.handInputEnabled), conn = useApp(s => s.conn);
  const [style, setStyle] = useState<GameStyle>(game === "race" ? "x" : "depth");
  const [chosen, choose] = useState<string[]>([]), [error, setError] = useState("");
  const refs = objects.filter(o => o.kind !== "pen").map(o => `#${o.id}`);
  const sources = Array.from({ length: players }, (_, i) => chosen[i] ?? refs[i] ?? (i === 0 && handEnabled ? "@hand" : ""));
  useEffect(() => { useGameMappingView.getState().setGame(game); }, [game]);
  const check = () => mappingWarning(useDraftStore.getState().draft, game, players, useApp.getState().objects, useApp.getState().handInputEnabled);
  const options: [GameStyle, string][] = game === "race" ? [["x", t("좌우 이동으로 조향", "Steer by moving sideways")], ["angle", t("기울기로 조향", "Steer by tilting")]]
    : [["depth", t("바닥에 놓고 · 크기/앞뒤로 상하", "On desk · size/near-far for Y")], ["y", t("들고 · 영상 위아래로 상하", "Held up · video up/down for Y")]];
  const channels = new Set(gameFns(game).filter(f => f.control && (requiredControls(game, players).includes(f.control) || game === "race" && players === 1)).map(f => GAME_AXES[f.control!]));
  const relevant = (m: NonNullable<typeof draft>["mappings"][number]) => m.output.target === "gamepad_axis" && channels.has(m.output.axis);
  const values = draft?.mappings.filter(relevant).map(sensitivity) ?? [];
  const sens = values.length ? values.reduce((a, b) => a + b, 0) / values.length : 1;
  const mixed = values.some(v => Math.abs(v - sens) > .05);
  const bar = (actions: ReactNode) => <section className="game-mapping" data-tour="automap" aria-label={t("게임 자동 매핑", "Game auto-mapping")}>
    <div className="row"><label>{t("조작법", "Controls")} <select aria-label={t("자동 매핑 조작법", "Auto-map control style")} value={style} onChange={e => setStyle(e.target.value as GameStyle)}>{options.map(([v, text]) => <option key={v} value={v}>{text}</option>)}</select></label>
      {sources.map((ref, i) => <label key={i}>{players > 1 ? `${i + 1}P` : t("컨트롤러", "Controller")} <select aria-label={`${i + 1}P ${t("컨트롤러", "controller")}`} value={ref} onChange={e => { const next = [...sources]; next[i] = e.target.value; choose(next); }}>
        <option value="">{t("선택하세요", "Select")}</option>{refs.map(ref => <option key={ref} value={ref}>{objectLabel(ref, objects)}</option>)}{handEnabled && <option value="@hand">{t("맨손 (영상 XY)", "Bare hand (video XY)")}</option>}
      </select></label>)}
      <button type="button" className="act-config" disabled={!draft || conn !== "open"} onClick={() => { try { edit(buildGameMapping(useDraftStore.getState().draft!, game, players, style, sources), true); setError(""); } catch (e) { setError(String(e instanceof Error ? e.message : e)); } }}>{t("자동 매핑", "Auto-map")}</button>
      <label className="game-sensitivity">{t("민감도", "Sensitivity")} {`×${sens.toFixed(1)}`} {mixed && t("(축별 설정)", "(mixed axes)")}
        <input type="range" aria-label={t("게임 민감도", "Game sensitivity")} min="0.3" max="4" step="0.1" value={Math.max(.3, Math.min(4, sens))} disabled={!values.length} onChange={e => { const p = useDraftStore.getState().draft; if (p) edit({ ...p, mappings: p.mappings.map(m => relevant(m) ? withSensitivity(m, sensitivity(m) * Number(e.target.value) / sens) : m) }); }} />
      </label>
      {actions}
    </div>
    <p className="small muted">{t("자동 매핑은 가상 게임패드 축 연결을 선택한 프리셋으로 교체합니다. 민감도는 모든 조작 축을 함께 조절하며 축별 비율·방향은 유지합니다. 매핑 패널의 수정도 게임 중 반영됩니다.", "Auto-map replaces virtual gamepad axis connections with the selected preset. Sensitivity adjusts all control axes together and keeps their relative tuning and directions. Mapping edits also apply during play.")}</p>
    {(error || err) && <p role="alert" className="error small">{error || err}</p>}
    {mappingWarning(draft, game, players, objects, handEnabled) && <p className="warn small">{t("연결 대기 · 자동 매핑을 누르세요", "Not connected · press Auto-map")}</p>}
  </section>;
  return { bar, check };
}
