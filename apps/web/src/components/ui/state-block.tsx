import type { PropsWithChildren, ReactNode } from "react";

interface StateBlockProps {
  title: string;
  description: string;
  action?: ReactNode;
}

export function StateBlock({ title, description, action }: PropsWithChildren<StateBlockProps>) {
  return (
    <section className="state-block">
      <h2 className="state-title">{title}</h2>
      <p className="state-description">{description}</p>
      {action ? <div style={{ marginTop: "0.75rem" }}>{action}</div> : null}
    </section>
  );
}
