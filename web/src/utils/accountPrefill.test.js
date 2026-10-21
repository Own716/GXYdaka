import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import { canApplyPrefillLocation, credentialsMatch, hasAddressAndCoordinates, hasLocationValues, normalizeAccountInfo } from './accountPrefill.js'

const completeLocation = {
  address: '湖南省·长沙市·岳麓区·示例园',
  latitude: '28.200000',
  longitude: '112.900000',
  province: '湖南省',
  city: '长沙市',
  area: '岳麓区',
  source: '账号位置',
}

test('account info accepts only the documented profile whitelist and complete actual locations', () => {
  const result = normalizeAccountInfo({
    ok: true,
    profile: { name: '张三', companyName: '示例公司', token: 'must-not-escape', userInfo: { password: 'secret' } },
    accountLocation: completeLocation,
    ready: true,
    warnings: ['已读取'],
    locationMessage: '完整位置',
  })
  assert.deepEqual(result.profile, {
    name: '张三', schoolName: '', companyName: '示例公司', companyAddress: '', jobAddress: '', planName: '',
  })
  assert.equal(result.ready, true)
  assert.equal(result.accountLocation.source, '账号位置')
  assert.deepEqual(result.warnings, ['已读取'])
})

test('incomplete, missing, or invalid coordinates are never marked ready or applicable', () => {
  for (const location of [
    null,
    { ...completeLocation, latitude: '' },
    { ...completeLocation, longitude: '181' },
    { ...completeLocation, address: '' },
  ]) {
    const result = normalizeAccountInfo({ ok: true, accountLocation: location, ready: true })
    assert.equal(result.ready, false)
  }
  for (const location of [null, { ...completeLocation, latitude: '' }, { ...completeLocation, longitude: '181' }]) {
    assert.equal(canApplyPrefillLocation(normalizeAccountInfo({ accountLocation: location }).accountLocation), false)
  }
  const addressMissing = normalizeAccountInfo({ ok: true, accountLocation: { ...completeLocation, address: '' }, ready: true })
  assert.equal(addressMissing.ready, false)
  assert.equal(canApplyPrefillLocation(addressMissing.accountLocation), true)
  const partialCoordinates = { ...completeLocation, area: '' }
  assert.equal(canApplyPrefillLocation(partialCoordinates), true)
  assert.equal(normalizeAccountInfo({ ok: true, accountLocation: partialCoordinates, ready: true }).ready, true)
})

test('credential matching requires exact non-empty request credentials and detects account changes', () => {
  const captured = { phone: '13800000000', password: 'p@ss' }
  assert.equal(credentialsMatch(captured, { ...captured }), true)
  assert.equal(credentialsMatch(captured, { ...captured, phone: '13900000000' }), false)
  assert.equal(credentialsMatch(captured, { ...captured, password: 'different' }), false)
  assert.equal(credentialsMatch({ phone: '', password: 'p@ss' }, { phone: '', password: 'p@ss' }), false)
})

test('location value detection supports confirmation before replacing existing form values', () => {
  assert.equal(hasLocationValues({ latitude: 0, longitude: 0 }), true)
  assert.equal(hasLocationValues({ address: '', latitude: '', longitude: '' }), false)
  assert.equal(hasAddressAndCoordinates(completeLocation), true)
  assert.equal(hasAddressAndCoordinates({ ...completeLocation, address: '' }), false)
  assert.equal(hasAddressAndCoordinates({ ...completeLocation, latitude: '' }), false)
})

test('new-account prefill remains a lookup-only basic-info flow with stale-save protection', () => {
  const source = fs.readFileSync(new URL('../views/UserEdit.vue', import.meta.url), 'utf8')
  assert.match(source, /http\.post\('\/users\/account-info',\s*\{\s*phone,\s*password:\s*captured\.password\s*\},\s*\{\s*timeout:\s*120000\s*\}\)/)
  assert.match(source, /:disabled="!form\.phone\.trim\(\) \|\| !form\.password\.trim\(\) \|\| accountInfoLoading"/)
  assert.match(source, /type="password"\s+show-password/)
  assert.match(source, /accountInfoState\.value === 'expired'/)
  assert.match(source, /新增用户账号或密码已变更，请重新获取账号信息后再保存/)
  assert.match(source, /账号信息位置未完整：请补全有效地址和经纬度，或明确关闭自动打卡后再保存/)
  const lookup = source.split('const fetchNewAccountInfo = async () => {')[1].split('const canApplyAccountLocation')[0]
  assert.doesNotMatch(lookup, /http\.post\(['"`]\/users['"`]/)
})
