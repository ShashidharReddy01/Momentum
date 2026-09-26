import '@testing-library/jest-dom/vitest';
import { cleanup, configure } from '@testing-library/react';
import { afterEach } from 'vitest';

afterEach(() => cleanup());

// The whole app boots per test (config → me → data, lazy chunks); under a full parallel run
// that can take over the 1s default, so findBy*/waitFor get more room (passing tests stay fast).
configure({ asyncUtilTimeout: 4000 });

// jsdom lacks these; Radix/cmdk use them.
class RO {
  observe() {}
  unobserve() {}
  disconnect() {}
}
globalThis.ResizeObserver ??= RO as unknown as typeof ResizeObserver;
Element.prototype.scrollIntoView ??= function scrollIntoView() {};
// sonner's toasts capture the pointer on press (clicking a toast action, e.g. Undo)
Element.prototype.setPointerCapture ??= function setPointerCapture() {};
Element.prototype.releasePointerCapture ??= function releasePointerCapture() {};
// ProseMirror measures the selection to scroll it into view after programmatic edits (S3.4.4)
const noRects = () =>
  ({ length: 0, item: () => null, [Symbol.iterator]: [][Symbol.iterator] }) as unknown as DOMRectList;
const zeroRect = () =>
  ({ x: 0, y: 0, top: 0, left: 0, right: 0, bottom: 0, width: 0, height: 0, toJSON() {} }) as DOMRect;
Range.prototype.getClientRects ??= noRects;
Range.prototype.getBoundingClientRect ??= zeroRect;
Element.prototype.getClientRects ??= noRects;
document.elementFromPoint ??= () => null;
window.matchMedia ??= ((query: string) => ({
  matches: false,
  media: query,
  onchange: null,
  addEventListener() {},
  removeEventListener() {},
  addListener() {},
  removeListener() {},
  dispatchEvent: () => false,
})) as unknown as typeof window.matchMedia;
