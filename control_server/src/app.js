'use strict'

/**
 * Fastify app factory — nơi ráp plugin và route.
 *
 * Tách khỏi `server.js` để test dựng được app mà không mở cổng mạng.
 */
const fs = require('node:fs')
const path = require('node:path')

const Fastify = require('fastify')

// Backend tự serve luôn website (../website/dist) — cùng origin nên frontend
// gọi API bằng đường dẫn tương đối, KHÔNG cần CORS, không cần build lại khi
// đổi domain. Đổi chỗ chứa dist bằng WEB_DIST nếu deploy kiểu khác.
const WEB_DIST = process.env.WEB_DIST
  || path.join(__dirname, '..', '..', 'website', 'dist')

async function build(opts = {}) {
  const app = Fastify({
    logger: opts.logger !== undefined ? opts.logger : {
      level: process.env.LOG_LEVEL || 'info',
      redact: ['req.headers.authorization', 'req.headers["x-admin-token"]'],
    },
    trustProxy: process.env.TRUST_PROXY === '1',
    bodyLimit: 4 * 1024 * 1024,   // transcript một video dài vẫn lọt
    ...opts.fastify,
  })

  await app.register(require('@fastify/helmet'), { contentSecurityPolicy: false })

  // Website được backend serve cùng origin nên trình duyệt KHÔNG cần CORS.
  // Danh sách này chỉ để phòng khi website được host tách rời (CORS_ORIGIN),
  // mặc định thêm PUBLIC_URL cho chắc. App desktop không gửi Origin — luôn qua.
  const origins = (process.env.CORS_ORIGIN || process.env.PUBLIC_URL || '')
    .split(',').map((s) => s.trim().replace(/\/+$/, '')).filter(Boolean)
  await app.register(require('@fastify/cors'), {
    // Cùng origin thì trình duyệt không gửi preflight; danh sách chỉ dùng
    // khi host tách rời.
    origin: origins.length ? origins : false,
    methods: ['GET', 'POST', 'PATCH', 'PUT', 'DELETE'],
    // Admin panel gửi token qua header riêng; thiếu dòng này thì trình duyệt
    // chặn preflight và mọi thao tác quản trị đều hỏng với lỗi CORS khó hiểu.
    allowedHeaders: ['Content-Type', 'Authorization', 'X-Admin-Token'],
  })

  await app.register(require('@fastify/rate-limit'), {
    global: true,
    max: 200,
    timeWindow: '1 minute',
    // Giới hạn theo thiết bị khi có token, theo IP khi chưa — nhiều máy sau
    // cùng một NAT không được phép chặn lẫn nhau.
    keyGenerator: (request) => {
      const auth = request.headers.authorization || ''
      if (auth.startsWith('Bearer ')) return auth.slice(-32)
      // Admin panel bắn nhiều request khi mở dashboard (5-6 bảng cùng lúc)
      // và luôn từ một IP — tách khỏi hạn mức chung để không tự chặn mình.
      if (request.headers['x-admin-token']) return `admin:${request.ip}`
      return request.ip
    },
  })

  if (opts.mongo !== false) {
    await app.register(require('./plugins/mongo'))
  }

  app.get('/health', async () => ({
    ok: true,
    version: '3.0.0',
    uptimeS: Math.round(process.uptime()),
  }))

  await app.register(require('./routes/config'), { prefix: '/v1/config' })
  await app.register(require('./routes/device'), { prefix: '/v1/device' })
  await app.register(require('./routes/ai'), { prefix: '/v1/ai' })
  await app.register(require('./routes/holds'), { prefix: '/v1/holds' })
  await app.register(require('./routes/billing'), { prefix: '/v1/billing' })
  await app.register(require('./routes/admin'), { prefix: '/v1/admin' })

  // Website tĩnh (nếu đã build). SPA: đường dẫn lạ ngoài /v1 trả index.html.
  const hasWeb = opts.web !== false && fs.existsSync(path.join(WEB_DIST, 'index.html'))
  if (hasWeb) {
    await app.register(require('@fastify/static'), {
      root: WEB_DIST,
      wildcard: false,
      cacheControl: false,   // hook onSend bên dưới tự quyết định cache
    })
    // Tài nguyên băm tên (assets/) cache 1 năm; còn lại luôn hỏi lại server.
    app.addHook('onSend', async (request, reply) => {
      if (request.method === 'GET' && !request.url.startsWith('/v1')
          && !reply.getHeader('cache-control')) {
        reply.header('Cache-Control', request.url.startsWith('/assets/')
          ? 'public, max-age=31536000, immutable'
          : 'no-cache')
      }
    })
  }

  // Lỗi không lường trước: log đầy đủ phía server, nói ngắn gọn phía client —
  // stack trace lộ ra ngoài là món quà cho người dò lỗ hổng.
  app.setErrorHandler((err, request, reply) => {
    if (err.validation) {
      return reply.code(400).send({
        code: 'VALIDATION_ERROR',
        message: 'Dữ liệu gửi lên không hợp lệ.',
        details: err.validation.map((v) => `${v.instancePath || 'body'} ${v.message}`),
      })
    }
    if (err.statusCode && err.statusCode < 500) {
      return reply.code(err.statusCode).send({
        code: err.code || 'ERROR',
        message: err.message,
      })
    }
    request.log.error({ err }, 'unhandled error')
    return reply.code(500).send({ code: 'INTERNAL', message: 'Lỗi máy chủ.' })
  })

  app.setNotFoundHandler((request, reply) => {
    // SPA fallback: GET một trang không phải API (vd /mua, /admin/orders)
    // thì trả index.html cho React Router lo phần còn lại.
    if (hasWeb && request.method === 'GET' && !request.url.startsWith('/v1')) {
      reply.header('Cache-Control', 'no-cache')
      return reply.type('text/html').send(fs.readFileSync(path.join(WEB_DIST, 'index.html')))
    }
    reply.code(404).send({ code: 'NOT_FOUND', message: 'Không có endpoint này.' })
  })

  return app
}

module.exports = { build }
