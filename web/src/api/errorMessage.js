const NETWORK_ERROR_MESSAGE = '网络连接失败，请检查网络后重试'
const TIMEOUT_ERROR_MESSAGE = '请求超时，请稍后重试'

const normalizeResponseMessage = (data) => {
  if (!data) return ''
  if (typeof data === 'string') return data.trim()
  if (Array.isArray(data?.detail)) {
    return data.detail
      .map((item) => {
        if (typeof item === 'string') return item.trim()
        if (item && typeof item === 'object' && typeof item.msg === 'string') return item.msg.trim()
        return ''
      })
      .filter(Boolean)
      .join('；')
  }
  if (typeof data?.detail === 'string') return data.detail.trim()
  if (typeof data?.message === 'string') return data.message.trim()
  return ''
}

export const resolveApiErrorMessage = (error) => {
  const response = error?.response
  const dataMessage = normalizeResponseMessage(response?.data)
  if (error?.code === 'ECONNABORTED' || error?.code === 'ETIMEDOUT') {
    return TIMEOUT_ERROR_MESSAGE
  }

  if (response && Number(response.status || 0) >= 500) {
    const status = Number(response.status)
    if (status === 503) return dataMessage || '服务暂时不可用，请稍后重试'
    if (status === 504) return '服务器响应超时，请稍后重试'
    if (status === 500) return '服务器处理请求时出错，请稍后重试'
    return '服务暂时不可用，请稍后重试'
  }

  if (dataMessage) return dataMessage

  if (!response || error?.code === 'ERR_NETWORK') {
    return NETWORK_ERROR_MESSAGE
  }

  return error?.message || '请求失败'
}
