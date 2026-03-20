import clsx from "clsx";
import type {
  ButtonHTMLAttributes,
  HTMLAttributes,
  InputHTMLAttributes,
  SelectHTMLAttributes,
} from "react";

type CardProps = HTMLAttributes<HTMLDivElement> & {
  tone?: "default" | "muted" | "glass";
};

export function Card({ className, tone = "default", ...props }: CardProps) {
  return (
    <div
      className={clsx("admin-card", {
        "admin-card-muted": tone === "muted",
        "admin-card-glass": tone === "glass",
      }, className)}
      {...props}
    />
  );
}

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "secondary" | "ghost";
};

export function Button({ className, variant = "secondary", ...props }: ButtonProps) {
  return (
    <button
      className={clsx("admin-button", {
        "admin-button-primary": variant === "primary",
        "admin-button-secondary": variant === "secondary",
        "admin-button-ghost": variant === "ghost",
      }, className)}
      {...props}
    />
  );
}

export function Badge({
  className,
  tone = "neutral",
  ...props
}: HTMLAttributes<HTMLSpanElement> & {
  tone?: "neutral" | "accent" | "success" | "warning" | "danger";
}) {
  return (
    <span
      className={clsx("admin-badge", {
        "admin-badge-accent": tone === "accent",
        "admin-badge-success": tone === "success",
        "admin-badge-warning": tone === "warning",
        "admin-badge-danger": tone === "danger",
      }, className)}
      {...props}
    />
  );
}

export function StatusDot({
  className,
  tone = "neutral",
  label,
}: {
  className?: string;
  tone?: "neutral" | "success" | "warning" | "danger" | "accent";
  label: string;
}) {
  return (
    <span className={clsx("status-dot", className)}>
      <span
        className={clsx("status-dot-indicator", {
          "status-dot-accent": tone === "accent",
          "status-dot-success": tone === "success",
          "status-dot-warning": tone === "warning",
          "status-dot-danger": tone === "danger",
        })}
      />
      <span>{label}</span>
    </span>
  );
}

export function MeterBar({
  value,
  max = 100,
  className,
}: {
  value: number;
  max?: number;
  className?: string;
}) {
  const percent = Math.max(0, Math.min(100, (value / max) * 100));

  return (
    <div className={clsx("meter-bar", className)}>
      <div className="meter-bar-fill" style={{ width: `${percent}%` }} />
    </div>
  );
}

export function TextField({
  className,
  ...props
}: InputHTMLAttributes<HTMLInputElement>) {
  return <input className={clsx("admin-input", className)} {...props} />;
}

export function SelectField({
  className,
  ...props
}: SelectHTMLAttributes<HTMLSelectElement>) {
  return <select className={clsx("admin-input admin-select", className)} {...props} />;
}

export function ToggleSwitch({
  checked,
  onChange,
  label,
}: {
  checked: boolean;
  onChange: (nextValue: boolean) => void;
  label: string;
}) {
  return (
    <button
      type="button"
      className={clsx("toggle-switch", { "toggle-switch-on": checked })}
      aria-pressed={checked}
      aria-label={label}
      onClick={() => onChange(!checked)}
    >
      <span className="toggle-switch-thumb" />
    </button>
  );
}
