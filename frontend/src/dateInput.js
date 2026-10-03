import { beijingDateIso } from './api'

const pad = (value) => String(value).padStart(2, '0')
const daysInMonth = (year, month) => new Date(Date.UTC(year, month, 0)).getUTCDate()

/**
 * Turn whatever was typed into a date filter into a YYYY-MM-DD key.
 *
 * Accepts digits with or without separators: 20261001, 2026-10-1, 2026/10,
 * 202610, 1001, 10-1, 15.  A month without a day becomes its first day for a
 * range start and its last day (or today, for the current month) for a range
 * end.  Returns '' when nothing usable was typed.
 */
export function normalizeDateInput(raw, { edge = 'start', today = beijingDateIso() } = {}) {
  const text = String(raw ?? '').trim()
  if (!text) return ''
  const [todayYear, todayMonth, todayDay] = today.split('-').map(Number)
  const digits = text.replace(/\D/g, '')
  const parts = text.split(/[^\d]+/).filter(Boolean)
  let year
  let month
  let day = null
  if (parts.length >= 2) {
    if (parts[0].length === 4) { year = Number(parts[0]); month = Number(parts[1]); day = parts[2] ? Number(parts[2]) : null }
    else { year = todayYear; month = Number(parts[0]); day = Number(parts[1]) }
  } else if (digits.length === 8) { year = Number(digits.slice(0, 4)); month = Number(digits.slice(4, 6)); day = Number(digits.slice(6, 8)) }
  else if (digits.length === 6) { year = Number(digits.slice(0, 4)); month = Number(digits.slice(4, 6)) }
  else if (digits.length === 4 && Number(digits.slice(0, 2)) >= 1 && Number(digits.slice(0, 2)) <= 12) { year = todayYear; month = Number(digits.slice(0, 2)); day = Number(digits.slice(2, 4)) }
  else if (digits.length === 4) { year = Number(digits); month = edge === 'start' ? 1 : 12 }
  else if (digits.length === 3) { year = todayYear; month = Number(digits.slice(0, 1)); day = Number(digits.slice(1, 3)) }
  else if (digits.length >= 1 && digits.length <= 2) { year = todayYear; month = todayMonth; day = Number(digits) }
  else return ''
  if (!(year >= 1970 && year <= 2100) || !(month >= 1 && month <= 12)) return ''
  if (day === null) {
    const current = year === todayYear && month === todayMonth
    day = edge === 'start' ? 1 : current ? todayDay : daysInMonth(year, month)
  }
  if (!(day >= 1)) return ''
  day = Math.min(day, daysInMonth(year, month))
  return `${year}-${pad(month)}-${pad(day)}`
}

/** Default filter range: the first day of the current Beijing month to today. */
export function currentMonthRange(today = beijingDateIso()) {
  return { from: `${today.slice(0, 7)}-01`, to: today }
}
