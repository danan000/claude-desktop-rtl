import { test, expect } from 'claude-code/testing'

import { plan } from './plan'

test('with no argument it shows the status and how to set up', () => {
  const p = plan('', false, 'no copy yet')
  expect(p.run).toBeNull()
  expect(p.text).toContain('no copy yet')
  expect(p.text).toContain('/rtl install')
})

test('install asks first, and says what it does', () => {
  const p = plan('install', false, 'x')
  expect(p.run).toBeNull()
  expect(p.text).toContain('closes Claude')
  expect(p.text).toContain('/rtl install yes')
})

test('install yes starts the install job', () => {
  expect(plan('install yes', false, 'x').run).toBe('install')
})

test('an app that is already patched is left alone', () => {
  expect(plan('install yes', true, 'patched in place').run).toBeNull()
  expect(plan('install', true, 'patched in place').text).toContain('Already active')
})

test('extra spaces around the argument do not matter', () => {
  expect(plan('  install yes ', false, 'x').run).toBe('install')
})

test('install yes tells the user to click Always Allow, never Deny', () => {
  const t = plan('install yes', false, 'x').text
  expect(t).toContain('Always Allow')
  expect(t).toContain('Deny')
})

test('uninstall asks first, and uninstall yes starts the uninstall job', () => {
  const ask = plan('uninstall', true, 'x')
  expect(ask.run).toBeNull()
  expect(ask.text).toContain('/rtl uninstall yes')
  expect(plan('uninstall yes', true, 'x').run).toBe('uninstall')
})

test('uninstall on an app that is not patched does nothing', () => {
  expect(plan('uninstall yes', false, 'x').run).toBeNull()
  expect(plan('uninstall yes', false, 'x').text).toContain('Nothing to undo')
})

test('after uninstall the text says how to stop the reminder', () => {
  expect(plan('uninstall yes', true, 'x').text).toContain('/plugin uninstall rtl-hebrew')
})
