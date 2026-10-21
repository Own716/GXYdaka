export const MAX_PHOTOS = 20
export const MAX_PHOTO_BYTES = 10 * 1024 * 1024
export const MAX_BATCH_BYTES = 30 * 1024 * 1024
const allowedTypes = new Set(['image/jpeg', 'image/png', 'image/webp'])
export function validateClockInPhotoFiles(files, existingCount = 0) {
  if (existingCount + files.length > MAX_PHOTOS) return `最多保存 ${MAX_PHOTOS} 张照片，请减少选择或删除旧照片`
  for (const file of files) {
    if (!allowedTypes.has(file.type)) return `“${file.name}”不是支持的 JPG、PNG 或 WebP 图片`
    if (!file.size || file.size > MAX_PHOTO_BYTES) return `“${file.name}”为空或超过 10 MB，请重新选择`
  }
  if (files.reduce((total, file) => total + file.size, 0) > MAX_BATCH_BYTES) return '单批照片总大小不能超过 30 MB，请分批添加'
  return ''
}
