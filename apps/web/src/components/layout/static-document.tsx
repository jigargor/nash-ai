import type { PropsWithChildren } from "react";

interface StaticDocumentProps extends PropsWithChildren {
  title: string;
  description?: string;
}

export function StaticDocument({ title, description, children }: StaticDocumentProps) {
  return (
    <div className="static-document">
      <header className="static-document-header">
        <h1 className="static-document-title">{title}</h1>
        {description ? <p className="static-document-lead">{description}</p> : null}
      </header>
      <div className="static-document-body panel">
        <div className="panel-content static-document-prose">{children}</div>
      </div>
    </div>
  );
}
