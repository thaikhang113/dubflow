'use strict'

/**
 * Sinh và chuẩn hóa mã kích hoạt.
 *
 * Định dạng: `VOX-XXXX-XXXX-XXXX` với bảng chữ Crockford rút gọn — bỏ
 * I/O/0/1/U để người dùng đọc từ email rồi gõ tay vào app không nhầm được
 * (I↔1, O↔0 là hai lỗi gõ phổ biến nhất; U bỏ để tránh sinh ra từ tục).
 *
 * 3 nhóm × 4 ký tự trên bảng 30 ký tự ≈ 5.3e17 tổ hợp — không dò được, và
 * `code` có UNIQUE index nên trùng ngẫu nhiên cũng chỉ là một lần thử lại.
 */
const crypto = require('node:crypto')

const ALPHABET = '23456789ABCDEFGHJKLMNPQRSTVWXYZ'
const GROUPS = 3
const GROUP_LEN = 4

function generateKeyCode() {
  const bytes = crypto.randomBytes(GROUPS * GROUP_LEN)
  const chars = Array.from(bytes, (b) => ALPHABET[b % ALPHABET.length])
  const groups = []
  for (let i = 0; i < GROUPS; i += 1) {
    groups.push(chars.slice(i * GROUP_LEN, (i + 1) * GROUP_LEN).join(''))
  }
  return `VOX-${groups.join('-')}`
}

/**
 * Chuẩn hóa mã người dùng gõ vào: hoa hết, bỏ khoảng trắng và gạch nối, rồi
 * chấm lại dấu gạch. Người dùng dán kèm khoảng trắng, gõ thường, hay quên
 * gạch nối đều ra cùng một mã.
 *
 * Ký tự ngoài bảng (I, O, 0, 1, U) là gõ nhầm — quy về ký tự trông giống
 * nhất đang có trong bảng, thay vì bắt người dùng tự tìm ra mình sai chỗ nào.
 * Trả về "" khi độ dài không đúng.
 */
const _TYPO_FIX = { O: 'Q', '0': 'Q', I: 'J', '1': 'J', L: 'L', U: 'V' }

function normalizeKeyCode(raw) {
  let s = String(raw || '').toUpperCase().replace(/[^0-9A-Z]/g, '')
  if (s.startsWith('VOX')) s = s.slice(3)
  s = s.replace(/[IO01U]/g, (c) => _TYPO_FIX[c])
  if (s.length !== GROUPS * GROUP_LEN) return ''
  if ([...s].some((c) => !ALPHABET.includes(c))) return ''
  const groups = []
  for (let i = 0; i < GROUPS; i += 1) {
    groups.push(s.slice(i * GROUP_LEN, (i + 1) * GROUP_LEN))
  }
  return `VOX-${groups.join('-')}`
}

/** Mã đơn hàng — chỉ chữ HOA + số, vì ngân hàng lọc ký tự đặc biệt. */
function generateOrderCode() {
  const n = crypto.randomInt(0, 1_000_000).toString().padStart(6, '0')
  return `VOX${n}`
}

module.exports = { generateKeyCode, normalizeKeyCode, generateOrderCode, ALPHABET }
