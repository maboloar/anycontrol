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
export class Connection {
  private ws: WebSocket | null = null;
  private backoff = 250;
  private closedByUser = false;
  private pingTimer: number | undefined;
  private reconnectTimer: number | undefined;
  private generation = 0;
  private decoding = false;
  private pending: ArrayBuffer | null = null;
  private frameListeners = new Set<FrameListener>();
  private msgListeners = new Set<MessageListener>();
  private lastPanelUpdate = 0;
  /** 가장 최근 추적 상태 (오버레이가 매 프레임 읽는다) */
  latestState: FrameState | null = null;

  constructor(private readonly url = defaultUrl()) {}

  connect(): void {
    if (this.ws && this.ws.readyState < WebSocket.CLOSING) return;
    window.clearTimeout(this.reconnectTimer);
    window.clearInterval(this.pingTimer);
    const generation = ++this.generation;
    this.closedByUser = false;
    useApp.getState().setConn("connecting");
    const ws = new WebSocket(this.url);
    ws.binaryType = "arraybuffer";
    this.ws = ws;
    ws.onopen = () => {
      if (this.ws !== ws) return;
      this.backoff = 250;
      useApp.getState().setConn("open");
      this.pingTimer = window.setInterval(() => this.send("ping", { t: performance.now() }), 2000);
    };
    ws.onclose = () => {
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
    ws.onmessage = (ev) => {
      if (this.ws !== ws || generation !== this.generation) return;
      if (typeof ev.data === "string") this.onText(ev.data);
      else this.onBinary(ev.data as ArrayBuffer);
    };
  }

  close(): void {
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
    if (msg.type === "hello") app.setHello(String(msg.data.version ?? ""));
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
