/**
 * Máy khách REST tới backend VoxDub.
 *
 * Mặc định gọi bằng đường dẫn tương đối (/v1/...) vì backend serve luôn
 * website cùng origin — build một lần chạy ở đâu cũng được, đổi domain
 * không phải build lại. Dev thì Vite proxy /v1 sang backend local.
 * `VITE_API_URL` chỉ dành cho trường hợp host website tách rời backend.
 *
 * Mọi lỗi đều được gói thành `ApiError` với `code` do backend đặt, để giao
 * diện phân biệt "hết Vox" với "mất mạng" mà không phải đọc chuỗi tiếng Việt.
 */
const BASE = (import.meta.env.VITE_API_URL || '').replace(/\/+$/, '')

export class ApiError extends Error {
  constructor(message, { code = '', status = 0, data = null } = {}) {
    super(message)
    this.name = 'ApiError'
    this.code = code
    this.status = status
    this.data = data
  }
}

async function request(path, { method = 'GET', body, headers = {}, signal } = {}) {
  let resp
  try {
    resp = await fetch(`${BASE}${path}`, {
      method,
      headers: {
        ...(body !== undefined ? { 'Content-Type': 'application/json' } : {}),
        ...headers,
      },
      body: body !== undefined ? JSON.stringify(body) : undefined,
      signal,
    })
  } catch (err) {
    if (err.name === 'AbortError') throw err
    throw new ApiError(
      'Không kết nối được máy chủ. Kiểm tra mạng rồi thử lại.',
      { code: 'OFFLINE' })
  }

  let data = null
  try {
    data = await resp.json()
  } catch {
    // 204, hoặc máy chủ trả về thứ không phải JSON (nginx chen vào giữa).
  }

  if (!resp.ok) {
    throw new ApiError(
      (data && data.message) || `Lỗi máy chủ (HTTP ${resp.status})`,
      { code: (data && data.code) || '', status: resp.status, data })
  }
  return data
}

// ------------------------------------------------------------- công khai --

export const api = {
  health: () => request('/health'),
  appConfig: () => request('/v1/config/app'),
  packages: () => request('/v1/billing/packages'),

  createOrder: ({ packageId, amountVnd, email }) =>
    request('/v1/billing/orders', {
      method: 'POST',
      body: { packageId, amountVnd, email },
    }),

  /** `token` chỉ có ở trình duyệt đã tạo đơn — thiếu nó thì không thấy key. */
  getOrder: (orderCode, token, signal) =>
    request(
      `/v1/billing/orders/${encodeURIComponent(orderCode)}`
      + (token ? `?token=${encodeURIComponent(token)}` : ''),
      { signal }),

  resendKey: (orderCode, token, email) =>
    request(`/v1/billing/orders/${encodeURIComponent(orderCode)}/resend`, {
      method: 'POST',
      body: { token, email },
    }),
}

// ------------------------------------------------------------------ admin --

/** Gọi route admin với token lưu trong sessionStorage. */
function adminRequest(path, opts = {}) {
  const token = sessionStorage.getItem('voxdub_admin_token') || ''
  return request(`/v1/admin${path}`, {
    ...opts,
    headers: { ...(opts.headers || {}), 'X-Admin-Token': token },
  })
}

function qs(params) {
  const clean = Object.entries(params || {})
    .filter(([, v]) => v !== '' && v !== undefined && v !== null)
  return clean.length ? `?${new URLSearchParams(clean)}` : ''
}

export const adminApi = {
  whoami: () => adminRequest('/whoami'),

  // -- Thiết bị --
  devices: (params) => adminRequest(`/devices${qs(params)}`),
  device: (fp) => adminRequest(`/devices/${fp}`),
  setDeviceStatus: (fp, status, reason) =>
    adminRequest(`/devices/${fp}/status`, {
      method: 'PATCH', body: { status, reason },
    }),
  adjustCredit: (fp, delta, reason) =>
    adminRequest(`/devices/${fp}/credit`, {
      method: 'POST', body: { delta, reason },
    }),
  transferCredit: (fp, toFingerprint, reason) =>
    adminRequest(`/devices/${fp}/transfer`, {
      method: 'POST', body: { toFingerprint, reason },
    }),

  // -- Mã kích hoạt --
  keys: (params) => adminRequest(`/keys${qs(params)}`),
  issueKeys: (vox, count, note) =>
    adminRequest('/keys', { method: 'POST', body: { vox, count, note } }),
  revokeKey: (code) => adminRequest(`/keys/${code}`, { method: 'DELETE' }),

  // -- Đơn hàng --
  orders: (params) => adminRequest(`/orders${qs(params)}`),
  approveOrder: (code, note) =>
    adminRequest(`/orders/${code}/approve`, { method: 'POST', body: { note } }),

  // -- Cấu hình --
  config: () => adminRequest('/config'),
  setConfig: (key, value) =>
    adminRequest(`/config/${encodeURIComponent(key)}`, {
      method: 'PUT', body: { value },
    }),

  // -- Nơi gọi mô hình --
  providers: () => adminRequest('/providers'),
  createProvider: (data) =>
    adminRequest('/providers', { method: 'POST', body: data }),
  updateProvider: (id, data) =>
    adminRequest(`/providers/${id}`, { method: 'PATCH', body: data }),
  deleteProvider: (id) =>
    adminRequest(`/providers/${id}`, { method: 'DELETE' }),

  // -- Thống kê --
  overview: (days) => adminRequest(`/analytics/overview${qs({ days })}`),
  usage: (days) => adminRequest(`/analytics/usage${qs({ days })}`),
  auditLog: (params) => adminRequest(`/audit-log${qs(params)}`),
}
