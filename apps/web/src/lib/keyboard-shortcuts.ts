/** True when keyboard input is going to a text-entry control (shortcuts must not hijack it). */
export function isEditableShortcutTarget(target: EventTarget | null): boolean {
  if (!target || typeof (target as HTMLElement).tagName !== "string") return false;
  const element = target as HTMLElement;
  const tag = element.tagName.toLowerCase();
  if (tag === "input" || tag === "textarea" || tag === "select") return true;
  if (element.isContentEditable) return true;
  const attr = element.getAttribute?.("contenteditable");
  return attr !== null && attr !== undefined && attr !== "false";
}
