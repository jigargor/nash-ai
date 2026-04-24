# Incident Runbook

## Emergency kill switch

- Set `ENABLE_REVIEWS=false` in API environment variables.
- Webhooks continue returning `200`, but review jobs are not enqueued.

## Common incidents

### GitHub API outage

- Symptom: review jobs fail while webhook intake is healthy.
- Action: keep enqueue enabled, allow ARQ retries, monitor failure rate.
- Recovery: rerun failed reviews once GitHub API stabilizes.

### Anthropic rate limit / outage

- Symptom: review jobs fail in model-call path.
- Action: monitor `Review failed` logs, reduce concurrency (`max_jobs`) if needed.
- Recovery: retry failed jobs from admin endpoint after API recovers.

### Database outage

- Symptom: `/health` fails or worker cannot mark review state.
- Action: pause reviews (`ENABLE_REVIEWS=false`) and restore DB availability.
- Recovery: restart API and worker, run stale review recovery.

### Mass false positives after prompt/config change

- Symptom: sudden spike in findings volume and user complaints.
- Action: immediately set `ENABLE_REVIEWS=false`.
- Recovery: run eval harness, revert prompt/config, redeploy, re-enable reviews.

### Prompt injection attempt in PR content

- Symptom: findings reference untrusted instructions from diff content.
- Action: inspect system prompt constraints and dropped-finding diagnostics.
- Recovery: tighten prompt instructions and rerun evals before re-enabling.

## Postmortem template

- Incident start/end time (UTC)
- Impacted installations/repos
- User-visible impact
- Root cause
- Mitigation steps taken
- Preventive actions (code/tests/alerts/process)
