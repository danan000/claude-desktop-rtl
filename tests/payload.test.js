const test = require('node:test')
const assert = require('node:assert')

const { isRtl } = require('../payload.js')

test('a Hebrew line is RTL', () => assert.equal(isRtl('שלום עולם'), true))

test('a Hebrew line that opens with English is RTL', () =>
  assert.equal(isRtl('API שלום עולם, יש 16 tests ו-0 שנכשלו.'), true))

test('an English line with one Hebrew word is LTR', () =>
  assert.equal(isRtl('this line is mostly English, רק מילה אחת עברית.'), false))

test('Arabic is RTL', () => assert.equal(isRtl('مرحبا بالعالم'), true))

test('English, digits and empty text are LTR', () => {
  assert.equal(isRtl('hello world'), false)
  assert.equal(isRtl('2026-11-01 12345'), false)
  assert.equal(isRtl(''), false)
})

test('equal counts of words go RTL', () => assert.equal(isRtl('שלום abcd'), true))

// Long English names have more letters than the Hebrew around them. Words count, not letters.
test('a Hebrew sentence with long English names is RTL', () =>
  assert.equal(isRtl('הקובץ נמצא ב-rtl-desktop ולא הועבר ל-production.'), true))

test('a Hebrew-first line with a long English tail is RTL', () =>
  assert.equal(isRtl('הרצתי npm install git push עכשיו'), true))

test('an English-first line with a short Hebrew tail is LTR', () =>
  assert.equal(isRtl('run npm install now הרצתי'), false))
