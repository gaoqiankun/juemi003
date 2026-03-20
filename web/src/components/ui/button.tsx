import * as React from "react";
import { Slot } from "@radix-ui/react-slot";
import { LoaderCircle } from "lucide-react";
import { cva, type VariantProps } from "class-variance-authority";

import { cn } from "@/lib/utils";

const buttonVariants = cva(
  "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-lg text-sm font-medium tracking-[-0.02em] transition-all duration-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background disabled:pointer-events-none disabled:opacity-50 [&_svg]:pointer-events-none [&_svg]:size-4 [&_svg]:shrink-0",
  {
    variants: {
      variant: {
        default: "border border-transparent bg-[linear-gradient(135deg,var(--accent-strong),var(--accent-deep))] text-accent-ink shadow-float hover:brightness-105",
        secondary: "border border-outline bg-surface-container-highest text-text-primary hover:bg-surface-container-high",
        outline: "border border-outline bg-transparent text-text-primary hover:bg-surface-container-low",
        ghost: "border border-transparent bg-transparent text-text-secondary hover:bg-surface-container-low hover:text-text-primary",
        destructive: "border border-transparent bg-danger text-text-primary shadow-float hover:brightness-105",
      },
      size: {
        default: "h-11 px-4 py-2.5",
        sm: "h-9 px-3 text-xs",
        lg: "h-12 px-5 text-sm",
        icon: "h-10 w-10 p-0",
      },
    },
    defaultVariants: {
      variant: "default",
      size: "default",
    },
  },
);

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {
  asChild?: boolean;
  loading?: boolean;
}

const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, children, disabled, loading = false, variant, size, asChild = false, ...props }, ref) => {
    const Comp = asChild ? Slot : "button";
    const content = asChild
      ? children
      : (
        <>
          {loading ? <LoaderCircle className="animate-spin" /> : null}
          {children}
        </>
      );

    return (
      <Comp
        className={cn(buttonVariants({ variant, size, className }))}
        ref={ref}
        disabled={disabled || loading}
        {...props}
      >
        {content}
      </Comp>
    );
  },
);
Button.displayName = "Button";

export { Button, buttonVariants };
