const SECRET_KEY = /(?:^|_)(?:api[_-]?key|authorization|cookie|credential|password|proxy|secret|session|ssh|token)(?:$|_)/i;
const SECRET_VALUE_PATTERNS = [
  /\b(?:authorization\s*:\s*)?bearer\s+[A-Za-z0-9._~+/=-]{8,}/gi,
  /\b(?:xai|sk)-[A-Za-z0-9_-]{12,}\b/g,
  /\b(?:api[_-]?key|token|password|secret)\s*[=:]\s*[^\s,;]+/gi,
];

export function redact(value: unknown, key = ""): unknown {
  if (SECRET_KEY.test(key)) return "[REDACTED]";
  if (typeof value === "string") {
    return SECRET_VALUE_PATTERNS.reduce(
      (current, pattern) => current.replace(pattern, (match) => {
        const separator = match.match(/^([^:=]+[:=]\s*)/);
        return separator ? `${separator[1]}[REDACTED]` : "Authorization: [REDACTED]";
      }),
      value,
    );
  }
  if (Array.isArray(value)) return value.map((entry) => redact(entry));
  if (value && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value).map(([entryKey, entryValue]) => [entryKey, redact(entryValue, entryKey)]),
    );
  }
  return value;
}
