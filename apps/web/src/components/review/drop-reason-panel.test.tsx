import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import React from "react";

import { DropReasonPanel } from "@/components/review/drop-reason-panel";
import { collectDropBuckets } from "@/lib/api/quality";

describe("collectDropBuckets", () => {
  it("merges pipeline drops and legacy runner artifacts by stage:reason", () => {
    const buckets = collectDropBuckets({
      drops: [
        { finding: { file_path: "a.py", line_start: 3 }, reason: "target_line_mismatch", stage: "validation", detail: "x" },
        { finding: null, reason: "delivery_rejected", stage: "delivery" },
      ],
      validator_dropped: [{ file_path: "b.py", line_start: 9, reason: "target_line_mismatch", detail: "y" }],
      confidence_dropped: [{ file_path: "c.py", line_start: 1, confidence: 70, threshold: 85 }],
    });

    expect(buckets.map((bucket) => [bucket.key, bucket.count])).toEqual([
      ["validation:target_line_mismatch", 2],
      ["delivery:delivery_rejected", 1],
      ["policy:below_confidence_threshold", 1],
    ]);
  });

  it("returns nothing for empty artifacts", () => {
    expect(collectDropBuckets(null)).toEqual([]);
    expect(collectDropBuckets({})).toEqual([]);
  });
});

describe("DropReasonPanel", () => {
  it("renders nothing when no findings were withheld", () => {
    const { container } = render(<DropReasonPanel debugArtifacts={{}} postedFindings={2} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("summarises withheld findings with reasons", () => {
    render(
      <DropReasonPanel
        debugArtifacts={{
          drops: [{ finding: { file_path: "a.py", line_start: 3 }, reason: "line_not_in_diff", stage: "validation" }],
        }}
        generatedFindings={3}
        postedFindings={2}
      />,
    );

    expect(screen.getByRole("heading", { name: "Withheld findings" })).toBeInTheDocument();
    expect(screen.getByText(/3 generated · 2 posted · 1 withheld/)).toBeInTheDocument();
    expect(screen.getByText("line_not_in_diff")).toBeInTheDocument();
  });
});
