import { useSyncExternalStore } from "react";

/**
 * 차트는 화면 폭에 맞춰 그려져 있어 그대로 인쇄하면 A4 칸을 넘친다.
 * 인쇄 전에 인쇄 폭으로 다시 그린 뒤 인쇄 창을 연다. 브라우저 메뉴로 인쇄해도 beforeprint에서 같은 상태로 바꾼다.
 */
let printing = false;
const listeners = new Set<() => void>();

function set(value: boolean) {
  if (printing === value) return;
  printing = value;
  listeners.forEach((l) => l());
}

function subscribe(listener: () => void) {
  if (listeners.size === 0) {
    window.addEventListener("beforeprint", onBefore);
    window.addEventListener("afterprint", onAfter);
  }
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
    if (listeners.size === 0) {
      window.removeEventListener("beforeprint", onBefore);
      window.removeEventListener("afterprint", onAfter);
    }
  };
}
const onBefore = () => set(true);
const onAfter = () => set(false);

export function usePrinting() {
  return useSyncExternalStore(subscribe, () => printing, () => false);
}

export function printPage() {
  set(true);
  // 차트가 다시 그려질 시간을 두 프레임 준다.
  requestAnimationFrame(() => requestAnimationFrame(() => window.print()));
}

/** A4(좌우 여백 16mm) 두 칸 배치에서 차트가 들어가는 폭(px). */
export const PRINT_CHART_WIDTH = 280;
export const PRINT_CHART_HEIGHT = 190;
