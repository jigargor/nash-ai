FastAPI-specific rules:
- Prefer async I/O paths and avoid blocking calls in request handlers.
- Do not suggest broad exception swallowing; recommend explicit exception handling and proper HTTP status mapping.
- Validate request/response models with Pydantic rather than ad-hoc dict checks.
