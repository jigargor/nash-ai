# Structured Error Handling

Nash uses one conceptual error contract across the FastAPI API, worker lifecycle, Next.js BFF, and dashboard UI. The same envelope fields appear everywhere, while each execution context chooses its own behavior policy: fail closed for security, retry/back off for transient dependencies, guide users for fixable input, and give operators a correlation ID when support is needed.

## Envelope

Canonical API/BFF errors use this shape:

```json
{
  "error": {
    "code": "DEPENDENCY_REDIS_UNAVAILABLE",
    "family": "dependency",
    "message": "Redis unavailable",
    "retryable": true,
    "action": "retry",
    "request_id": "..."
  },
  "detail": "Redis unavailable"
}
```

`detail` remains during migration so existing clients keep working. New clients should read `error`.

## Families and actions

- `auth`: reauthenticate or fail closed.
- `validation`: fix input before retrying.
- `not_found`: do not reveal cross-tenant existence.
- `conflict`: retry after the current operation settles.
- `rate_limit`: back off before retrying.
- `dependency`: retry or contact an operator depending on the dependency.
- `upstream`: retry/back off for provider or network failures.
- `security`: fail closed; never bypass verification.
- `internal`: generic safe message plus `request_id`.

## Worker failure classes

- `retryable_transient`: timeout, temporary outage, network blip.
- `retryable_backoff_required`: quota/rate-limit/provider overload.
- `permanent_user_actionable`: invalid user input or inaccessible resource.
- `permanent_operator_actionable`: deployment/configuration issue.
- `security_fail_closed`: signature/auth/token integrity failure.

## Dependency fallback policy

| Dependency | Default behavior | User-facing mode | Operator signal |
| --- | --- | --- | --- |
| Redis | Structured 503 for queue/lock-dependent paths | Retry | Restore Redis / queue health |
| DB | Safe dependency/internal error | Retry or contact support | Pool, timeout, migration, RLS |
| GitHub | 429/5xx retryable; permission/auth permanent | Retry or reconnect/install | App permissions/rate limit |
| LLM | quota/rate-limit backoff; missing key operator/user actionable | Retry, wait, or configure key | BYOK/env/circuit breaker |
| R2 | Degrade non-critical archive/export; block unsafe rotation state | Degraded archive/export | Rotate credentials |
| Turnstile | Fail closed | Verification failed/unavailable | Secret or siteverify outage |

## Compatibility and enforcement

During migration, backend handlers emit both canonical `error` and legacy `detail`. The BFF accepts canonical, legacy JSON, and text errors, then normalizes them to `NormalizedApiError` before dashboard code sees them. Future endpoint migrations should raise typed app errors or safe `HTTPException`s and should never return raw exception text to clients.
