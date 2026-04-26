"use client";

import type { ButtonHTMLAttributes, PropsWithChildren } from "react";

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: "default" | "ghost" | "primary" | "danger";
}

function classNames(...values: Array<string | false | null | undefined>): string {
  return values.filter(Boolean).join(" ");
}

export function Button({
  children,
  className,
  variant = "default",
  type = "button",
  ...props
}: PropsWithChildren<ButtonProps>) {
  return (
    <button
      type={type}
      className={classNames(
        "button",
        variant === "ghost" && "button-ghost",
        variant === "primary" && "button-primary",
        variant === "danger" && "button-danger",
        className,
      )}
      {...props}
    >
      {children}
    </button>
  );
}
