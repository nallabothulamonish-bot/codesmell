export function formatDate(value: string | null | undefined): string {
  if (!value) return '—'

  // Backend stores UTC timestamps but may return them without a timezone suffix.
  const hasTimezone = /(?:Z|[+-]\d{2}:\d{2})$/i.test(value)
  const utcValue = hasTimezone ? value : `${value}Z`
  const date = new Date(utcValue)

  return new Intl.DateTimeFormat(undefined, {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(date)
}

export function formatPercent(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined || Number.isNaN(value)) return 'â€”'
  return `${(value * 100).toFixed(digits)}%`
}

export function titleCase(value: string): string {
  return value.replaceAll('_', ' ').replace(/\b\w/g, (letter) => letter.toUpperCase())
}

export function compactId(value: string): string {
  return value.length > 12 ? `${value.slice(0, 8)}â€¦` : value
}

export function severityRank(value: string): number {
  return { critical: 4, high: 3, medium: 2, low: 1 }[value] ?? 0
}



