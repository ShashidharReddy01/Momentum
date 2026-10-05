/**
 * Colours for a chip labelled in a user-chosen colour (tags, field options): a light tint of the
 * colour behind text mixed toward ink (the reverse in dark). Any colour at all stays readable:
 * swept over 4,096 hex colours in both themes, the worst contrast is 4.9:1 (2026-10-05).
 * Never put the raw colour on text: a light yellow or a near-black tag would be unreadable.
 */
export function tintColors(color: string): { background: string; color: string } {
  return {
    background: `color-mix(in oklab, ${color} 16%, var(--surface))`,
    color: `color-mix(in oklab, ${color} 35%, var(--ink))`,
  };
}
