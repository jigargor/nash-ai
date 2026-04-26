import type { HTMLAttributes, PropsWithChildren } from "react";

type BadgeVariant = "critical" | "high" | "medium" | "low" | "info";

interface BadgeProps extends HTMLAttributes<HTMLSpanElement> {
  variant?: BadgeVariant;
}

function classNames(...values: Array<string | false | null | undefined>): string {
  return values.filter(Boolean).join(" ");
}

export function Badge({ children, className, variant = "info", ...props }: PropsWithChildren<BadgeProps>) {
  return (
    <span className={classNames("badge", `badge-${variant}`, className)} {...props}>
      {children}
    </span>
  );
}
