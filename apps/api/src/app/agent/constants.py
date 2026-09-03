# Prompt version tag stamped on every review for traceability.
PROMPT_VERSION = "v5-review-overhaul"

# Agent loop
MAX_ITERATIONS = 10

# Context builder token budgets (tiktoken overestimates Sonnet 5 ~30%; allow more content)
MAX_INPUT_TOKENS = 130_000
MAX_DIFF_TOKENS = 65_000
CONTEXT_WINDOW_LINES = 30
DOC_CONTEXT_WINDOW_LINES = 8

# Repair / validation retry thresholds
REPAIR_SEARCH_WINDOW = 3
REPAIR_RETRY_DROP_RATE = 0.20
