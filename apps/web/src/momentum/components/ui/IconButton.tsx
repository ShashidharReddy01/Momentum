import type { LucideIcon } from 'lucide-react';
import { forwardRef } from 'react';
import { Button, type ButtonProps } from './Button';
import { Icon } from './Icon';
import { Tooltip } from './Tooltip';

export interface IconButtonProps extends Omit<ButtonProps, 'children'> {
  icon: LucideIcon;
  label: string;
  shortcut?: string;
}

/** Icon-only button: always has an accessible name and a tooltip (with shortcut). */
export const IconButton = forwardRef<HTMLButtonElement, IconButtonProps>(function IconButton(
  { icon, label, shortcut, variant = 'text', size = 'icon', ...props },
  ref,
) {
  return (
    <Tooltip content={label} shortcut={shortcut}>
      <Button ref={ref} variant={variant} size={size} aria-label={label} {...props}>
        <Icon icon={icon} size={size === 'icon-sm' ? 15 : 17} />
      </Button>
    </Tooltip>
  );
});
