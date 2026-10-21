import assert from 'node:assert/strict'
import test from 'node:test'
import { resolveApiErrorMessage } from './errorMessage.js'

test('shows the server no-plan prompt for a 400 response', () => {
  const prompt = '尚未同步有效实习计划，请点击「同步实习计划」后重试'
  assert.equal(resolveApiErrorMessage({ response: { status: 400, data: { detail: prompt } } }), prompt)
})

test('uses a safe server explanation for 503 and a useful fallback otherwise', () => {
  assert.equal(
    resolveApiErrorMessage({ response: { status: 503, data: { detail: '第三方验证失败，请稍后重试' } } }),
    '第三方验证失败，请稍后重试',
  )
  assert.equal(resolveApiErrorMessage({ response: { status: 503 } }), '服务暂时不可用，请稍后重试')
})

test('distinguishes gateway timeout, internal server error, request timeout, and network failure', () => {
  assert.equal(resolveApiErrorMessage({ response: { status: 504 } }), '服务器响应超时，请稍后重试')
  assert.equal(resolveApiErrorMessage({ response: { status: 500, data: 'Internal Server Error' } }), '服务器处理请求时出错，请稍后重试')
  assert.equal(resolveApiErrorMessage({ code: 'ECONNABORTED' }), '请求超时，请稍后重试')
  assert.equal(resolveApiErrorMessage({ code: 'ERR_NETWORK' }), '网络连接失败，请检查网络后重试')
})
