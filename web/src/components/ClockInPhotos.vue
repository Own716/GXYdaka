<template>
  <section class="photo-library" aria-label="打卡照片库" v-loading="busy">
    <div class="photo-heading">
      <div><h3>打卡照片</h3><p>准备多张照片，每次打卡随机提交其中一张。</p></div>
      <el-switch :model-value="modelValue === true" :disabled="disabled || !endpoint" aria-label="随机提交打卡照片" active-text="随机提交" @update:model-value="emit('update:modelValue', $event)" />
    </div>
    <p class="photo-note">开关需保存配置后生效；上传和删除照片会立即保存，不会自动开启提交。手动打卡和补卡也使用此设置，随机结果可能重复；关闭时沿用原有图片设置。</p>
    <p class="photo-note">若日志提示“学校设置必须上传图片”，请上传至少一张照片，再开启“随机提交”并保存；仅上传不会改变原有打卡配置。</p>
    <div v-if="!endpoint" class="photo-empty">请先保存并绑定用户，再添加专属打卡照片。</div>
    <template v-else>
      <el-alert v-if="loadError" :title="loadError" type="error" :closable="false" />
      <div class="photo-toolbar">
        <label class="photo-picker" :class="{ 'is-disabled': disabled || busy || photos.length >= MAX_PHOTOS || !!loadError }">
          <span>＋ 添加照片</span>
          <input type="file" accept="image/jpeg,image/png,image/webp" multiple :disabled="disabled || busy || photos.length >= MAX_PHOTOS || !!loadError" aria-label="选择多张打卡照片" @change="uploadFiles" />
        </label>
        <span>{{ photos.length }} / {{ MAX_PHOTOS }} 张 · JPG、PNG、WebP · 每张 10 MB / 单批 30 MB 以内</span>
        <el-button text :disabled="busy" @click="load">刷新照片</el-button>
      </div>
      <div v-if="photos.length" class="photo-grid">
        <article v-for="photo in photos" :key="photo.id" class="photo-tile">
          <el-image :src="photoUrl(photo)" :alt="photo.name" fit="cover" :preview-src-list="[photoUrl(photo)]" preview-teleported>
            <template #error><span class="photo-image-error">照片加载失败</span></template>
          </el-image>
          <div class="photo-caption"><span :title="photo.name">{{ photo.name }}</span><el-button type="danger" text size="small" :disabled="disabled || busy" :aria-label="`删除照片 ${photo.name}`" @click="remove(photo)">删除</el-button></div>
        </article>
      </div>
      <div v-else-if="!loadError" class="photo-empty">还没有照片，点击“添加照片”可一次选择多张。</div>
      <el-alert v-if="modelValue === true && !photos.length && !loadError" title="尚无可用照片：开启后将暂停提交，避免无图打卡。请添加照片或关闭此开关。" type="warning" :closable="false" show-icon />
    </template>
  </section>
</template>

<script setup>
import { ref, watch, onBeforeUnmount } from 'vue'
import { ElMessageBox } from 'element-plus'
import { notifySuccess, notifyError, resolveErrorMessage } from '../utils/notify'
import { validateClockInPhotoFiles, MAX_PHOTOS } from '../utils/clockInPhotos'
const props = defineProps({
  modelValue: { type: Boolean, default: false },
  endpoint: { type: String, default: '' },
  client: { type: Function, required: true },
  disabled: { type: Boolean, default: false },
})
const emit = defineEmits(['update:modelValue'])
const photos = ref([])
const busy = ref(false)
const loadError = ref('')
let version = 0
let controller = null
const photoUrl = (photo) => `/api${props.endpoint}/${encodeURIComponent(photo.id)}`
const load = async () => {
  controller?.abort()
  controller = new AbortController()
  const current = ++version
  photos.value = []
  loadError.value = ''
  busy.value = !!props.endpoint
  if (!props.endpoint) return
  try {
    const res = await props.client.get(props.endpoint, { signal: controller.signal })
    if (current === version) photos.value = res.data?.photos || []
  } catch (error) {
    if (current === version && error?.code !== 'ERR_CANCELED') loadError.value = resolveErrorMessage(error, '照片库加载失败，请重试')
  } finally {
    if (current === version) busy.value = false
  }
}
const uploadFiles = async (event) => {
  const files = Array.from(event.target.files || [])
  event.target.value = ''
  if (!files.length || busy.value || props.disabled || !props.endpoint) return
  const error = validateClockInPhotoFiles(files, photos.value.length)
  if (error) { notifyError(error); return }
  const data = new FormData()
  files.forEach((file) => data.append('files', file))
  const current = version
  busy.value = true
  try {
    const res = await props.client.post(props.endpoint, data, { timeout: 120000, signal: controller.signal })
    if (current !== version) return
    photos.value = res.data?.photos || []
    notifySuccess(`已添加 ${files.length} 张照片；随机提交开关请保存配置后生效`)
  } catch (error) {
    if (current === version && error?.code !== 'ERR_CANCELED') notifyError(resolveErrorMessage(error, '照片上传失败，请刷新照片库确认后重试'))
  } finally {
    if (current === version) busy.value = false
  }
}
const remove = async (photo) => {
  const current = version
  try {
    await ElMessageBox.confirm(`删除照片“${photo.name}”？删除后不会再被随机选中。`, '删除打卡照片', { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' })
  } catch { return }
  if (current !== version || props.disabled || busy.value) return
  busy.value = true
  try {
    const res = await props.client.delete(`${props.endpoint}/${encodeURIComponent(photo.id)}`, { signal: controller.signal })
    if (current !== version) return
    photos.value = res.data?.photos || []
    notifySuccess('照片已删除')
  } catch (error) {
    if (current === version && error?.code !== 'ERR_CANCELED') notifyError(resolveErrorMessage(error, '照片删除失败，请刷新照片库确认'))
  } finally {
    if (current === version) busy.value = false
  }
}
watch(() => props.endpoint, load, { immediate: true })
onBeforeUnmount(() => { version++; controller?.abort() })
</script>

<style scoped>
.photo-library { margin: 12px 0 24px; padding: 20px; border: 1px solid var(--el-border-color-lighter); border-radius: 16px; background: var(--el-fill-color-extra-light); }
.photo-heading { display: flex; justify-content: space-between; align-items: center; gap: 16px; flex-wrap: wrap; }
.photo-heading h3 { margin: 0 0 5px; font-size: 16px; }
.photo-heading p, .photo-note { color: var(--el-text-color-secondary); font-size: 13px; line-height: 1.7; margin: 0; }
.photo-note { margin: 12px 0; }
.photo-toolbar { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; margin: 16px 0; }
.photo-toolbar > span { font-size: 12px; color: var(--el-text-color-secondary); }
.photo-picker { position: relative; display: inline-flex; padding: 9px 14px; border-radius: 9px; background: var(--el-color-primary); color: white; cursor: pointer; font-size: 13px; }
.photo-picker:focus-within { outline: 2px solid var(--el-color-primary-light-3); outline-offset: 3px; }
.photo-picker input { position: absolute; inset: 0; opacity: 0; width: 100%; cursor: pointer; }
.photo-picker.is-disabled { opacity: .5; cursor: not-allowed; }
.photo-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(140px, 1fr)); gap: 12px; margin-bottom: 14px; }
.photo-tile { min-width: 0; overflow: hidden; background: var(--el-bg-color); border: 1px solid var(--el-border-color-lighter); border-radius: 12px; }
.photo-tile .el-image { width: 100%; height: 130px; display: block; }
.photo-caption { display: flex; align-items: center; justify-content: space-between; gap: 4px; padding: 6px 8px; }
.photo-caption > span { overflow: hidden; white-space: nowrap; text-overflow: ellipsis; font-size: 12px; }
.photo-empty { padding: 25px 12px; text-align: center; color: var(--el-text-color-secondary); border: 1px dashed var(--el-border-color); border-radius: 12px; font-size: 13px; margin-bottom: 12px; }
.photo-image-error { display: grid; height: 100%; place-items: center; color: var(--el-text-color-secondary); font-size: 12px; }
@media (max-width: 600px) { .photo-library { padding: 14px; } .photo-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
</style>
