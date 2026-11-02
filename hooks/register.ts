import type { EngineInterface, Register } from 'claude-code'

import { plan } from './plan'

const PYTHON = '/usr/bin/python3'

async function status($: EngineInterface) {
  const r = await $.process.run([PYTHON, `${$.plugin.root}/rtl.py`, 'status'], { timeoutMs: 20000 }).catch(() => null)
  return { patched: r?.exitCode === 0, line: (r?.stdout || r?.stderr || 'status unknown').trim().split('\n')[0]! }
}

export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    if (!(await $.session.surfaces()).includes('desktop')) return next(e)
    await $.command.register({ name: 'rtl', description: 'Hebrew right-to-left: status, /rtl install' })
    if (!(await status($)).patched) {
      $.ui.toast('Hebrew right-to-left is off, maybe after a Claude update. Type /rtl to fix it.')
    }
    return next(e)
  })

  on('command.run', { command: 'rtl' }, async ($, e) => {
    const s = await status($)
    const p = plan(e.args, s.patched, s.line)
    if (p.run) {
      const args = p.run === 'install' ? ['install', '--in-place', '--relaunch'] : ['uninstall', '--relaunch']
      await $.process.run([PYTHON, `${$.plugin.root}/rtl.py`, ...args], { timeoutMs: 60000 })
    }
    return { text: p.text }
  })
}
