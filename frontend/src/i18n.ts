import { useSyncExternalStore } from "react";

export type Lang = "ko" | "en";
export const LANG_KEY = "anycontrol.lang";
export const LANGS: [Lang, string][] = [["ko", "한국어"], ["en", "English"]];

function initial(): Lang {
  try { return localStorage.getItem(LANG_KEY) === "en" ? "en" : "ko"; } catch { return "ko"; }
}

let current: Lang = initial();
const listeners = new Set<() => void>();
if (typeof document !== "undefined") document.documentElement.lang = current;

export const getLang = (): Lang => current;

/** 언어를 바꾸고 저장한다. 처음 설치해 켜면 한국어가 기본. */
export function setLang(lang: Lang) {
  if (lang === current) return;
  current = lang;
  try { localStorage.setItem(LANG_KEY, lang); } catch { /* 이번 화면에서만 */ }
  document.documentElement.lang = lang;
  listeners.forEach((l) => l());
}

/** 현재 언어를 구독한다. App 이 구독하므로 언어가 바뀌면 화면 전체가 다시 그려진다. */
export function useLang(): Lang {
  return useSyncExternalStore((cb) => { listeners.add(cb); return () => listeners.delete(cb); }, getLang, getLang);
}

/** 한국어·영어 문구를 나란히 적고 현재 언어 쪽을 쓴다. 문자열과 JSX 모두 된다. */
export function t<T>(ko: T, en: T): T {
  return current === "en" ? en : ko;
}

/** 모듈 상수로 둔 라벨 표: 읽을 때마다 현재 언어로 고른다 (Object.entries 도 번역된 값을 준다). */
export function labels<K extends string>(pairs: Record<K, readonly [string, string]>): Record<K, string> {
  return new Proxy(pairs, {
    get: (o, k) => { const p = (o as Record<string | symbol, unknown>)[k]; return Array.isArray(p) ? t(p[0], p[1]) : p; },
  }) as unknown as Record<K, string>;
}
