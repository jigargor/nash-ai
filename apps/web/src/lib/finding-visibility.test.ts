import type { Finding } from "@ai-code-review/shared-types";
import { describe, expect, it } from "vitest";

import { filterVisibleFindings, getDismissedFindingIndices, isFindingVisible } from "@/lib/finding-visibility";
import { isEditableShortcutTarget } from "@/lib/keyboard-shortcuts";

function makeFinding(message: string): Finding {
  return {
    category: "security",
    confidence: 90,
    evidence: "diff_visible",
    file_path: "a.py",
    line_start: 1,
    message,
    severity: "high",
    target_line_content: "x = 1",
  };
}

describe("finding visibility", () => {
  it("reads dismissed indices defensively", () => {
    expect(getDismissedFindingIndices(null).size).toBe(0);
    expect(getDismissedFindingIndices({ dismissed_findings: "nope" }).size).toBe(0);
    expect([...getDismissedFindingIndices({ dismissed_findings: [1, "x", -2, 1.5, 3] })]).toEqual([1, 3]);
  });

  it("hides dismissed findings by default and shows them when toggled", () => {
    const findings = [makeFinding("a"), makeFinding("b"), makeFinding("c")];
    const dismissed = new Set([1]);
    expect(isFindingVisible(findings[1], 1, dismissed, false)).toBe(false);
    expect(isFindingVisible(findings[1], 1, dismissed, true)).toBe(true);

    const hidden = filterVisibleFindings(findings, dismissed, false);
    expect(hidden.map((item) => item.originalIndex)).toEqual([0, 2]);
    const shown = filterVisibleFindings(findings, dismissed, true);
    expect(shown.map((item) => item.originalIndex)).toEqual([0, 1, 2]);
  });
});

describe("keyboard shortcut target guard", () => {
  it("ignores text-entry controls", () => {
    expect(isEditableShortcutTarget(document.createElement("input"))).toBe(true);
    expect(isEditableShortcutTarget(document.createElement("textarea"))).toBe(true);
    expect(isEditableShortcutTarget(document.createElement("select"))).toBe(true);
    const editable = document.createElement("div");
    editable.setAttribute("contenteditable", "true");
    expect(isEditableShortcutTarget(editable)).toBe(true);
  });

  it("allows other targets", () => {
    expect(isEditableShortcutTarget(document.createElement("button"))).toBe(false);
    expect(isEditableShortcutTarget(document.body)).toBe(false);
    expect(isEditableShortcutTarget(window)).toBe(false);
    expect(isEditableShortcutTarget(null)).toBe(false);
  });
});
