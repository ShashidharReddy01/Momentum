import type { LucideIcon, LucideProps } from 'lucide-react';

export type IconProps = LucideProps & { icon: LucideIcon; size?: number };

/** Every icon goes through here so size/stroke follow the design system (1.7 stroke). */
export function Icon({ icon: Glyph, size = 16, strokeWidth = 1.7, ...rest }: IconProps) {
  return (
    <Glyph
      size={size}
      strokeWidth={strokeWidth}
      aria-hidden={rest['aria-label'] ? undefined : true}
      {...rest}
    />
  );
}
