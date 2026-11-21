export function formatDate(value?: string, time = false) {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '—'
  return new Intl.DateTimeFormat('zh-CN', { month: 'short', day: 'numeric', ...(time ? { hour: '2-digit', minute: '2-digit' } as const : {}) }).format(date)
}
export function fileSize(bytes: number) {
  if (bytes >= 1024 * 1024) return (bytes / 1024 / 1024).toFixed(1) + ' MB'
  return (bytes / 1024).toFixed(1) + ' KB'
}
