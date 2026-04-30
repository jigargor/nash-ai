export type ErrorFamily =
  | "auth"
  | "validation"
  | "not_found"
  | "conflict"
  | "rate_limit"
  | "dependency"
  | "upstream"
  | "security"
  | "internal";

export type ErrorAction = "retry" | "reauth" | "fix_input" | "contact_support" | "none";

export interface NormalizedApiError {
  status: number;
  code: string;
  family: ErrorFamily;
  message: string;
  retryable: boolean;
  action: ErrorAction;
  requestId?: string;
  details?: Record<string, unknown>;
}

interface CanonicalErrorBody {
  error?: {
    code?: unknown;
    family?: unknown;
    message?: unknown;
    retryable?: unknown;
    action?: unknown;
    request_id?: unknown;
    details?: unknown;
  };
  detail?: unknown;
  error_description?: unknown;
}

function familyForStatus(status: number): ErrorFamily {
  if (status === 401 || status === 403) return "auth";
  if (status === 400 || status === 413 || status === 422) return "validation";
  if (status === 404) return "not_found";
  if (status === 409) return "conflict";
  if (status === 429) return "rate_limit";
  if (status === 502 || status === 504) return "upstream";
  if (status === 503) return "dependency";
  return "internal";
}

function actionForStatus(status: number): ErrorAction {
  if (status === 401) return "reauth";
  if (status === 400 || status === 413 || status === 422) return "fix_input";
  if (status === 409 || status === 429 || status === 502 || status === 503 || status === 504) return "retry";
  if (status >= 500) return "contact_support";
  return "none";
}

function codeForStatus(status: number): string {
  if (status === 401) return "AUTH_UNAUTHORIZED";
  if (status === 403) return "AUTH_FORBIDDEN";
  if (status === 404) return "NOT_FOUND";
  if (status === 409) return "CONFLICT";
  if (status === 413) return "VALIDATION_BODY_TOO_LARGE";
  if (status === 429) return "RATE_LIMITED";
  if (status === 502) return "UPSTREAM_BAD_GATEWAY";
  if (status === 503) return "DEPENDENCY_UNAVAILABLE";
  if (status === 504) return "UPSTREAM_TIMEOUT";
  if (status >= 500) return "INTERNAL_ERROR";
  return "REQUEST_FAILED";
}

function retryableForStatus(status: number): boolean {
  return status === 409 || status === 429 || status === 502 || status === 503 || status === 504;
}

function parseMaybeJson(raw: string): unknown {
  try {
    return JSON.parse(raw);
  } catch {
    return raw;
  }
}

function stringValue(value: unknown): string | undefined {
  return typeof value === "string" && value.trim() ? value : undefined;
}

function recordValue(value: unknown): Record<string, unknown> | undefined {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : undefined;
}

export function normalizeApiErrorPayload(input: unknown, status: number): NormalizedApiError {
  const payload = typeof input === "string" ? parseMaybeJson(input) : input;
  const body = recordValue(payload) as CanonicalErrorBody | undefined;
  const canonical = body?.error;
  const message =
    stringValue(canonical?.message) ??
    stringValue(body?.detail) ??
    stringValue(body?.error_description) ??
    (typeof payload === "string" && payload.trim() ? payload : undefined) ??
    `API request failed: ${status}`;

  return {
    status,
    code: stringValue(canonical?.code) ?? codeForStatus(status),
    family: (stringValue(canonical?.family) as ErrorFamily | undefined) ?? familyForStatus(status),
    message,
    retryable: typeof canonical?.retryable === "boolean" ? canonical.retryable : retryableForStatus(status),
    action: (stringValue(canonical?.action) as ErrorAction | undefined) ?? actionForStatus(status),
    requestId: stringValue(canonical?.request_id),
    details: recordValue(canonical?.details),
  };
}

export function apiErrorBody(error: NormalizedApiError): Record<string, unknown> {
  return {
    error: {
      code: error.code,
      family: error.family,
      message: error.message,
      retryable: error.retryable,
      action: error.action,
      request_id: error.requestId,
      details: error.details,
    },
    detail: error.message,
  };
}

export function makeApiError(
  status: number,
  message: string,
  overrides: Partial<NormalizedApiError> = {},
): NormalizedApiError {
  return {
    status,
    code: overrides.code ?? codeForStatus(status),
    family: overrides.family ?? familyForStatus(status),
    message,
    retryable: overrides.retryable ?? retryableForStatus(status),
    action: overrides.action ?? actionForStatus(status),
    requestId: overrides.requestId,
    details: overrides.details,
  };
}
