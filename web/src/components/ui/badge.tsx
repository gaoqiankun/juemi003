import { cva, type VariantProps } from "class-variance-authority";

import { cn } from "@/lib/utils";

const badgeVariants = cva(
  "inline-flex items-center gap-2 rounded-full border px-2.5 py-1 text-xs font-medium transition-colors",
  {
    variants: {
      variant: {
        default: "border-outline bg-surface-container-low text-text-secondary",
        secondary: "border-outline bg-surface-container-highest text-text-primary",
        success: "border-[color:color-mix(in_srgb,var(--success)_28%,transparent)] bg-[color:color-mix(in_srgb,var(--success)_14%,transparent)] text-success-text",
        warning: "border-[color:color-mix(in_srgb,var(--warning)_28%,transparent)] bg-[color:color-mix(in_srgb,var(--warning)_14%,transparent)] text-warning-text",
        destructive: "border-[color:color-mix(in_srgb,var(--danger)_28%,transparent)] bg-[color:color-mix(in_srgb,var(--danger)_14%,transparent)] text-danger-text",
        accent: "border-[color:color-mix(in_srgb,var(--accent)_24%,transparent)] bg-[color:color-mix(in_srgb,var(--accent)_12%,transparent)] text-accent-strong",
      },
    },
    defaultVariants: {
      variant: "default",
    },
  },
);

export interface BadgeProps extends React.HTMLAttributes<HTMLDivElement>, VariantProps<typeof badgeVariants> {}

export function Badge({ className, variant, ...props }: BadgeProps) {
  return <div className={cn(badgeVariants({ variant }), className)} {...props} />;
}
