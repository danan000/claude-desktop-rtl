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
      $.ui.toast('Hebrew right-to-left is not active in this Claude. Type /rtl to set it up.')
    }
    return next(e)
  })

  on('command.run', { command: 'rtl' }, async ($, e) => {
    const s = await status($)
    const p = plan(e.args, s.patched, s.line)
    if (p.run) {
      await $.process.run([PYTHON, `${$.plugin.root}/rtl.py`, 'install', '--in-place', '--relaunch'], { timeoutMs: 60000 })
    }
    return { text: p.text }
  })
}
