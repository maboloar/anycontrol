import { Panel } from "./Panel";
import { useEffect, useState } from "react";
import { connection } from "../connection";
import type { FrameState, GamepadAxis, GamepadButton } from "../protocol";

export interface PadState {
  axes: Record<GamepadAxis, number>;
  buttons: Record<GamepadButton, boolean>;
  keys: string[];
  /** true: 실제로 내보낸 값, false: 보기만 모드에서 계산만 한 값 */
  sent: boolean;
}

export const ZERO: PadState = {
  axes: { left_x: 0, left_y: 0, right_x: 0, right_y: 0, lt: 0, rt: 0 },
  buttons: { a: false, b: false, x: false, y: false, lb: false, rb: false, back: false, start: false, ls: false,
    rs: false, up: false, down: false, left: false, right: false, home: false },
  keys: [],
  sent: false,
};

export function padFromState(s: FrameState): PadState {
  const c = s.controller;
  if (c?.mode === "send") return { axes: c.axes, buttons: c.buttons, keys: c.keys, sent: true };
  return s.mapping ? { ...s.mapping.computed, sent: false } : ZERO;
}

/** 매 상태 메시지마다 게임패드 값을 받는다 (60Hz 애니메이션을 React 패널 갱신 주기와 분리). */
export function usePad(): PadState {
  const [pad, setPad] = useState<PadState>(ZERO);
  useEffect(
    () =>
      connection.onMessage((type, data) => {
        if (type !== "state") return;
        setPad(padFromState(data as unknown as FrameState));
      }),
    [],
  );
  return pad;
}

/** 가상 Xbox 패드 (W3C standard 레이아웃). 보기만 모드에서는 흐리게 표시한다. */
export function GamepadView({ pad, compact = false }: { pad: PadState; compact?: boolean }) {
  const a = pad.axes;
  const b = pad.buttons;
  const stick = (cx: number, cy: number, x: number, y: number, pressed: boolean, label: string) => (
    <g aria-label={label}>
      <circle cx={cx} cy={cy} r={26} className="pad-well" />
      <circle cx={cx + x * 16} cy={cy + y * 16} r={15} className={`pad-stick ${pressed ? "on" : ""}`} />
    </g>
  );
  const face = (cx: number, cy: number, on: boolean, label: string, color: string) => (
    <g>
      <circle cx={cx} cy={cy} r={11} fill={on ? color : "#2a3240"} stroke={color} strokeWidth={2} />
      <text x={cx} y={cy + 4} textAnchor="middle" className="pad-label">{label}</text>
    </g>
  );
  const trig = (x: number, v: number, label: string) => (
    <g>
      <rect x={x} y={6} width={60} height={12} rx={4} className="pad-well" />
      <rect x={x} y={6} width={60 * v} height={12} rx={4} className="pad-fill" />
      <text x={x + 30} y={30} textAnchor="middle" className="pad-label">{label} {v.toFixed(2)}</text>
    </g>
  );
  const dpad = (cx: number, cy: number) => (
    <g>
      {([["up", 0, -14], ["down", 0, 14], ["left", -14, 0], ["right", 14, 0]] as const).map(([k, dx, dy]) => (
        <rect key={k} x={cx + dx - 7} y={cy + dy - 7} width={14} height={14} rx={2}
          className={`pad-dpad ${b[k] ? "on" : ""}`} />
      ))}
    </g>
  );
  const view = (
    <figure className={`gamepad ${pad.sent ? "" : "ghost"}`} aria-label="가상 게임패드">
      <svg viewBox="0 0 320 190" role="img" aria-label={describe(pad)}>
        {trig(20, a.lt, "LT")}
        {trig(240, a.rt, "RT")}
        <rect x={30} y={36} width={60} height={10} rx={5} className={`pad-bumper ${b.lb ? "on" : ""}`} />
        <rect x={230} y={36} width={60} height={10} rx={5} className={`pad-bumper ${b.rb ? "on" : ""}`} />
        <path d="M60 52 Q160 38 260 52 Q312 60 305 130 Q298 185 250 170 Q215 158 200 140 L120 140 Q105 158 70 170 Q22 185 15 130 Q8 60 60 52 Z"
          className="pad-body" />
        {stick(80, 92, a.left_x, a.left_y, b.ls, "왼쪽 스틱")}
        {stick(200, 132, a.right_x, a.right_y, b.rs, "오른쪽 스틱")}
        {dpad(120, 132)}
        {face(250, 110, b.a, "A", "#57cc99")}
        {face(272, 88, b.b, "B", "#ff5d73")}
        {face(228, 88, b.x, "X", "#4ea8de")}
        {face(250, 66, b.y, "Y", "#ffd166")}
        <circle cx={145} cy={82} r={6} className={`pad-small ${b.back ? "on" : ""}`} />
        <circle cx={175} cy={82} r={6} className={`pad-small ${b.start ? "on" : ""}`} />
        <circle cx={160} cy={66} r={8} className={`pad-small ${b.home ? "on" : ""}`} />
      </svg>
      <figcaption className="small">
        {pad.sent ? "내보내는 중" : "보기만 (출력 안 함)"} · 키 {pad.keys.length ? pad.keys.join(" + ") : "없음"}
      </figcaption>
    </figure>
  );
  return compact ? view : <Panel title="가상 게임패드" label="게임패드 패널" className="pad-panel">{view}</Panel>;
}

function describe(p: PadState): string {
  const on = Object.entries(p.buttons).filter(([, v]) => v).map(([k]) => k.toUpperCase());
  return `왼쪽 스틱 ${p.axes.left_x.toFixed(2)}, ${p.axes.left_y.toFixed(2)} · 트리거 ${p.axes.lt.toFixed(2)}/${p.axes.rt.toFixed(2)} · 버튼 ${on.join(", ") || "없음"}`;
}
