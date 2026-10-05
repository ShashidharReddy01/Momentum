import { useEffect, useRef, useState } from 'react';

/**
 * `on`, but when it turns off because a press elsewhere took focus, stay on until that press is
 * released. Hiding the toolbar at mousedown moved everything below it up, so the click landed on
 * whatever slid under the pointer (e.g. "Add subtask" right after typing a description).
 */
export function useUntilRelease(on: boolean): boolean {
  const [shown, setShown] = useState(on);
  const pressed = useRef(false);
  useEffect(() => {
    if (!on) return;
    const down = () => (pressed.current = true);
    const up = () => (pressed.current = false);
    document.addEventListener('pointerdown', down, true);
    document.addEventListener('pointerup', up, true);
    return () => {
      document.removeEventListener('pointerdown', down, true);
      document.removeEventListener('pointerup', up, true);
    };
  }, [on]);
  useEffect(() => {
    if (on) return setShown(true);
    if (!pressed.current) return setShown(false);
    // after the release and the click it produces, so the click hits what was under the pointer
    const hide = () => {
      pressed.current = false;
      setTimeout(() => setShown(false), 0);
    };
    document.addEventListener('pointerup', hide, { once: true, capture: false });
    document.addEventListener('pointercancel', hide, { once: true });
    return () => {
      document.removeEventListener('pointerup', hide);
      document.removeEventListener('pointercancel', hide);
    };
  }, [on]);
  return on || shown;
}
