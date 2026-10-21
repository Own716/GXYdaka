import { validLocationCoordinates } from './userRules.js'

const PROFILE_FIELDS = ['name', 'schoolName', 'companyName', 'companyAddress', 'jobAddress', 'planName']
const LOCATION_FIELDS = ['address', 'latitude', 'longitude', 'province', 'city', 'area', 'source']

const text = (value) => typeof value === 'string' || typeof value === 'number' ? String(value).trim() : ''

export const normalizeAccountInfo = (data) => {
  const source = data && typeof data === 'object' ? data : {}
  const rawProfile = source.profile && typeof source.profile === 'object' ? source.profile : {}
  const profile = Object.fromEntries(PROFILE_FIELDS.map((key) => [key, text(rawProfile[key])]))
  const rawLocation = source.accountLocation && typeof source.accountLocation === 'object' ? source.accountLocation : null
  const accountLocation = rawLocation
    ? Object.fromEntries(LOCATION_FIELDS.map((key) => [key, text(rawLocation[key])]))
    : null
  const hasCompleteLocation = !!accountLocation
    && ['address', 'latitude', 'longitude'].every((key) => !!accountLocation[key])
    && validLocationCoordinates(accountLocation)
  const warnings = Array.isArray(source.warnings) ? source.warnings.map(text).filter(Boolean) : []

  return {
    ok: source.ok === true,
    profile,
    accountLocation,
    ready: source.ready === true && hasCompleteLocation,
    warnings,
    locationMessage: text(source.locationMessage),
  }
}

export const canApplyPrefillLocation = (location) => !!location && validLocationCoordinates(location)

export const hasAddressAndCoordinates = (location) =>
  !!text(location?.address) && validLocationCoordinates(location)

export const hasLocationValues = (location) =>
  ['address', 'latitude', 'longitude', 'province', 'city', 'area']
    .some((key) => text(location?.[key]) !== '')

export const credentialsMatch = (captured, current) =>
  !!captured?.phone && !!captured?.password
  && captured.phone === current?.phone
  && captured.password === current?.password
