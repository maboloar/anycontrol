import {
  encodeMessage,
  parseMessage,
  parsePreview,
  type FrameState,
  type PreviewHeader,
  type Telemetry,
} from "./protocol";
import { useApp } from "./store";

export interface DecodedFrame {
  header: PreviewHeader;
  bitmap: ImageBitmap;
}

type FrameListener = (f: DecodedFrame) => void;
type MessageListener = (type: string, data: Record<string, unknown>) => void;

/**
 * 백엔드 WebSocket 연결. 끊기면 지수 백오프로 다시 붙는다.
 * 프레임은 React 상태에 넣지 않고 구독자(캔버스)에게 직접 넘긴다 (60Hz 리렌더 방지).
 * 디코딩이 밀리면 오래된 프레임은 버린다.
 */
/** 이 시간 동안 아무것도 못 받으면 연결이 끊긴 것으로 보고 다시 연결한다 */
const STALE_MS = 6000;

export class Connection {
  private ws: WebSocket | null = null;
  private backoff = 250;
  private closedByUser = false;
  /** 서버가 hello 로 알려 준 내 연결 번호. 창을 닫을 때 서버에 알리는 데 쓴다 */
  private clientId: number | null = null;
  private pingTimer: number | undefined;
  private reconnectTimer: number | undefined;
  /** 마지막으로 서버에서 무엇이든 받은 시각. pong 이 2초마다 오므로 오래 조용하면 끊긴 것으로 본다 */
  private lastRx = 0;
  private generation = 0;
  private decoding = false;
  private pending: ArrayBuffer | null = null;
  private frameListeners = new Set<FrameListener>();
  private msgListeners = new Set<MessageListener>();
  private lastPanelUpdate = 0;
  /** 이 창에서 처음 붙는 연결이면 fresh=1 (서버가 다른 창을 놓게 한다). 재연결은 0 */
  private everConnected = false;
  private bootId: string | null = null;
  /** 다른 창이 연결을 가져갔거나 서버가 새 창을 열었다: 다시 붙지 않는다 (사용자가 '이 창에서 계속'을 누를 때까지) */
  private dormant = false;
  /** 가장 최근 추적 상태 (오버레이가 매 프레임 읽는다) */
  latestState: FrameState | null = null;

  constructor(private readonly url = defaultUrl()) {}

  connect(): void {
    if (this.dormant || (this.ws && this.ws.readyState < WebSocket.CLOSING)) return;
    window.clearTimeout(this.reconnectTimer);
    window.clearInterval(this.pingTimer);
    const generation = ++this.generation;
    this.closedByUser = false;
    useApp.getState().setConn("connecting");
    const ws = new WebSocket(`${this.url}${this.url.includes("?") ? "&" : "?"}fresh=${this.everConnected ? 0 : 1}`);
    this.everConnected = true;
    ws.binaryType = "arraybuffer";
    this.ws = ws;
    ws.onopen = () => {
      if (this.ws !== ws) return;
      this.backoff = 250;
      useApp.getState().setConn("open");
      this.lastRx = performance.now();
      this.pingTimer = window.setInterval(() => {
        // 소켓이 닫히지 않은 채 서버가 멈추거나 사라져도 알아챈다 (절전·네트워크 단절·프로세스 정지)
        if (performance.now() - this.lastRx > STALE_MS) { onDead(); return; }
        this.send("ping", { t: performance.now() });
      }, 2000);
    };
    const onDead = () => {
      if (this.ws !== ws) return;
      ws.onclose = ws.onmessage = null;
      ws.close();
      onClosed();
    };
    const onClosed = () => {
      if (this.ws !== ws) return;
      this.ws = null;
      this.latestState = null;
      this.pending = null;
      ++this.generation;
      window.clearInterval(this.pingTimer);
      useApp.getState().setConn("closed");
      if (!this.closedByUser) {
        this.reconnectTimer = window.setTimeout(() => {
          if (!this.closedByUser) this.connect();
        }, this.backoff);
        this.backoff = Math.min(this.backoff * 2, 4000);
      }
    };
    ws.onclose = onClosed;
    ws.onmessage = (ev) => {
      if (this.ws !== ws || generation !== this.generation) return;
      this.lastRx = performance.now();
      if (typeof ev.data === "string") this.onText(ev.data);
      else this.onBinary(ev.data as ArrayBuffer);
    };
  }

  /** 창을 닫을 때: 소켓 종료 신호가 늦거나 안 가는 브라우저를 위해 서버에도 직접 알린다 (마지막 창이면 서버가 곧 종료) */
  private sayBye(): void {
    const id = this.clientId;
    this.clientId = null;
    if (id === null) return;
    try {
      const url = new URL("/api/bye", this.url.replace(/^ws/, "http")).toString();
      navigator.sendBeacon?.(url, new Blob([JSON.stringify({ client_id: id })], { type: "application/json" }));
    } catch { /* 알리지 못해도 소켓 종료로 처리된다 */ }
  }

  private goDormant(why: "replaced" | "restarted"): void {
    this.close();
    this.dormant = true;
    useApp.getState().setDormant(why);
  }

  close(): void {
    this.sayBye();
    this.closedByUser = true;
    window.clearTimeout(this.reconnectTimer);
    window.clearInterval(this.pingTimer);
    const ws = this.ws;
    this.ws = null;
    ++this.generation;
    this.latestState = null;
    this.pending = null;
    ws?.close();
    useApp.getState().setConn("closed");
  }

  send(type: string, data: Record<string, unknown> = {}): void {
    if (this.ws?.readyState === WebSocket.OPEN) this.ws.send(encodeMessage(type, data));
  }

  onFrame(fn: FrameListener): () => void {
    this.frameListeners.add(fn);
    return () => this.frameListeners.delete(fn);
  }

  onMessage(fn: MessageListener): () => void {
    this.msgListeners.add(fn);
    return () => this.msgListeners.delete(fn);
  }

  private onText(text: string): void {
    let msg;
    try {
      msg = parseMessage(text);
    } catch {
      return;
    }
    const app = useApp.getState();
    if (msg.type === "hello") {
      app.setHello(String(msg.data.version ?? ""));
      this.clientId = typeof msg.data.client_id === "number" ? msg.data.client_id : null;
      const boot = typeof msg.data.boot_id === "string" ? msg.data.boot_id : null;
      // 서버를 다시 켰고 서버가 새 탭을 열었다 → 이 예전 탭은 물러난다 (두 탭이 붙어 있으면 창을 닫아도 서버가 안 꺼진다)
      if (this.bootId && boot && boot !== this.bootId && msg.data.browser_auto_open) { this.goDormant("restarted"); return; }
      this.bootId = boot ?? this.bootId;
    }
    else if (msg.type === "replaced") { this.goDormant("replaced"); return; }
    else if (msg.type === "telemetry") app.setTelemetry(msg.data as unknown as Telemetry);
    else if (msg.type === "state") {
      this.latestState = msg.data as unknown as FrameState;
      const now = performance.now();
      if (now - this.lastPanelUpdate > 100) {
        this.lastPanelUpdate = now;
        app.setObjects(this.latestState.objects);
        app.setInputMirror(!!this.latestState.input_mirror);
        app.setCalibration(this.latestState.calibration);
        app.setAutoCalibration(this.latestState.auto_calibration ?? null);
        app.setLive({
          real: this.latestState.real ?? null,
          mouse: this.latestState.mouse ?? null,
          pens: this.latestState.pens ?? {},
          handDrawing: this.latestState.hand_drawing ?? null,
          mapping: this.latestState.mapping ?? null,
          controller: this.latestState.controller ?? null,
        });
      }
    } else if (msg.type === "pong" && typeof msg.data.client_t === "number")
      app.setClient({ rttMs: Math.round((performance.now() - msg.data.client_t) * 10) / 10 });
    this.msgListeners.forEach((fn) => fn(msg.type, msg.data));
  }

  private onBinary(buf: ArrayBuffer): void {
    if (this.decoding) {
      if (this.pending) useApp.getState().setClient({ decodeDropped: useApp.getState().client.decodeDropped + 1 });
      this.pending = buf; // 최신 것만 남긴다
      return;
    }
    void this.decode(buf);
  }

  private async decode(buf: ArrayBuffer): Promise<void> {
    const generation = this.generation;
    this.decoding = true;
    try {
      const { header, jpeg } = parsePreview(buf);
      const bitmap = await createImageBitmap(new Blob([jpeg], { type: "image/jpeg" }));
      if (generation !== this.generation || this.frameListeners.size === 0) bitmap.close();
      else this.frameListeners.forEach((fn) => fn({ header, bitmap }));
    } catch {
      /* 손상된 프레임은 건너뛴다 */
    } finally {
      this.decoding = false;
      const next = this.pending;
      this.pending = null;
      if (next) void this.decode(next);
    }
  }
}

function defaultUrl(): string {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  return `${proto}://${location.host}/ws`;
}

export const connection = new Connection();
