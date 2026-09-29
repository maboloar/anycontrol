import { describe, expect, it } from "vitest";
import { HEADER_SIZE, encodeMessage, parseMessage, parsePreview } from "./protocol";
import { Rolling } from "./rolling";

function makePreview(seq: number, t: number, w: number, h: number, flags = 0, body = [0xff, 0xd8]): ArrayBuffer {
  const buf = new ArrayBuffer(HEADER_SIZE + body.length);
  const v = new DataView(buf);
  [0x56, 0x49, 0x46, 0x31].forEach((b, i) => v.setUint8(i, b));
  v.setUint8(4, 1);
  v.setUint8(5, 1);
  v.setUint16(6, flags, true);
  v.setUint32(8, seq, true);
  v.setFloat64(12, t, true);
  v.setUint16(20, w, true);
  v.setUint16(22, h, true);
  new Uint8Array(buf, HEADER_SIZE).set(body);
  return buf;
}

describe("parsePreview", () => {
  it("reads the 24-byte little-endian header written by the backend", () => {
    const { header, jpeg } = parsePreview(makePreview(4294967295, 1790000000123.5, 960, 540, 1));
    expect(header).toEqual({ seq: 4294967295, tWallMs: 1790000000123.5, width: 960, height: 540, flags: 1 });
    expect(Array.from(jpeg)).toEqual([0xff, 0xd8]);
  });

  it("rejects short buffers, bad magic and unknown versions", () => {
    expect(() => parsePreview(new ArrayBuffer(4))).toThrow();
    const bad = makePreview(1, 0, 1, 1);
    new DataView(bad).setUint8(0, 0);
    expect(() => parsePreview(bad)).toThrow(/magic/);
    const ver = makePreview(1, 0, 1, 1);
    new DataView(ver).setUint8(4, 9);
    expect(() => parsePreview(ver)).toThrow(/version/);
  });
});

describe("messages", () => {
  it("round-trips the JSON envelope", () => {
    const m = parseMessage(encodeMessage("ping", { t: 5 }));
    expect(m).toEqual({ v: 1, type: "ping", data: { t: 5 } });
  });

  it.each(["[]", '{"v":2,"type":"x"}', '{"v":1}', '{"v":1,"type":"x","data":[1]}'])("rejects %s", (bad) => {
    expect(() => parseMessage(bad)).toThrow();
  });
});

describe("Rolling", () => {
  it("matches numpy linear percentiles and keeps only the last N", () => {
    const r = new Rolling(5);
    [100, 1, 2, 3, 4, 5].forEach((x) => r.add(x));
    expect(r.length).toBe(5);
    expect(r.quantile(0.5)).toBe(3);
    expect(r.quantile(0.95)).toBeCloseTo(4.8);
    r.add(Number.NaN);
    expect(r.length).toBe(5);
  });
});
