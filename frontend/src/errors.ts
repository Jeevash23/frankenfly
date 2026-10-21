// Validation errors arrive as a list of {location, message}; show readable sentences, not JSON.
// Locations read as words: ['body', 'custom_conditions', 0, 'label'] → "custom conditions 1 › label".
export function describeError(detail: unknown, status: number): string {
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail) && detail.length)
    return detail
      .map((item) => {
        const location: unknown[] = Array.isArray(item?.location) ? item.location : [];
        const parts: string[] = [];
        for (const part of location.filter((part) => part !== 'body')) {
          if (typeof part === 'number' && parts.length) parts.push(`${parts.pop()} ${part + 1}`);
          else parts.push(String(part).replaceAll('_', ' '));
        }
        const field = parts.join(' › ');
        const message = String(item?.message ?? 'Invalid value').replace(/^Value error, /, '');
        return field ? `${field}: ${message}` : message;
      })
      .join(' ');
  return `The local command failed (HTTP ${status}).`;
}
