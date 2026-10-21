<template>
  <div class="login-page">
    <div class="login-card-wrap">
      <el-card class="login-card page-card">
        <template #header>
          <div class="login-header">
            <div class="login-title">工学云用户端</div>
            <div class="login-subtitle">登录后可执行打卡与日报</div>
          </div>
        </template>
        <el-form :model="form" @keyup.enter="submit">
          <el-form-item label="手机号/账号">
            <el-input v-model="form.phone" autocomplete="username" />
          </el-form-item>
          <el-form-item label="密码">
            <el-input v-model="form.password" type="password" show-password autocomplete="current-password" />
          </el-form-item>
          <el-form-item>
            <el-button type="primary" :loading="loading" style="width: 100%" @click="submit">登录</el-button>
          </el-form-item>
          <div class="login-footer">
            <span>还没有账号？</span>
            <el-button link type="primary" @click="router.push('/u/register')">立即注册</el-button>
          </div>
        </el-form>
      </el-card>
    </div>
  </div>
</template>

<script setup>
import { reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { userHttp } from '../../api/userHttp'
import { useUserAuthStore } from '../../stores/userAuth'
import { notifyError, notifyWarning, resolveErrorMessage } from '../../utils/notify'

const router = useRouter()
const route = useRoute()
const auth = useUserAuthStore()
const loading = ref(false)
const form = reactive({
  phone: '',
  password: '',
})

const resolveUserRedirect = () => {
  const redirect = route.query.redirect
  return typeof redirect === 'string' && (redirect === '/u' || redirect.startsWith('/u/')) ? redirect : '/u'
}

const submit = async () => {
  if (!form.phone || !form.password) {
    notifyWarning('请输入账号和密码')
    return
  }
  loading.value = true
  try {
    const res = await userHttp.post('/app/auth/login', {
      phone: form.phone,
      password: form.password,
    })
    if (!res.data?.phone) throw new Error('login response missing phone')
    auth.setAuth(res.data?.token || 'cookie', res.data?.phone, res.data?.user_id)
    router.replace(resolveUserRedirect())
  } catch (e) {
    notifyError(resolveErrorMessage(e, '登录失败'))
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.login-page {
  min-height: 100vh;
  min-height: 100dvh;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
  background:
    radial-gradient(900px 360px at 20% 10%, rgba(64, 158, 255, 0.14), transparent 60%),
    radial-gradient(900px 360px at 80% 0%, rgba(103, 194, 58, 0.1), transparent 55%),
    radial-gradient(600px 300px at 50% 100%, rgba(230, 162, 60, 0.1), transparent 60%),
    var(--el-bg-color-page);
}
.login-card-wrap {
  width: 100%;
  max-width: 440px;
}
.login-card {
  width: 100%;
  overflow: hidden;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 20px;
  box-shadow: 0 24px 64px rgba(31, 45, 61, 0.1);
}
.login-card :deep(.el-card__header) {
  padding: 28px 30px 18px;
  border-bottom: 0;
}
.login-card :deep(.el-card__body) {
  padding: 8px 30px 30px;
}
.login-card :deep(.el-form-item) {
  margin-bottom: 20px;
}
.login-card :deep(.el-form-item__label) {
  color: var(--el-text-color-regular);
  font-weight: 600;
}
.login-header {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.login-title {
  font-size: 22px;
  font-weight: 800;
  letter-spacing: 0.1px;
}
.login-subtitle {
  margin-top: 3px;
  font-size: 13px;
  color: var(--el-text-color-secondary);
}
.login-footer {
  display: flex;
  justify-content: center;
  align-items: center;
  gap: 4px;
  font-size: 13px;
  color: var(--el-text-color-secondary);
}
:global(html.dark) .login-page {
  background:
    radial-gradient(900px 360px at 20% 10%, rgba(64, 158, 255, 0.16), transparent 60%),
    radial-gradient(900px 360px at 80% 0%, rgba(103, 194, 58, 0.12), transparent 55%),
    radial-gradient(600px 300px at 50% 100%, rgba(230, 162, 60, 0.12), transparent 60%),
    var(--el-bg-color-page);
}
@media (max-width: 520px) {
  .login-page {
    padding: 18px;
  }
  .login-card {
    border-radius: 16px;
  }
  .login-card :deep(.el-card__header) {
    padding: 24px 22px 14px;
  }
  .login-card :deep(.el-card__body) {
    padding: 8px 22px 24px;
  }
}
</style>
