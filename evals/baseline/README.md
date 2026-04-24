# Baseline Review Corpus

This directory stores deterministic review fixtures used to compare review quality and runtime behavior before and after agent changes.

## Goals

- Protect against silent regressions when prompts, context packing, validation, or loop logic changes.
- Track comparable metrics across runs:
  - findings count
  - severity distribution
  - dropped findings (`debug_artifacts.validator_dropped`, `confidence_dropped`)
  - token/cost trend

## Corpus layout

- `manifest.json`: baseline case list and expected quality ranges.
- `records/*.json`: captured baseline outputs for each case.

## How to use

1. Add/update representative fixture payloads in `records/`.
2. Run the eval harness against these cases:
   - `python evals/run_eval.py --prompt-version candidate --predictions-dir evals/predictions/candidate`
   - `python evals/compare.py evals/results/prod.json evals/results/candidate.json`
3. Compare current run metrics with `manifest.json` expectations.
4. Flag any case that breaches tolerance as a regression.

## Notes

- Keep this corpus synthetic/sanitized.
- Do not include secrets or private repository content.
- Expand this set when new stack-specific prompts or tools are introduced.
