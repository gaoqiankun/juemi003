import clsx from "clsx";
import type {
  ButtonHTMLAttributes,
  ComponentPropsWithoutRef,
  HTMLAttributes,
  InputHTMLAttributes,
  ReactNode,
} from "react";

import { Badge as UiBadge } from "@/components/ui/badge";
import { Button as UiButton, type ButtonProps as UiButtonProps } from "@/components/ui/button";
import { Card as UiCard } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { cn } from "@/lib/utils";

type CardProps = HTMLAttributes<HTMLDivElement> & {
  tone?: "default" | "low" | "glass" | "muted";
};

export function Card({ className, tone = "default", ...props }: CardProps) {
  const resolvedTone = tone === "muted" ? "low" : tone;
  return <UiCard tone={resolvedTone} className={className} {...props} />;
}

type ButtonVariant = "primary" | "secondary" | "ghost" | "danger";
type ButtonSize = "sm" | "md" | "lg";

const buttonVariantMap: Record<ButtonVariant, NonNullable<UiButtonProps["variant"]>> = {
  primary: "default",
  secondary: "secondary",
  ghost: "ghost",
  danger: "destructive",
};

const buttonSizeMap: Record<ButtonSize, NonNullable<UiButtonProps["size"]>> = {
  sm: "sm",
  md: "default",
  lg: "lg",
};

export interface ButtonProps extends Omit<UiButtonProps, "variant" | "size"> {
  variant?: ButtonVariant;
  size?: ButtonSize;
}

export function Button({
  className,
  variant = "secondary",
  size = "md",
  ...props
}: ButtonProps) {
  return (
    <UiButton
      className={className}
      variant={buttonVariantMap[variant]}
      size={buttonSizeMap[size]}
      {...props}
    />
  );
}

type BadgeTone = "neutral" | "accent" | "success" | "warning" | "danger";

const badgeVariantMap: Record<BadgeTone, NonNullable<ComponentPropsWithoutRef<typeof UiBadge>["variant"]>> = {
  neutral: "secondary",
  accent: "accent",
  success: "success",
  warning: "warning",
  danger: "destructive",
};

export function Badge({
  className,
  tone = "neutral",
  ...props
}: HTMLAttributes<HTMLDivElement> & {
  tone?: BadgeTone;
}) {
  return <UiBadge className={className} variant={badgeVariantMap[tone]} {...props} />;
}

export function StatusDot({
  className,
  tone = "neutral",
  label,
}: {
  className?: string;
  tone?: BadgeTone;
  label: string;
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-2 rounded-full bg-surface-container-low px-2.5 py-1 text-xs font-medium text-text-secondary",
        {
          "text-accent-strong": tone === "accent",
          "text-success-text": tone === "success",
          "text-warning-text": tone === "warning",
          "text-danger-text": tone === "danger",
        },
        className,
      )}
    >
      <span className="h-1.5 w-1.5 rounded-full bg-current" />
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
    <div className={cn("h-2 overflow-hidden rounded-full bg-surface-container-low", className)}>
      <div
        className="h-full rounded-full bg-[linear-gradient(135deg,var(--accent-strong),var(--accent-deep))] transition-all"
        style={{ width: `${percent}%` }}
      />
    </div>
  );
}

export function TextField({ className, ...props }: InputHTMLAttributes<HTMLInputElement>) {
  return <Input className={className} {...props} />;
}

export function InputField({ className, ...props }: InputHTMLAttributes<HTMLInputElement>) {
  return <Input className={className} {...props} />;
}

export type SelectFieldOption = {
  label: ReactNode;
  value: string;
};

export function SelectField({
  className,
  contentClassName,
  onValueChange,
  options,
  placeholder,
  value,
}: {
  className?: string;
  contentClassName?: string;
  onValueChange: (value: string) => void;
  options: SelectFieldOption[];
  placeholder?: string;
  value: string;
}) {
  return (
    <Select value={value} onValueChange={onValueChange}>
      <SelectTrigger className={className}>
        <SelectValue placeholder={placeholder} />
      </SelectTrigger>
      <SelectContent className={contentClassName}>
        {options.map((option) => (
          <SelectItem key={option.value} value={option.value}>
            {option.label}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}

export function ToggleSwitch({
  checked,
  className,
  onChange,
  label,
}: {
  checked: boolean;
  className?: string;
  onChange: (nextValue: boolean) => void;
  label: string;
}) {
  return <Switch aria-label={label} checked={checked} className={className} onCheckedChange={onChange} />;
}

export {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  Switch,
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
};
