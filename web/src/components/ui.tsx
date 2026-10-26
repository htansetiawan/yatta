import { createContext, ReactNode, useCallback, useContext, useEffect, useRef, useState } from "react";
import seal from "./seal-path.json";

export function Seal({ size = 28 }: { size?: number }) {
  return (
    <svg viewBox="0 0 64 64" width={size} height={size} aria-hidden="true">
      <rect width="64" height="64" rx="14" fill="#D2392B" />
      <path transform={seal.transform} fill="#FBF9F5" d={seal.d} />
    </svg>
  );
}

export const icons = {
  play: <svg viewBox="0 0 16 16"><path d="M4 2.8v10.4c0 .6.6.9 1.1.6l8.2-5.2c.5-.3.5-.9 0-1.2L5.1 2.2C4.6 1.9 4 2.2 4 2.8z" /></svg>,
  pause: <svg viewBox="0 0 16 16"><rect x="3.5" y="2.5" width="3" height="11" rx="1" /><rect x="9.5" y="2.5" width="3" height="11" rx="1" /></svg>,
  bigPlay: <svg viewBox="0 0 48 48"><circle cx="24" cy="24" r="24" fill="rgba(251,249,245,.94)" /><path d="M19 15.5v17c0 .8.9 1.3 1.6.9l13.5-8.5c.6-.4.6-1.3 0-1.7L20.6 14.6c-.7-.5-1.6 0-1.6.9z" fill="#1B1A17" /></svg>,
  download: <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"><path d="M8 1.5v8.2m0 0L4.8 6.5M8 9.7l3.2-3.2M2.5 11v2a1 1 0 001 1h9a1 1 0 001-1v-2" /></svg>,
  share: <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"><path d="M8 10V1.8m0 0L5 4.8m3-3l3 3M3 8v5.2a1 1 0 001 1h8a1 1 0 001-1V8" /></svg>,
  spark: <svg viewBox="0 0 16 16" fill="currentColor"><path d="M8 1l1.6 4.4L14 7 9.6 8.6 8 13 6.4 8.6 2 7l4.4-1.6z" /></svg>,
};

// ---- toast ----
type ToastFn = (message: string, error?: boolean) => void;
const ToastContext = createContext<ToastFn>(() => {});
export const useToast = () => useContext(ToastContext);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<{ message: string; error: boolean; show: boolean }>({ message: "", error: false, show: false });
  const timer = useRef<number>();
  const toast = useCallback<ToastFn>((message, error = false) => {
    setState({ message, error, show: true });
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => setState((s) => ({ ...s, show: false })), error ? 6000 : 2600);
  }, []);
  return (
    <ToastContext.Provider value={toast}>
      {children}
      <div className={`toast${state.show ? " show" : ""}${state.error ? " err" : ""}`} role="status" aria-live="polite">{state.message}</div>
    </ToastContext.Provider>
  );
}

// ---- modal ----
export function Modal({ children, onClose }: { children: ReactNode; onClose: () => void }) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <div className="modal-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal" role="dialog" aria-modal="true">{children}</div>
    </div>
  );
}

// ---- formatting ----
export const fmtSeconds = (s?: number | null) => {
  if (s == null) return "";
  const r = Math.round(s);
  return r < 60 ? `${r}s` : `${Math.floor(r / 60)}:${String(r % 60).padStart(2, "0")}`;
};

export function timeAgo(iso: string) {
  const sec = (Date.now() - new Date(iso).getTime()) / 1000;
  if (sec < 60) return "just now";
  if (sec < 3600) return `${Math.floor(sec / 60)} min ago`;
  if (sec < 86400) return `${Math.floor(sec / 3600)} h ago`;
  return new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

const PALETTE = ["#1B1A17", "#5E5A52", "#8A5A44", "#5D7044", "#24395B", "#B32F23"];
export const chipColor = (id: string) => PALETTE[[...id].reduce((a, c) => a + c.charCodeAt(0), 0) % PALETTE.length];

export const store = {
  get<T>(key: string, fallback: T): T {
    try { const v = localStorage.getItem("yatta:" + key); return v ? (JSON.parse(v) as T) : fallback; } catch { return fallback; }
  },
  set(key: string, value: unknown) {
    try { localStorage.setItem("yatta:" + key, JSON.stringify(value)); } catch { /* private mode */ }
  },
};

/** Poll ``fn`` every ``ms`` while ``active`` is true. */
export function usePoll(fn: () => void, ms: number, active = true) {
  const saved = useRef(fn);
  saved.current = fn;
  useEffect(() => {
    if (!active) return;
    const id = window.setInterval(() => saved.current(), ms);
    return () => window.clearInterval(id);
  }, [ms, active]);
}
