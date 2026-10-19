import { useEffect, useRef, useState, type ReactNode } from "react";
import { useApp } from "../store";
import { placeCard, unionBox, type Box, type Side } from "../tutorial";
import { CameraBuddy } from "./CameraBuddy";
import { t } from "../i18n";
import { useDraftStore } from "../mappingDraft";
import { cables } from "../patch";

type Goal = "object" | "mapping" | "demo" | "automap";
interface Step {
  id: string;
  /** 가리킬 요소의 data-tour 이름들 (여러 개면 모두 감싼다). 비우면 가운데 카드만 */
  targets: string[];
  title: string;
  body: ReactNode;
  /** 따라 하기 단계: 사용자가 이걸 해내면 초록으로 바뀌고 자동으로 다음 단계로 간다 (그동안 화면을 가리지 않는다) */
  goal?: Goal;
  /** 따라 하기 단계에서 할 일 한 줄 */
  task?: string;
  /** 가리킬 요소들을 하나의 상자로 묶어 강조 */
  merge?: boolean;
  /** 직접 해 보는 단계: [다음]에 초점을 두지 않고 키보드(Space·화살표)를 앱에 넘긴다 */
  free?: boolean;
}

/** 튜토리얼: 물체 등록 → 확인 → 매핑 → 데모 고르기 → 자동 매핑까지 직접 따라 해 보고, 나머지를 짧게 알려 준다. */
export const STEPS: Step[] = [
  { id: "hello", targets: [], title: "안녕하세요! AnyControl을 소개해 드릴게요",
    body: <>카메라로 책상 위 <b>물체·펜·맨손</b>의 움직임을 읽어서 마우스·키보드·게임패드 입력으로 바꿔 드려요.
      물체를 하나 등록해서 게임까지 직접 해 보면서 하나씩 짚어 볼게요. 금방 끝나요.</> },
  { id: "caution", targets: [], title: "시작 전에 딱 두 가지",
    body: <ul>
      <li>macOS가 <b>카메라·손쉬운 사용 권한</b>을 물으면 허용해 주세요. (<b>macOS</b> · <b>iPhone 연속성 카메라</b>가 가장 정확해요)</li>
      <li>뭔가 이상하면 <b>ESC</b>를 누르면 모든 입력이 바로 멈춰요.</li>
    </ul> },
  { id: "object", targets: ["camera"], goal: "object", title: "1. 물건 하나 등록하기",
    task: "영상 속 물건을 마우스로 꾹 눌러 네모로 감싸 주세요",
    body: <>책상 위에 <b>컵·지갑·필통</b>처럼 단단한 물건을 하나 두세요. 그리고 아래 카메라 영상에서 그 물건을
      <b> 마우스로 드래그해 네모로 감싸면</b> 돼요. (물건 위를 한 번 클릭해도 돼요)</> },
  { id: "objects", targets: ["objects"], title: "2. 등록됐어요!",
    body: <>물건이 <b>사진 카드</b>로 들어왔어요. 이제 이 물건이 움직이면 제가 따라가요.
      이름을 누르면 바꿀 수 있고, 엉뚱한 게 잡혔으면 <b>[다시 선택]</b>을 누르면 돼요.
      <br />참고로 모든 패널은 <b>−</b> 로 최소화하고, 오른쪽 아래 모서리로 크기를 바꾸고, 제목 줄을 끌어 자리를 옮길 수 있어요.</> },
  { id: "mapping", targets: ["patchbay", "obj-cards"], goal: "mapping", title: "3. 물건을 기능에 연결하기",
    task: "물건 카드의 동그라미(잭)를 끌어서 ‘조향’ 같은 기능 동그라미에 놓아 주세요",
    body: <>물체 패널의 <b>물건 카드 옆 작은 동그라미</b>를 잡고, 매핑의 <b>기능 동그라미</b>(예: 조향) 위에 놓으면 선이 이어져요.
      <b>기능 동그라미를 클릭한 뒤 영상 속 물건을 클릭</b>해도 바로 연결돼요.
      연결을 끊으려면 <b>[매핑 해제]</b>를 누르거나 <b>선 위에서 마우스 휠을 클릭</b>하세요.</> },
  { id: "demo", targets: ["game-pick"], merge: true, goal: "demo", title: "4. 게임 고르기",
    task: "목록에서 해 보고 싶은 게임을 하나 눌러 주세요",
    body: <>아래 <b>데모</b> 목록에서 게임을 하나 골라 주세요. 레이싱·퐁·과일 받기 어떤 것이든 좋아요.</> },
  { id: "automap", targets: ["automap"], goal: "automap", title: "5. 자동 매핑 누르기",
    task: "‘컨트롤러’에서 물건을 고르고 [자동 매핑] 버튼을 눌러 주세요",
    body: <>게임 위의 <b>컨트롤러</b> 칸에서 방금 등록한 물건을 고르고 <b>[자동 매핑]</b>을 누르면,
      게임에 맞게 연결을 알아서 해 줘요.</> },
  { id: "play", targets: ["automap", "demo-stage"], merge: true, free: true, title: "6. 직접 해 보기",
    body: <>이제 진짜로 해 볼 차례예요! 게임 위의 <b>[시작]</b> 버튼이나 <b>Space</b>를 누르고, 물건을 움직여서 조종해 보세요.
      물건을 두 개 등록하면 2인 게임도 할 수 있어요. 충분히 해 봤으면 <b>[다음 →]</b>을 눌러 주세요.</> },
  { id: "hand", targets: ["mouse"], title: "마우스로 사용하기",
    body: <><b>[맨손 마우스]</b>나 <b>[물체 마우스]</b>를 누르면 손이나 물건이 컴퓨터 커서가 돼요.
      다른 앱까지 조작하려면 [출력 대상]에서 <b>실제</b>를 켜세요.</> },
  { id: "bye", targets: ["help"], title: "끝! 이제 마음껏 놀아요",
    body: <>이 안내는 언제든 <b>[? 안내]</b>로 다시 볼 수 있어요. 다 쓰면 <b>브라우저 창을 닫으면</b> 몇 초 뒤 AnyControl도 꺼져요.</> },
];

export const STEPS_EN: Step[] = [
  { id: "hello", targets: [], title: "Hi! Let me introduce AnyControl",
    body: <>I read how <b>objects, pens and bare hands</b> move on your desk and turn that into mouse, keyboard and gamepad input. Let's register an object and play a game together. It's quick.</> },
  { id: "caution", targets: [], title: "Two things first",
    body: <ul><li>Allow the <b>camera and Accessibility permissions</b> if macOS asks. (<b>macOS</b> · an <b>iPhone Continuity Camera</b> is most accurate)</li>
      <li>If anything goes wrong, press <b>ESC</b> to stop all input.</li></ul> },
  { id: "object", targets: ["camera"], goal: "object", title: "1. Register one object", task: "Drag a box around an object in the video",
    body: <>Put something solid like a <b>cup, wallet or pencil case</b> on the desk. In the camera video, <b>drag a box around it</b> with the mouse (or click on it).</> },
  { id: "objects", targets: ["objects"], title: "2. Registered!",
    body: <>It now appears as a <b>photo card</b> and I follow it as it moves. Click the name to rename it; if the wrong thing was grabbed, press <b>[Reselect]</b>.
      <br />Every panel can be collapsed with <b>−</b>, resized from its bottom-right corner and moved by dragging its title bar.</> },
  { id: "mapping", targets: ["patchbay", "obj-cards"], goal: "mapping", title: "3. Connect it to a function", task: "Drag the circle (jack) on the object card onto a function circle like ‘Steer’",
    body: <>Grab the <b>small circle by the object card</b> and drop it on a <b>function circle</b> (e.g. Steer). <b>Clicking a function circle, then the object in the video</b> also connects it.
      To disconnect, press <b>[Unmap]</b> or <b>middle-click the cable</b>.</> },
  { id: "demo", targets: ["game-pick"], merge: true, goal: "demo", title: "4. Pick a game", task: "Click a game in the list",
    body: <>In <b>Demos</b>, pick any game from the list: Racing, Pong, Fruit Catch…</> },
  { id: "automap", targets: ["automap"], goal: "automap", title: "5. Press Auto-map", task: "Choose your object under ‘Controller’, then press [Auto-map]",
    body: <>Above the game, choose the object you registered under <b>Controller</b> and press <b>[Auto-map]</b>. It connects everything for that game.</> },
  { id: "play", targets: ["automap", "demo-stage"], merge: true, free: true, title: "6. Try it yourself",
    body: <>Your turn! Press <b>[Start]</b> above the game or <b>Space</b>, then move your object to control it. Register two objects for 2-player games. When you're done, press <b>[Next →]</b>.</> },
  { id: "hand", targets: ["mouse"], title: "Use it as a mouse",
    body: <>Press <b>[Hand mouse]</b> or <b>[Object mouse]</b> to turn your hand or object into the cursor. To control other apps, turn on <b>Real</b> in [Output target].</> },
  { id: "bye", targets: ["help"], title: "Done! Have fun",
    body: <>Reopen this anytime with <b>[? Guide]</b>. When you're done, <b>close the browser window</b> and AnyControl quits a few seconds later.</> },
];

const PAD = 10;
type Layout = { box: Box | null; holes: Box[]; card: { left: number; top: number; side: Side } };

/** 따라 하기 단계의 성공 판정에 쓰는 시작 시점 값 */
interface Baseline { objects: number; cables: number; clicked: boolean }
function cableCount(): number { const d = useDraftStore.getState().draft; return d ? cables(d).length : 0; }

export function Tutorial() {
  const open = useApp((s) => s.tourOpen);
  const setTour = useApp((s) => s.setTour);
  const [idx, setIdx] = useState(0);
  const [done, setDone] = useState(false);
  const [layout, setLayout] = useState<Layout | null>(null);
  const cardRef = useRef<HTMLDivElement>(null);
  const nextRef = useRef<HTMLButtonElement>(null);
  const base = useRef<Baseline>({ objects: 0, cables: 0, clicked: false });
  const steps = t(STEPS, STEPS_EN);
  const step = steps[Math.min(idx, steps.length - 1)]!;
  const last = idx >= steps.length - 1;
  const go = (i: number) => setIdx(Math.max(0, Math.min(steps.length - 1, i)));

  useEffect(() => { if (open) setIdx(0); }, [open]);

  const targetsOf = (s: Step) =>
    s.targets.flatMap((name) => Array.from(document.querySelectorAll<HTMLElement>(`[data-tour="${name}"]`)));

  // 단계가 바뀌면: 성공 판정 기준을 새로 잡고, 가리킬 곳을 화면 가운데로
  useEffect(() => {
    if (!open) return;
    setDone(false);
    base.current = { objects: useApp.getState().objects.length, cables: cableCount(), clicked: false };
    targetsOf(step)[0]?.scrollIntoView?.({ behavior: "smooth", block: "center" });
    if (step.free) { if (document.activeElement instanceof HTMLElement && document.activeElement.closest(".tour")) document.activeElement.blur(); }
    else if (!step.goal) nextRef.current?.focus({ preventScroll: true });
  }, [open, step]);

  // 따라 하기: 데모 탭·자동 매핑 버튼 클릭을 지켜본다
  useEffect(() => {
    if (!open || (step.goal !== "demo" && step.goal !== "automap")) return;
    const onClick = (e: MouseEvent) => {
      const el = e.target instanceof Element ? e.target : null;
      if (step.goal === "demo") {
        const tab = el?.closest('[data-tour="demos"] [role="tab"]');
        if (tab && !/그리기|Drawing/.test(tab.textContent ?? "")) base.current.clicked = true;
      } else {
        const btn = el?.closest('[data-tour="automap"] button') as HTMLButtonElement | null;
        if (btn && !btn.disabled && /자동 매핑|Auto-map/.test(btn.textContent ?? "")) base.current.clicked = true;
      }
    };
    document.addEventListener("click", onClick, true);
    return () => document.removeEventListener("click", onClick, true);
  }, [open, step]);

  // 성공하면 초록으로 표시하고 1.4초 뒤 다음 단계로
  useEffect(() => {
    if (!open || !step.goal || done) return;
    const timer = window.setInterval(() => {
      const b = base.current;
      const ok = step.goal === "object" ? useApp.getState().objects.length > b.objects || b.objects > 0
        : step.goal === "mapping" ? cableCount() > b.cables
          : b.clicked;
      if (ok) setDone(true);
    }, 200);
    return () => window.clearInterval(timer);
  }, [open, step, done]);
  useEffect(() => {
    if (!done) return;
    const timer = window.setTimeout(() => go(idx + 1), 1400);
    return () => window.clearTimeout(timer);
  }, [done]);

  // 매 프레임 위치를 다시 잰다 (스크롤·크기 변경·패널 접기를 따라가게). 바뀔 때만 상태를 갱신한다.
  useEffect(() => {
    if (!open) return;
    let raf = 0;
    let lastKey = "";
    const tick = () => {
      raf = requestAnimationFrame(tick);
      const rects = targetsOf(step).map((e) => e.getBoundingClientRect()).filter((r) => r.width > 0 && r.height > 0);
      const box = unionBox(rects);
      const holes = (step.merge && box ? [box] : rects).map((r) => ({ left: r.left - PAD, top: r.top - PAD, width: r.width + PAD * 2, height: r.height + PAD * 2 }));
      const c = cardRef.current?.getBoundingClientRect();
      const hole = box && { left: box.left - PAD, top: box.top - PAD, width: box.width + PAD * 2, height: box.height + PAD * 2 };
      const card = placeCard(hole, { width: c?.width || 420, height: c?.height || 220 },
        { width: window.innerWidth, height: window.innerHeight });
      const key = JSON.stringify([hole, card, ...holes].map((v) => v && Object.values(v).map((n) => (typeof n === "number" ? Math.round(n) : n))));
      if (key !== lastKey) { lastKey = key; setLayout({ box: hole, holes, card }); }
    };
    tick();
    return () => cancelAnimationFrame(raf);
  }, [open, step]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (step.goal || step.free) { if (e.key === "Escape") setTour(false); return; }   // 따라 하기 중에는 화살표 키를 앱에 양보
      if (e.key === "ArrowRight") go(idx + 1);
      else if (e.key === "ArrowLeft") go(idx - 1);
      else if (e.key === "Escape") setTour(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, setTour, step, idx]);

  if (!open) return null;
  const card = layout?.card;
  const interactive = Boolean(step.goal);
  const total = steps.filter((s) => s.goal).length, doneCount = steps.slice(0, idx).filter((s) => s.goal).length + (done ? 1 : 0);
  return (
    <div className="tour interactive" role="dialog" aria-modal={!interactive} aria-labelledby="tour-title" aria-describedby="tour-text">
      {/* 나머지는 어둡게, 가리킬 곳(여러 개)만 뚫는다. 어두운 곳도 클릭·조작은 그대로 된다 */}
      <svg className="tour-mask" aria-hidden="true">
        <defs><mask id="tour-cut"><rect width="100%" height="100%" fill="white" />
          {(layout?.holes ?? []).map((h, i) => <rect key={i} x={h.left} y={h.top} width={h.width} height={h.height} rx={8} fill="black" />)}</mask></defs>
        <rect width="100%" height="100%" fill="rgba(5,8,14,0.62)" mask="url(#tour-cut)" />
        {(layout?.holes ?? []).map((h, i) => <rect key={i} x={h.left} y={h.top} width={h.width} height={h.height} rx={8} className={`tour-ring ${done ? "done" : ""}`} />)}
      </svg>
      <div ref={cardRef} className={`tour-card side-${card?.side ?? "center"}`}
        style={card ? { left: card.left, top: card.top } : { visibility: "hidden" }}>
        <div className="tour-buddy"><CameraBuddy size={52} /></div>
        <div className={`tour-bubble ${done ? "done" : ""}`}>
          <h2 id="tour-title">{done ? `✓ ${t("잘했어요!", "Nice!")}` : step.title}</h2>
          <div id="tour-text" className="tour-text">{step.body}</div>
          {step.task && <p className={`tour-task ${done ? "done" : ""}`}>{done ? t("성공! 다음 단계로 넘어가요…", "Done! Moving on…") : <>👉 {step.task}</>}</p>}
          <div className="tour-progress" aria-hidden="true">{steps.map((s, i) => <i key={s.id} className={i < idx || (i === idx && done) ? "past" : i === idx ? "now" : ""} />)}</div>
          <div className="tour-nav">
            <span className="muted small">{total ? t(`따라 하기 ${doneCount}/${total}`, `Hands-on ${doneCount}/${total}`) : `${idx + 1} / ${steps.length}`}</span>
            <button type="button" className="tour-skip" onClick={() => setTour(false)}>{t("건너뛰기", "Skip")}</button>
            {idx > 0 && <button type="button" onClick={() => go(idx - 1)}>{t("← 이전", "← Back")}</button>}
            {interactive
              ? <button type="button" className="tour-later" onClick={() => go(idx + 1)}>{t("이 단계 넘기기", "Skip this step")}</button>
              : <button ref={nextRef} type="button" className="active" onClick={() => (last ? setTour(false) : go(idx + 1))}>{last ? t("시작하기", "Get started") : t("다음 →", "Next →")}</button>}
          </div>
        </div>
      </div>
    </div>
  );
}
