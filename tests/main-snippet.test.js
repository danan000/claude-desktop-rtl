const test = require('node:test')
const assert = require('node:assert')
const fs = require('fs')
const os = require('os')
const path = require('path')
const vm = require('vm')

const SRC = fs
  .readFileSync(path.join(__dirname, '..', 'main-snippet.js'), 'utf8')
  .replace('__RTL_PAYLOAD__', JSON.stringify('/*PAYLOAD*/'))

// Runs the snippet against a mocked electron. The state file sits in a throwaway
// folder that does not exist yet, as on a first run, unless a state is given.
const rig = state => {
  const home = fs.mkdtempSync(path.join(os.tmpdir(), 'rtl-test-'))
  const stateFile = path.join(home, 'Claude-RTL', 'state.json')
  if (state !== undefined) {
    fs.mkdirSync(path.dirname(stateFile))
    fs.writeFileSync(stateFile, typeof state === 'string' ? state : JSON.stringify(state))
  }

  const handlers = {}
  const shown = []
  const wcs = []
  const wc = url => {
    const ev = {}
    const w = {
      calls: [],
      on: (n, f) => (ev[n] = f),
      emit: (n, ...a) => ev[n] && ev[n](...a),
      getURL: () => url,
      executeJavaScript: code => (w.calls.push(code), Promise.resolve()),
    }
    wcs.push(w)
    handlers['web-contents-created'](null, w)
    return w
  }
  class Menu {
    static setApplicationMenu(m) {
      shown.push(m)
    }
    static getApplicationMenu() {
      return shown.at(-1) || null
    }
  }
  const menu = () => ({
    items: [],
    append(i) {
      this.items.push(i)
    },
    getMenuItemById(id) {
      return this.items.find(i => i.id === id)
    },
  })
  const electron = {
    app: { on: (n, f) => (handlers[n] = f) },
    Menu,
    MenuItem: class {
      constructor(o) {
        Object.assign(this, o)
      }
    },
    webContents: { getAllWebContents: () => wcs },
  }
  vm.runInNewContext(SRC.replace('__RTL_STATE__', JSON.stringify(stateFile)), {
    require: m => (m === 'electron' ? electron : require(m)),
  })
  return { wc, Menu, menu, shown, stateFile, wcs }
}

test('the first save creates the state folder', () => {
  const r = rig()
  assert.equal(fs.existsSync(path.dirname(r.stateFile)), false)
  const page = r.wc('https://claude.ai/code')
  page.emit('console-message', { message: 'claude-rtl:false' })
  assert.deepEqual(JSON.parse(fs.readFileSync(r.stateFile, 'utf8')), { enabled: false })
})

test('injects the payload with the saved state into a claude.ai page', () => {
  const r = rig()
  const w = r.wc('https://claude.ai/code')
  w.emit('dom-ready')
  assert.equal(w.calls.length, 1)
  assert.match(w.calls[0], /\/\*PAYLOAD\*\/.*__claudeRtl\.set\(true\)/s)
})

test('leaves every other host alone, look-alikes included', () => {
  const r = rig()
  for (const url of ['https://example.com/', 'https://claude.ai.evil.com/', 'https://evilclaude.ai/', 'http://claude.ai/']) {
    const w = r.wc(url)
    w.emit('dom-ready')
    assert.equal(w.calls.length, 0, url)
  }
})

test('the saved state off reaches the page', () => {
  const r = rig({ enabled: false })
  const w = r.wc('https://claude.ai/code')
  w.emit('dom-ready')
  assert.match(w.calls[0], /__claudeRtl\.set\(false\)/)
})

test('an unreadable state file means on', () => {
  const r = rig('{not json')
  const w = r.wc('https://claude.ai/code')
  w.emit('dom-ready')
  assert.match(w.calls[0], /set\(true\)/)
})

test('adds one Hebrew menu with a checkbox, once per menu', () => {
  const r = rig({ enabled: false })
  const m = r.menu()
  r.Menu.setApplicationMenu(m)
  r.Menu.setApplicationMenu(m)
  assert.equal(m.items.length, 1)
  assert.equal(m.items[0].label, 'Hebrew')
  assert.equal(m.items[0].submenu[0].type, 'checkbox')
  assert.equal(m.items[0].submenu[0].checked, false)
  assert.equal(r.shown.length, 2)
})

test('the checkbox saves the state and tells every claude.ai page', () => {
  const r = rig({ enabled: true })
  const page = r.wc('https://claude.ai/code')
  const other = r.wc('https://example.com/')
  const m = r.menu()
  r.Menu.setApplicationMenu(m)
  m.items[0].submenu[0].click({ checked: false })
  assert.deepEqual(JSON.parse(fs.readFileSync(r.stateFile, 'utf8')), { enabled: false })
  assert.match(page.calls.at(-1), /__claudeRtl&&window\.__claudeRtl\.set\(false\)/)
  assert.equal(other.calls.length, 0)
})

// The page switch has no way into the app but the console, so it logs a coded line.
const logged = (w, message, style) =>
  style === 'old' ? w.emit('console-message', {}, 1, message, 0, '') : w.emit('console-message', { message })

test('a console line from a claude.ai page sets, saves and reaches every page (both Electron event shapes)', () => {
  for (const style of ['new', 'old']) {
    const r = rig({ enabled: true })
    const page = r.wc('https://claude.ai/code')
    const other = r.wc('https://claude.ai/chat')
    logged(page, 'claude-rtl:false', style)
    assert.deepEqual(JSON.parse(fs.readFileSync(r.stateFile, 'utf8')), { enabled: false }, style)
    assert.match(page.calls.at(-1), /set\(false\)/, style)
    assert.match(other.calls.at(-1), /set\(false\)/, style)
  }
})

test('console lines from other hosts or with other text change nothing', () => {
  const r = rig({ enabled: true })
  const evil = r.wc('https://example.com/')
  const page = r.wc('https://claude.ai/code')
  logged(evil, 'claude-rtl:false')
  logged(page, 'hello')
  logged(page, 'claude-rtl:maybe')
  logged(page, 'xclaude-rtl:false')
  assert.deepEqual(JSON.parse(fs.readFileSync(r.stateFile, 'utf8')), { enabled: true })
  assert.equal(page.calls.length, 0)
})

test('a page switch also moves the menu checkbox', () => {
  const r = rig({ enabled: true })
  const page = r.wc('https://claude.ai/code')
  const m = r.menu()
  r.Menu.setApplicationMenu(m)
  assert.equal(m.items[0].submenu[0].checked, true)
  const item = { id: 'claude-rtl', checked: true }
  m.getMenuItemById = id => (id === 'claude-rtl' ? item : m.items.find(i => i.id === id))
  logged(page, 'claude-rtl:false')
  assert.equal(item.checked, false)
})

test('a console line with no menu built yet does not throw', () => {
  const r = rig({ enabled: true })
  const page = r.wc('https://claude.ai/code')
  assert.doesNotThrow(() => logged(page, 'claude-rtl:false'))
})

test('the saved state is written through a symlink, so a dotfiles repo copy changes', () => {
  const r = rig('{"enabled":true}')
  const target = path.join(path.dirname(r.stateFile), 'repo-state.json')
  fs.writeFileSync(target, '{"enabled":true}\n')
  fs.rmSync(r.stateFile)
  fs.symlinkSync(target, r.stateFile)
  const m = r.menu()
  r.Menu.setApplicationMenu(m)
  m.items[0].submenu[0].click({ checked: false })
  assert.equal(fs.lstatSync(r.stateFile).isSymbolicLink(), true)
  assert.deepEqual(JSON.parse(fs.readFileSync(target, 'utf8')), { enabled: false })
})

test('a failing electron does not throw out of the snippet', () => {
  assert.doesNotThrow(() =>
    vm.runInNewContext(SRC, {
      require: () => {
        throw new Error('no electron')
      },
    }),
  )
})
