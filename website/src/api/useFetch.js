/** Hook nạp dữ liệu một lần, có trạng thái loading/lỗi và nút thử lại. */
import { useCallback, useEffect, useState } from 'react'

export function useFetch(fn, deps = []) {
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(true)
  const [nonce, setNonce] = useState(0)

  const reload = useCallback(() => setNonce((n) => n + 1), [])

  useEffect(() => {
    let alive = true
    setLoading(true)
    setError(null)
    fn()
      .then((result) => { if (alive) { setData(result); setLoading(false) } })
      .catch((err) => {
        // Request bị hủy do rời trang thì không phải lỗi — báo lên giao diện
        // sẽ hiện hộp đỏ ngay lúc người dùng vừa bấm đi chỗ khác.
        if (!alive || err.name === 'AbortError') return
        setError(err)
        setLoading(false)
      })
    return () => { alive = false }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, nonce])

  return { data, error, loading, reload, setData }
}
