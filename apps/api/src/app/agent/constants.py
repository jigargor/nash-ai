# Prompt version tag stamped on every review for traceability.
PROMPT_VERSION = "v4-reviewer-editor"

# Agent loop
MAX_ITERATIONS = 10

# Context builder token budgets
MAX_INPUT_TOKENS = 100_000
MAX_DIFF_TOKENS = 50_000
CONTEXT_WINDOW_LINES = 30
DOC_CONTEXT_WINDOW_LINES = 8

# Repair / validation retry thresholds
REPAIR_SEARCH_WINDOW = 3
REPAIR_RETRY_DROP_RATE = 0.20
