;(() => {
  // rtl.py puts this at the top of the app's main process file and fills in the
  // PAYLOAD and STATE constants below: the text of payload.js, and the path of the
  // state file. It adds one menu, "Hebrew", with one checkbox, and runs the payload
  // in every claude.ai page. It reads and writes the state file only, and makes no
  // network call.
  try {
    const { app, Menu, MenuItem, webContents } = require('electron')
    const fs = require('fs')
    const path = require('path')
    const STATE = __RTL_STATE__
    const PAYLOAD = __RTL_PAYLOAD__

    const read = () => {
      try {
        return JSON.parse(fs.readFileSync(STATE, 'utf8')).enabled !== false
      } catch {
        return true
      }
    }
    let on = read()

    const isClaude = wc => {
      try {
        return /^https:\/\/([a-z0-9-]+\.)*claude\.ai\//.test(wc.getURL())
      } catch {
        return false
      }
    }
    const run = (wc, code) => wc.executeJavaScript(code).catch(() => {})

    const toggle = next => {
      on = next
      try {
        fs.mkdirSync(path.dirname(STATE), { recursive: true })
        fs.writeFileSync(STATE, JSON.stringify({ enabled: on }) + '\n')
      } catch {}
      try {
        const item = Menu.getApplicationMenu()?.getMenuItemById('claude-rtl')
        if (item) item.checked = on
      } catch {}
      for (const wc of webContents.getAllWebContents()) {
        if (isClaude(wc)) run(wc, `window.__claudeRtl&&window.__claudeRtl.set(${on})`)
      }
    }

    app.on('web-contents-created', (_e, wc) => {
      wc.on('dom-ready', () => {
        if (isClaude(wc)) run(wc, `${PAYLOAD};window.__claudeRtl.set(${on})`)
      })
      // The page switch cannot call the app, so it logs a coded line. Electron
      // passes (details) in new versions and (event, level, message) in old ones.
      wc.on('console-message', (a, _level, text) => {
        const line = typeof text === 'string' ? text : a && a.message
        const m = /^claude-rtl:(true|false)$/.exec(line || '')
        if (m && isClaude(wc)) toggle(m[1] === 'true')
      })
    })

    const setMenu = Menu.setApplicationMenu.bind(Menu)
    Menu.setApplicationMenu = menu => {
      try {
        if (menu && !menu.getMenuItemById('claude-rtl-menu')) {
          menu.append(
            new MenuItem({
              id: 'claude-rtl-menu',
              label: 'Hebrew',
              submenu: [
                {
                  id: 'claude-rtl',
                  label: 'Right-to-left Hebrew',
                  type: 'checkbox',
                  checked: on,
                  click: item => toggle(item.checked),
                },
              ],
            }),
          )
        }
      } catch {}
      return setMenu(menu)
    }
  } catch {}
})();
