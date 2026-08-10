'use strict'

/**
 * Kiểm thử các tiện ích thuần (không cần MongoDB, không cần npm install):
 * mã kích hoạt, mã hóa API key, và bộ đọc JSON của mô hình.
 *
 * Chạy:  node --test tests/
 */
const test = require('node:test')
const assert = require('node:assert')

const {
  generateKeyCode, normalizeKeyCode, generateOrderCode, ALPHABET,
} = require('../src/utils/keycode')
const {
  containsCjk, stripFences, repairJson, parseResponseSegments,
  parseJsonObject, ensureTerminalPunct, mergeTranslations,
} = require('../src/utils/json-repair')

// ------------------------------------------------------------ mã kích hoạt --

test('mã kích hoạt đúng định dạng VOX-XXXX-XXXX-XXXX', () => {
  assert.match(generateKeyCode(), /^VOX-[0-9A-Z]{4}-[0-9A-Z]{4}-[0-9A-Z]{4}$/)
})

test('mã kích hoạt chỉ dùng ký tự không gây đọc nhầm', () => {
  for (let i = 0; i < 200; i += 1) {
    const body = generateKeyCode().slice(4).replace(/-/g, '')
    for (const ch of body) assert.ok(ALPHABET.includes(ch), `ký tự lạ: ${ch}`)
    assert.ok(!/[IO01U]/.test(body), 'chứa ký tự dễ đọc nhầm')
  }
})

test('mã kích hoạt không trùng nhau trong 2000 lần sinh', () => {
  const seen = new Set()
  for (let i = 0; i < 2000; i += 1) seen.add(generateKeyCode())
  assert.equal(seen.size, 2000)
})

test('chuẩn hóa: chữ thường, khoảng trắng và thiếu gạch nối đều ra cùng mã', () => {
  const code = generateKeyCode()
  const body = code.slice(4).replace(/-/g, '')
  assert.equal(normalizeKeyCode(code.toLowerCase()), code)
  assert.equal(normalizeKeyCode(`  ${code}  `), code)
  assert.equal(normalizeKeyCode(body), code)
  assert.equal(normalizeKeyCode(`vox ${body}`), code)
})

test('chuẩn hóa: sửa lỗi gõ nhầm O/0, I/1, U', () => {
  // Người dùng chép mã từ email rồi gõ tay — O↔0 và I↔1 là hai lỗi phổ biến
  // nhất, quy về ký tự hợp lệ thay vì bắt họ tự tìm ra mình sai chỗ nào.
  assert.equal(normalizeKeyCode('VOX-QJVA-2345-6789'),
    normalizeKeyCode('VOX-0IUA-2345-6789'))
})

test('chuẩn hóa: sai độ dài trả về chuỗi rỗng', () => {
  assert.equal(normalizeKeyCode('VOX-ABC'), '')
  assert.equal(normalizeKeyCode('VOX-ABCD-EFGH-IJKL-MNOP'), '')
  assert.equal(normalizeKeyCode(''), '')
  assert.equal(normalizeKeyCode(null), '')
})

test('mã đơn hàng chỉ chữ HOA và số (ngân hàng lọc ký tự đặc biệt)', () => {
  for (let i = 0; i < 100; i += 1) {
    assert.match(generateOrderCode(), /^VOX\d{6}$/)
  }
})

// ------------------------------------------------------------ mã hóa key ---

test('mã hóa API key: giải mã ra đúng bản gốc', () => {
  process.env.APP_ENCRYPTION_KEY = 'a'.repeat(64)
  const { encrypt, decrypt } = require('../src/utils/crypto')
  const secret = 'sk-or-v1-abc123xyz'
  assert.equal(decrypt(encrypt(secret)), secret)
})

test('mã hóa API key: mỗi lần mã hóa ra chuỗi khác nhau (IV ngẫu nhiên)', () => {
  process.env.APP_ENCRYPTION_KEY = 'a'.repeat(64)
  const { encrypt } = require('../src/utils/crypto')
  assert.notEqual(encrypt('same'), encrypt('same'))
})

test('mã hóa API key: sửa một byte trong DB thì giải mã thất bại', () => {
  process.env.APP_ENCRYPTION_KEY = 'a'.repeat(64)
  const { encrypt, decrypt } = require('../src/utils/crypto')
  const enc = encrypt('sk-secret')
  const [iv, tag, data] = enc.split(':')
  const tampered = `${iv}:${tag}:${data.slice(0, -2)}00`
  assert.throws(() => decrypt(tampered))
})

test('mã hóa API key: chuỗi rỗng đi qua nguyên vẹn', () => {
  process.env.APP_ENCRYPTION_KEY = 'a'.repeat(64)
  const { encrypt, decrypt } = require('../src/utils/crypto')
  assert.equal(encrypt(''), '')
  assert.equal(decrypt(''), '')
})

test('so sánh secret an toàn về thời gian', () => {
  const { safeEqual } = require('../src/utils/crypto')
  assert.ok(safeEqual('abc', 'abc'))
  assert.ok(!safeEqual('abc', 'abd'))
  assert.ok(!safeEqual('abc', 'abcdef'))   // khác độ dài vẫn so được
  assert.ok(!safeEqual('', ''))
  assert.ok(!safeEqual(null, 'abc'))
})

// ---------------------------------------------------------- đọc JSON ------

test('dò chữ Hán', () => {
  assert.ok(containsCjk('Xin chào 你好'))
  assert.ok(!containsCjk('Xin chào mọi người'))
  assert.ok(!containsCjk(''))
})

test('bóc khối ```json bọc ngoài', () => {
  assert.equal(stripFences('```json\n{"a":1}\n```'), '{"a":1}')
  assert.equal(stripFences('```\n[1]\n```'), '[1]')
  assert.equal(stripFences('{"a":1}'), '{"a":1}')
})

test('đọc được cả {"segments": [...]} lẫn mảng trần', () => {
  assert.deepEqual(
    parseResponseSegments('{"segments":[{"id":1,"text_vi":"A"}]}'),
    [{ id: 1, text_vi: 'A' }])
  assert.deepEqual(parseResponseSegments('[{"id":1}]'), [{ id: 1 }])
})

test('đọc được khi mô hình chèn câu dẫn quanh JSON', () => {
  const out = parseResponseSegments(
    'Here is the JSON:\n{"segments":[{"id":2,"text_vi":"B"}]}\nHope it helps!')
  assert.deepEqual(out, [{ id: 2, text_vi: 'B' }])
})

test('vá JSON bị cắt giữa chừng, giữ lại các câu đã hoàn chỉnh', () => {
  // Chạm trần token: mảng và object ngoài cùng chưa đóng, nhưng hai segment
  // đầu đã trọn vẹn — cứu được chúng thay vì vứt cả lô đã tốn tiền gọi.
  const truncated = '{"segments":[{"id":1,"text_vi":"Một."},{"id":2,"text_vi":"Hai."}'
  const out = parseResponseSegments(truncated)
  assert.equal(out.length, 2)
  assert.equal(out[0].text_vi, 'Một.')
  assert.equal(out[1].text_vi, 'Hai.')
})

test('vá JSON: segment cuối bị cắt giữa chuỗi thì bỏ, giữ phần trước', () => {
  const out = parseResponseSegments(
    '{"segments":[{"id":1,"text_vi":"Một."},{"id":2,"text_vi":"Hai.')
  assert.equal(out.length, 1)
  assert.equal(out[0].text_vi, 'Một.')
})

test('vá JSON: bỏ khóa dở dang ở cuối', () => {
  const out = parseResponseSegments(
    '{"segments":[{"id":1,"text_vi":"Một."},{"id":2,"text_')
  assert.equal(out.length, 1)
  assert.equal(out[0].id, 1)
})

test('vá JSON: đóng đúng thứ tự ngoặc đã mở', () => {
  assert.deepEqual(JSON.parse(repairJson('{"a": [1, 2')).a, [1, 2])
})

test('hỏng hoàn toàn thì ném lỗi kèm mẩu nội dung', () => {
  assert.throws(
    () => parseResponseSegments('hoàn toàn không phải JSON'),
    /JSON hỏng/)
})

test('đọc object bất kỳ, trả null khi hỏng', () => {
  assert.deepEqual(parseJsonObject('```json\n{"domain":"game"}\n```'),
    { domain: 'game' })
  assert.equal(parseJsonObject('không phải JSON'), null)
  assert.equal(parseJsonObject('[1,2,3]'), null)   // mảng không phải object
})

// ------------------------------------------------------- chuẩn hóa câu ----

test('thêm dấu kết câu khi thiếu', () => {
  assert.equal(ensureTerminalPunct('Xin chào'), 'Xin chào.')
  assert.equal(ensureTerminalPunct('Thật à?'), 'Thật à?')
  assert.equal(ensureTerminalPunct('Trời ơi!'), 'Trời ơi!')
  assert.equal(ensureTerminalPunct('Còn nữa…'), 'Còn nữa…')
})

test('thay dấu giữa câu ở cuối bằng dấu chấm', () => {
  // TTS phải hạ giọng ở cuối câu; dấu phẩy làm giọng treo lơ lửng rồi đâm
  // thẳng vào câu sau.
  assert.equal(ensureTerminalPunct('Xin chào,'), 'Xin chào.')
  assert.equal(ensureTerminalPunct('Xin chào —'), 'Xin chào.')
})

test('gom khoảng trắng thừa về một dấu cách', () => {
  assert.equal(ensureTerminalPunct('Xin   chào\n\nmọi người'),
    'Xin chào mọi người.')
})

// ------------------------------------------------------------- ghép -------

test('ghép theo id, không theo vị trí', () => {
  const { merged, missing } = mergeTranslations(
    [{ id: 1 }, { id: 2 }],
    [{ id: 2, text_vi: 'Hai' }, { id: 1, text_vi: 'Một' }],
    'text_vi')
  assert.equal(missing.length, 0)
  assert.deepEqual(merged.map((m) => m.text_vi), ['Một.', 'Hai.'])
})

test('ghép theo vị trí khi mô hình quên id nhưng đúng số câu', () => {
  const { merged, missing } = mergeTranslations(
    [{ id: 7 }, { id: 8 }],
    [{ text_vi: 'Một' }, { text_vi: 'Hai' }],
    'text_vi')
  assert.equal(missing.length, 0)
  assert.deepEqual(merged.map((m) => m.id), [7, 8])
})

test('báo đúng câu nào thiếu để lớp trên chia đôi lô', () => {
  const { merged, missing } = mergeTranslations(
    [{ id: 1 }, { id: 2 }, { id: 3 }],
    [{ id: 1, text_vi: 'Một' }],
    'text_vi')
  assert.equal(merged.length, 1)
  assert.deepEqual(missing, [2, 3])
})

test('bản dịch rỗng tính là thiếu', () => {
  const { missing } = mergeTranslations(
    [{ id: 1 }], [{ id: 1, text_vi: '   ' }], 'text_vi')
  assert.deepEqual(missing, [1])
})

test('id dạng chuỗi vẫn ghép được', () => {
  const { merged, missing } = mergeTranslations(
    [{ id: 5 }], [{ id: '5', text_vi: 'Năm' }], 'text_vi')
  assert.equal(missing.length, 0)
  assert.equal(merged[0].text_vi, 'Năm.')
})

// -------------------------------------------------- bảo vệ mã đơn hàng ----

test('orderView giấu keyCode khi không có token', () => {
  process.env.APP_ENCRYPTION_KEY = 'a'.repeat(64)
  const { orderView, tokenMatches } = require('../src/services/billing.service')
  const order = {
    orderCode: 'VOX123456', amountVnd: 50000, vox: 5500,
    packageId: 'standard', packageLabel: 'Phổ thông', status: 'paid',
    keyCode: 'VOX-AAAA-BBBB-CCCC', accessToken: 'secret-token',
    createdAt: new Date(0), expiresAt: new Date(0), paidAt: new Date(0),
  }
  // Mã đơn chỉ 6 chữ số nên dò được — nó không bao giờ đủ để lấy hàng.
  assert.equal(orderView(order).keyCode, '')
  assert.equal(orderView(order, { authorized: false }).keyCode, '')
  assert.equal(orderView(order, { authorized: true }).keyCode, 'VOX-AAAA-BBBB-CCCC')
})

test('orderView vẫn cho biết trạng thái khi không có token', () => {
  const { orderView } = require('../src/services/billing.service')
  const order = {
    orderCode: 'VOX123456', amountVnd: 50000, vox: 5500, status: 'paid',
    keyCode: 'VOX-AAAA-BBBB-CCCC', accessToken: 't',
    createdAt: new Date(0), expiresAt: new Date(0), paidAt: new Date(0),
  }
  assert.equal(orderView(order).status, 'paid')
})

test('orderView không lộ key khi đơn chưa thanh toán, kể cả có token', () => {
  const { orderView } = require('../src/services/billing.service')
  const order = {
    orderCode: 'VOX123456', amountVnd: 50000, vox: 5500, status: 'pending',
    keyCode: '', accessToken: 't',
    createdAt: new Date(0), expiresAt: new Date(0), paidAt: null,
  }
  assert.equal(orderView(order, { authorized: true }).keyCode, '')
})

test('tokenMatches từ chối token sai, rỗng và thiếu', () => {
  process.env.APP_ENCRYPTION_KEY = 'a'.repeat(64)
  const { tokenMatches } = require('../src/services/billing.service')
  const order = { accessToken: 'the-real-token' }
  assert.ok(tokenMatches(order, 'the-real-token'))
  assert.ok(!tokenMatches(order, 'the-real-toke'))
  assert.ok(!tokenMatches(order, ''))
  assert.ok(!tokenMatches(order, undefined))
  assert.ok(!tokenMatches({ accessToken: '' }, ''))
})
