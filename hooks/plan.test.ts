import { test, expect } from 'claude-code/testing'

import { plan } from './plan'

test('with no argument it shows the status and how to set up', () => {
  const p = plan('', false, 'no copy yet')
  expect(p.run).toBe(false)
  expect(p.text).toContain('no copy yet')
  expect(p.text).toContain('/rtl install')
})

test('install asks first, and says what it does', () => {
  const p = plan('install', false, 'x')
  expect(p.run).toBe(false)
  expect(p.text).toContain('closes Claude')
  expect(p.text).toContain('/rtl install yes')
})

test('install yes starts the job', () => {
  expect(plan('install yes', false, 'x').run).toBe(true)
})

test('an app that is already patched is left alone', () => {
  expect(plan('install yes', true, 'patched in place').run).toBe(false)
  expect(plan('install', true, 'patched in place').text).toContain('Already active')
})

test('extra spaces around the argument do not matter', () => {
  expect(plan('  install yes ', false, 'x').run).toBe(true)
})

test('install yes tells the user to click Always Allow, never Deny', () => {
  const t = plan('install yes', false, 'x').text
  expect(t).toContain('Always Allow')
  expect(t).toContain('Deny')
})
