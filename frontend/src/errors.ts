// Validation errors arrive as a list of {location, message}; show readable sentences, not JSON.
export function describeError(detail: unknown, status: number): string {
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail) && detail.length)
    return detail
      .map((item) => {
        const location: unknown[] = Array.isArray(item?.location) ? item.location : [];
        const field = location.filter((part) => part !== 'body').join(' › ');
        const message = String(item?.message ?? 'Invalid value').replace(/^Value error, /, '');
        return field ? `${field}: ${message}` : message;
      })
      .join(' ');
  return `The local command failed (HTTP ${status}).`;
}
