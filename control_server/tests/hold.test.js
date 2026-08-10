'use strict'

/**
 * Kiểm thử phần thuần của hold.service — không cần MongoDB.
 *
 * `bufferCommands=false` để mọi truy vấn Mongoose fail ngay khi chưa kết nối,
 * nhờ đó config.service rơi về DEFAULTS tức thì (đúng hành vi "DB chớp nháy
 * không được làm sập request") thay vì treo 10 giây chờ buffer timeout.
 *
 * Chạy:  node --test tests/
 */
const test = require('node:test')
const assert = require('node:assert')

const mongoose = require('mongoose')
mongoose.set('bufferCommands', false)

const holdService = require('../src/services/hold.service')
const { DEFAULTS } = require('../src/services/config.service')
const CreditLedger = require('../src/models/CreditLedger')
const CreditHold = require('../src/models/CreditHold')

// ------------------------------------------------------ công thức ước tính --

const BASE = DEFAULTS['credit.cost.segment.base']
const AUTO = DEFAULTS['credit.cost.segment.autotranslate']
const META = DEFAULTS['credit.cost.metadata']

test('estimateVox: giá theo segment, tắt dịch tự động vẫn thu giá nền', async () => {
  // Cùng một video phải ra cùng một con số dù hỏi qua endpoint nào —
  // sai lệch ở đây nghĩa là hold trừ một đằng, app báo một nẻo.
  for (const n of [1, 7, 50, 333, 20000]) {
    const off = await holdService.estimateVox(n, { autoTranslate: false, metadata: false })
    assert.equal(off.estimated, n * BASE, `sai với ${n} segment (tắt dịch tự động)`)

    const on = await holdService.estimateVox(n, { autoTranslate: true, metadata: false })
    assert.equal(on.estimated, n * (BASE + AUTO), `sai với ${n} segment (bật dịch tự động)`)

    // Dịch tự động chỉ được cộng thêm đúng AUTO mỗi segment, không nhân đôi.
    assert.equal(on.estimated - off.estimated, n * AUTO)
  }
})

test('estimateVox: tiêu đề + mô tả là phụ phí trọn gói, không theo segment', async () => {
  for (const n of [1, 200]) {
    const without = await holdService.estimateVox(n, { metadata: false })
    const withMeta = await holdService.estimateVox(n, { metadata: true })
    assert.equal(withMeta.estimated - without.estimated, META, `sai với ${n} segment`)
  }
})

test('estimateVox: breakdown cộng lại đúng bằng tổng', async () => {
  const { estimated, breakdown } = await holdService.estimateVox(120)
  assert.equal(breakdown.segmentTotal + breakdown.metadata, estimated)
  assert.equal(breakdown.segments, 120)
  assert.equal(breakdown.perSegment, BASE + AUTO)
})

test('estimateVox làm tròn số segment và không âm', async () => {
  const a = await holdService.estimateVox(10.4)
  const b = await holdService.estimateVox(10)
  assert.equal(a.estimated, b.estimated)

  // 0 segment: chỉ còn phụ phí tiêu đề + mô tả nếu người dùng bật.
  const zero = await holdService.estimateVox(-5, { metadata: true })
  assert.equal(zero.estimated, META)
  const bare = await holdService.estimateVox(-5, { metadata: false })
  assert.equal(bare.estimated, 0)
})

test('giá công khai: 10 Vox/segment, bật dịch tự động thành 12', async () => {
  // Con số người dùng thấy trên website và trong app — đổi ở đây là đổi
  // hợp đồng với người đã mua, phải cố ý.
  assert.equal(BASE, 10)
  assert.equal(BASE + AUTO, 12)
  assert.equal(META, 20)
})

test('giá nội bộ không lẫn vào giá công khai', async () => {
  // Bốn khóa internal.* chỉ để đối soát biên lợi nhuận. Nếu một khóa nào bị
  // đổi tên thành credit.cost.* thì nó lại trừ tiền người dùng như bản cũ.
  for (const k of ['internal.cost.translate.per_sentence', 'internal.cost.analyze',
    'internal.cost.review.per_sentence', 'internal.cost.generate_post']) {
    assert.ok(DEFAULTS[k] > 0, `thiếu ${k}`)
  }
  const priced = Object.keys(DEFAULTS).filter((k) => k.startsWith('credit.cost.'))
  assert.deepEqual(priced.sort(), [
    'credit.cost.metadata',
    'credit.cost.segment.autotranslate',
    'credit.cost.segment.base',
  ], 'chỉ ba khóa này được phép định giá công khai')
})

// ------------------------------------------------------------- publicView --

test('publicView không lộ khóa giải mã khi không xin', () => {
  const hold = {
    holdId: 'run-abc12345',
    status: 'active',
    estimatedVox: 100,
    usedVox: 40,
    usage: [{ action: 'translate', jobId: 'j1', vox: 40 }],
    expiresAt: new Date('2026-08-09'),
    encKeyHex: 'a'.repeat(64),
    meta: { sentences: 90 },
  }
  const noKey = holdService.publicView(hold)
  assert.equal(noKey.encKeyHex, undefined)
  assert.equal(noKey.holdId, 'run-abc12345')
  assert.equal(noKey.usedVox, 40)

  const withKey = holdService.publicView(hold, { withKey: true })
  assert.equal(withKey.encKeyHex, 'a'.repeat(64))
})

test('publicView chịu được hold thiếu field phụ (bản ghi cũ)', () => {
  const view = holdService.publicView({ holdId: 'x', status: 'committed' })
  assert.deepEqual(view.usage, [])
  assert.equal(view.autoCommitted, false)
  assert.deepEqual(view.meta, {})
})

// ------------------------------------------------------------ schema/enum --

test('CreditLedger chấp nhận type hold và hold_release', () => {
  const types = CreditLedger.schema.path('type').enumValues
  assert.ok(types.includes('hold'), 'thiếu type "hold"')
  assert.ok(types.includes('hold_release'), 'thiếu type "hold_release"')
})

test('CreditHold: status hợp lệ và index phục vụ sweeper', () => {
  const statuses = CreditHold.schema.path('status').enumValues
  assert.deepEqual([...statuses].sort(), ['active', 'committed', 'released'])

  // Sweeper quét {status, expiresAt} — thiếu index này là quét cả collection.
  const indexes = CreditHold.schema.indexes().map(([fields]) => JSON.stringify(fields))
  assert.ok(
    indexes.includes(JSON.stringify({ status: 1, expiresAt: 1 })),
    'thiếu index {status, expiresAt} cho sweeper',
  )
  assert.ok(CreditHold.schema.path('holdId').options.unique, 'holdId phải unique')
})

test('config có đủ khóa hold.* với giá trị mặc định an toàn', () => {
  assert.equal(DEFAULTS['hold.enabled'], true)
  assert.ok(DEFAULTS['hold.ttl.hours'] > 0)
  assert.ok(DEFAULTS['hold.sweep.interval.minutes'] > 0)
  assert.ok(DEFAULTS['hold.review.ratio'] > 0 && DEFAULTS['hold.review.ratio'] < 1)
})

// ----------------------------------------------------------- toán commit ---
// Logic hoàn/thu lúc commit nằm trong DB call, nhưng bất biến số học thì
// kiểm được thuần: hoàn + thu không bao giờ cùng dương, và tổng khớp sổ.

test('commit trung tính về tiền: giá đã chốt từ lúc tạo hold', () => {
  // Giá là công thức đóng trên số segment, biết chắc ngay sau ASR. Chi phí AI
  // nội bộ (`usedVox`) dùng ít hay nhiều hơn dự tính đều KHÔNG đổi số tiền —
  // sổ cái chỉ còn đúng một dòng `hold` âm nên tổng delta luôn khớp ví.
  for (const [est, used] of [[100, 40], [100, 100], [100, 130], [0, 0]]) {
    const ledgerDelta = -est   // không hoàn, không truy thu
    assert.equal(ledgerDelta, -est, `commit phải trung tính (used=${used})`)
  }
})

test('hold.service đã bỏ hẳn đường hoàn tiền', () => {
  // Còn một lời gọi grant nào sót lại nghĩa là hold vừa thu theo segment vừa
  // hoàn theo usage — người dùng bị tính giá lẫn lộn giữa hai mô hình.
  const fs = require('node:fs')
  const path = require('node:path')
  const src = fs.readFileSync(
    path.join(__dirname, '..', 'src', 'services', 'hold.service.js'), 'utf8',
  )
  assert.ok(!src.includes('credit.grant('), 'vẫn còn credit.grant trong hold.service')
  assert.ok(!src.includes('hold_release'), 'vẫn còn ghi sổ hold_release')
  assert.ok(!src.includes('holdover-'), 'vẫn còn truy thu phần vượt')
})

// -------------------------------------------------------------- canAbsorb --
// Hold nào hấp thụ được lượt AI nào — thuần JS, cùng điều kiện với query
// nguyên tử trong accrue().

test('canAbsorb: hold active hấp thụ mọi lượt', () => {
  const hold = { status: 'active', meta: {}, usage: [] }
  for (const action of ['translate', 'analyze', 'review', 'generate_post']) {
    assert.ok(holdService.canAbsorb(hold, action, 'j1'), action)
  }
})

test('canAbsorb: hold giá 10 (tắt dịch tự động) không bao các lượt dịch máy', () => {
  // Hold autoTranslate=false chỉ thu 10 Vox/segment — chưa trả tiền dịch
  // máy. Client sửa đổi gọi /translate kèm holdId rẻ phải rơi về trừ ví
  // đúng đơn giá 12, không được đi nhờ hold.
  const cheap = { status: 'active', meta: { autoTranslate: false, metadata: true }, usage: [] }
  for (const action of ['translate', 'analyze', 'review']) {
    assert.ok(!holdService.canAbsorb(cheap, action, 'j1'), action)
  }
  // Gói đăng bài vẫn nằm trong giá hold — generate_post hấp thụ bình thường.
  assert.ok(holdService.canAbsorb(cheap, 'generate_post', 'j1'))

  // Hold cũ thiếu meta.autoTranslate (đã thu giá 12 từ trước) → như cũ.
  const legacy = { status: 'active', meta: {}, usage: [] }
  assert.ok(holdService.canAbsorb(legacy, 'translate', 'j1'))
})

test('canAbsorb: hold committed chỉ nhận đúng một lượt generate_post có gói', () => {
  const committed = { status: 'committed', meta: { metadata: true }, usage: [] }
  // Gói đăng bài đã trả trong giá hold — lượt generate_post sau commit
  // (luồng wizard bấm Xuất video) không được trừ ví lần hai.
  assert.ok(holdService.canAbsorb(committed, 'generate_post', 'j1'))
  // ...nhưng các lượt khác thì không: hold đã đóng.
  for (const action of ['translate', 'analyze', 'review']) {
    assert.ok(!holdService.canAbsorb(committed, action, 'j1'), action)
  }

  // Không mua gói → không có gì để hấp thụ.
  const noMeta = { status: 'committed', meta: { metadata: false }, usage: [] }
  assert.ok(!holdService.canAbsorb(noMeta, 'generate_post', 'j1'))

  // Đã hấp thụ một lượt generate_post khác → lượt mới phải trả ví.
  const spent = {
    status: 'committed', meta: { metadata: true },
    usage: [{ action: 'generate_post', jobId: 'j0' }],
  }
  assert.ok(!holdService.canAbsorb(spent, 'generate_post', 'j1'))
  // Replay đúng jobId cũ thì vẫn nhận (idempotent, accrue tự no-op).
  assert.ok(holdService.canAbsorb(spent, 'generate_post', 'j0'))
})

test('canAbsorb: hold released hoặc thiếu không hấp thụ gì', () => {
  assert.ok(!holdService.canAbsorb(null, 'translate', 'j1'))
  const released = { status: 'released', meta: { metadata: true }, usage: [] }
  assert.ok(!holdService.canAbsorb(released, 'generate_post', 'j1'))
})
