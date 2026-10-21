const ISO_DATE_RE = /^\d{4}-\d{2}-\d{2}$/
const UNICODE_WHITESPACE_RE = /[\p{White_Space}\u001c-\u001f]/gu

export const countReportWords = (value) => Array.from(String(value ?? '').replace(UNICODE_WHITESPACE_RE, '')).length

export const resolveSkipHolidays = (mode, configuredValue, specialClockIn = false) => typeof configuredValue === 'boolean' ? configuredValue : mode === 'holiday' && !specialClockIn

export const validateReportWordLimits = (minWords = 1, maxWords = 1000) => {
  const min = Number(minWords)
  const max = Number(maxWords)
  if (!Number.isInteger(min) || !Number.isInteger(max) || min < 1 || max > 10000 || max < min) {
    return { valid: false, min, max, message: '字数范围配置无效' }
  }
  return { valid: true, min, max, message: '' }
}

export const validateReportWordRange = (value, minWords = 1, maxWords = 1000) => {
  const count = countReportWords(value)
  const limits = validateReportWordLimits(minWords, maxWords)
  if (!limits.valid) return { valid: false, count, message: limits.message }
  if (count < limits.min || count > limits.max) {
    return { valid: false, count, message: `内容字数为 ${count}，需在 ${limits.min}–${limits.max} 字之间（不计空白）` }
  }
  return { valid: true, count, message: '' }
}

const validIsoDate = (value) => {
  if (typeof value !== 'string' || !ISO_DATE_RE.test(value)) return false
  const date = new Date(`${value}T00:00:00Z`)
  return Number.isFinite(date.getTime()) && date.toISOString().slice(0, 10) === value
}

export const validateClockInSchedule = (clockIn) => {
  const schedule = clockIn?.schedule || {}
  const { startDate = '', endDate = '', weekdays = [] } = schedule
  if (startDate && !validIsoDate(startDate)) return '开始日期必须是有效的 YYYY-MM-DD 日期'
  if (endDate && !validIsoDate(endDate)) return '结束日期必须是有效的 YYYY-MM-DD 日期'
  if (startDate && endDate && endDate < startDate) return '结束日期不能早于开始日期'
  if (!Array.isArray(weekdays) || weekdays.some((day) => !Number.isInteger(day) || day < 1 || day > 7)) {
    return '每周打卡日配置无效'
  }
  return ''
}

export const validateReportContent = (content, reportSettings = {}) => {
  const minWords = reportSettings.minWords ?? 1
  const maxWords = reportSettings.maxWords ?? 1000
  return validateReportWordRange(content, minWords, maxWords)
}

export const hasLocationCoordinates = (location) => [location?.latitude, location?.longitude].some((value) => String(value ?? '').trim() !== '')

export const validLocationCoordinates = (location) => {
  if ([location?.latitude, location?.longitude].some((value) => value == null || typeof value === 'boolean' || String(value).trim() === '')) return false
  const latitude = Number(location.latitude)
  const longitude = Number(location.longitude)
  return Number.isFinite(latitude) && latitude >= -90 && latitude <= 90
    && Number.isFinite(longitude) && longitude >= -180 && longitude <= 180
}
