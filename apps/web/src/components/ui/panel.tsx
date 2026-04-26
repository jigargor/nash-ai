import type { HTMLAttributes, PropsWithChildren } from "react";

interface PanelProps extends HTMLAttributes<HTMLElement> {
  elevated?: boolean;
}

function classNames(...values: Array<string | false | null | undefined>): string {
  return values.filter(Boolean).join(" ");
}

export function Panel({ children, className, elevated = false, ...props }: PropsWithChildren<PanelProps>) {
  return (
    <section className={classNames("panel", elevated && "panel-elevated", className)} {...props}>
      <div className="panel-content">{children}</div>
    </section>
  );
}
