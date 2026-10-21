import test from 'node:test'
import assert from 'node:assert/strict'
import { validateClockInPhotoFiles, MAX_PHOTO_BYTES, MAX_PHOTOS } from './clockInPhotos.js'
const file = (overrides = {}) => ({ name: '打卡.png', type: 'image/png', size: 1024, ...overrides })
test('supports multiple JPEG PNG and WebP photos', () => {
  assert.equal(validateClockInPhotoFiles([file(), file({ type: 'image/jpeg' }), file({ type: 'image/webp' })]), '')
})
test('enforces total limit across existing and new photos', () => {
  assert.match(validateClockInPhotoFiles([file(), file()], MAX_PHOTOS - 1), /最多保存/)
  assert.equal(validateClockInPhotoFiles([file()], MAX_PHOTOS - 1), '')
})
test('rejects unsupported, empty and oversized files', () => {
  assert.match(validateClockInPhotoFiles([file({ type: 'image/svg+xml' })]), /不是支持/)
  assert.match(validateClockInPhotoFiles([file({ type: 'text/plain' })]), /不是支持/)
  assert.match(validateClockInPhotoFiles([file({ size: 0 })]), /为空/)
  assert.match(validateClockInPhotoFiles([file({ size: MAX_PHOTO_BYTES + 1 })]), /超过/)
  assert.equal(validateClockInPhotoFiles([file({ size: MAX_PHOTO_BYTES })]), '')
})
test('limits each batch while allowing incremental gallery uploads', () => {
  assert.equal(validateClockInPhotoFiles(Array.from({ length: 3 }, () => file({ size: MAX_PHOTO_BYTES }))), '')
  assert.match(validateClockInPhotoFiles(Array.from({ length: 4 }, () => file({ size: MAX_PHOTO_BYTES }))), /单批/)
})
