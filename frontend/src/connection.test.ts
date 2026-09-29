import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { Connection } from './connection';
import { useApp } from './store';

class Socket {
  static OPEN = 1; static CLOSING = 2;
  static all: Socket[] = [];
  readyState = 0;
  onopen?: () => void; onclose?: () => void;
  onmessage?: (event: { data: string | ArrayBuffer }) => void;
  constructor(_url: string) { Socket.all.push(this); }
  close() { this.readyState = 3; }
  send = vi.fn();
  open() { this.readyState = 1; this.onopen?.(); }
  drop() { this.readyState = 3; this.onclose?.(); }
}
let c: Connection;
beforeEach(() => {
  vi.useFakeTimers(); Socket.all = []; vi.stubGlobal('WebSocket', Socket);
  c = new Connection('ws://localhost/ws');
});
afterEach(() => { c.close(); vi.useRealTimers(); vi.unstubAllGlobals(); });
it('cancels pending reconnection when explicitly closed', () => {
  c.connect(); Socket.all[0]!.drop(); c.close(); vi.advanceTimersByTime(10000);
  expect(Socket.all).toHaveLength(1);
  expect(useApp.getState().conn).toBe('closed');
});
it('ignores old socket events after remount and keeps exactly one heartbeat', () => {
  c.connect(); const old = Socket.all[0]!; old.open(); c.close();
  c.connect(); const live = Socket.all[1]!; live.open(); old.drop(); old.open();
  vi.advanceTimersByTime(2100);
  expect(Socket.all).toHaveLength(2); expect(live.send).toHaveBeenCalledTimes(1);
  expect(old.send).not.toHaveBeenCalled(); expect(useApp.getState().conn).toBe('open');
});
it('drops a decoded bitmap from a closed connection', async () => {
  let finish!: (bitmap: ImageBitmap) => void;
  vi.stubGlobal('createImageBitmap', () => new Promise<ImageBitmap>(resolve => { finish = resolve; }));
  const listener = vi.fn(), close = vi.fn(); c.onFrame(listener);
  c.connect(); Socket.all[0]!.open();
  const b = new ArrayBuffer(26), v = new DataView(b);
  new Uint8Array(b).set([0x56, 0x49, 0x46, 0x31, 1, 1]);
  v.setUint16(20, 640, true); v.setUint16(22, 480, true);
  Socket.all[0]!.onmessage?.({ data: b }); c.close();
  finish({ close } as unknown as ImageBitmap); await Promise.resolve();
  expect(close).toHaveBeenCalledTimes(1); expect(listener).not.toHaveBeenCalled();
});
