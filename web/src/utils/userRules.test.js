import test from 'node:test'
import assert from 'node:assert/strict'
import { countReportWords, validateClockInSchedule, validateReportContent, validateReportWordLimits, validateReportWordRange, resolveSkipHolidays, hasLocationCoordinates, validLocationCoordinates } from './userRules.js'

test('report word counts remove Unicode whitespace and count Unicode code points', () => {
  assert.equal(countReportWords('中 文\nA\u00a0😀'), 4)
  assert.equal(countReportWords('中\u001c\u001f文'), 2)
  assert.deepEqual(validateReportWordRange('　中\n', 1, 1), { valid: true, count: 1, message: '' })
})

test('report word ranges reject empty, short, long, and invalid ranges', () => {
  assert.equal(validateReportWordRange('  ', 1, 1000).valid, false)
  assert.equal(validateReportWordRange('abc', 2, 3).valid, true)
  assert.equal(validateReportWordRange('abcd', 1, 3).valid, false)
  assert.equal(validateReportWordRange('x', 0, 1).message, '字数范围配置无效')
  assert.equal(validateReportWordLimits(1, 10000).valid, true)
  assert.equal(validateReportWordLimits(1, 10001).valid, false)
  assert.equal(validateReportContent('ok', { minWords: 2, maxWords: 8 }).count, 2)
})

test('legacy holiday mode is used only when the explicit switch is absent', () => {
  assert.equal(resolveSkipHolidays('holiday'), true)
  assert.equal(resolveSkipHolidays('holiday', false), false)
  assert.equal(resolveSkipHolidays('custom', false), false)
  assert.equal(resolveSkipHolidays('custom', true), true)
  assert.equal(resolveSkipHolidays('holiday', undefined, true), false)
})

test('schedule dates must be real ISO dates and end cannot precede start', () => {
  assert.equal(validateClockInSchedule({ schedule: { startDate: '2026-02-28', endDate: '2026-03-01', weekdays: [1, 5] } }), '')
  assert.match(validateClockInSchedule({ schedule: { startDate: '2026-02-29' } }), /有效/)
  assert.match(validateClockInSchedule({ schedule: { startDate: '2026-03-02', endDate: '2026-03-01' } }), /早于/)
  assert.match(validateClockInSchedule({ schedule: { weekdays: [0] } }), /每周打卡日/)
})

test('location application rejects missing/invalid coordinates and recognizes existing zero coordinates', () => {
  assert.equal(validLocationCoordinates({ latitude: 0, longitude: 0 }), true)
  assert.equal(hasLocationCoordinates({ latitude: 0, longitude: 0 }), true)
  assert.equal(hasLocationCoordinates({ latitude: null, longitude: '' }), false)
  for (const latitude of [null, '', ' ', 'NaN', Infinity, 91, false]) {
    assert.equal(validLocationCoordinates({ latitude, longitude: 110 }), false)
  }
})
