// Runs inside the claude.ai page of the desktop app. The app's chat text has no
// bidi rule: its paragraphs are direction ltr, so a Hebrew line with English in
// it scrambles. This sets dir="rtl" on a text block when most of its letters
// are right-to-left, and takes it off when they are not. It reads the page text
// in place, makes no network call and keeps nothing.
;(function () {
  const RTL = /[֐-ࣿיִ-﷿ﹰ-﻿]/
  const LETTER = /[A-Za-zÀ-ɏЀ-ӿ֐-ࣿיִ-﷿ﹰ-﻿]/
  // Words, not letters: long English names must not outweigh the Hebrew around
  // them. Half the words RTL is enough, and a line that opens in Hebrew needs a third.
  const isRtl = s => {
    const words = s.split(/\s+/).filter(w => LETTER.test(w))
    const rtl = words.filter(w => RTL.test(w)).length
    const first = RTL.test(s.match(LETTER)?.[0] ?? '')
    return rtl > 0 && (rtl * 2 >= words.length || (first && rtl * 3 >= words.length))
  }

  if (typeof document === 'undefined') {
    module.exports = { isRtl }
    return
  }
  if (window.__claudeRtl) return

  const BLOCKS = ['p', 'li', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'td', 'th']
  const SEL = BLOCKS.map(b => `[class*="epitaxy"] ${b}`).join(',')
  const SKIP = 'pre,code,kbd,textarea,[contenteditable]'
  const NESTED = `${SKIP},${BLOCKS.join(',')},ul,ol,blockquote,table`

  // The block's own text: its nested blocks and its code are left out.
  const ownText = el => {
    let t = ''
    for (const c of el.childNodes) {
      if (c.nodeType === 3) t += c.data
      else if (c.nodeType === 1 && !c.matches(NESTED)) t += ownText(c)
    }
    return t
  }

  const mark = (el, rtl) => {
    if (rtl) {
      el.setAttribute('dir', 'rtl')
      el.setAttribute('data-claude-rtl', '')
    } else if (el.hasAttribute('data-claude-rtl')) {
      el.removeAttribute('dir')
      el.removeAttribute('data-claude-rtl')
    }
  }

  const fix = el => {
    if (el.closest(SKIP)) return
    mark(el, isRtl(ownText(el)))
    const list = el.tagName === 'LI' ? el.parentElement : null
    if (list && (list.tagName === 'UL' || list.tagName === 'OL')) {
      const items = [...list.children].filter(k => k.tagName === 'LI')
      const rtl = items.filter(k => k.hasAttribute('data-claude-rtl')).length
      mark(list, rtl * 2 > items.length)
    }
  }

  const run = node => {
    const el = node.nodeType === 1 ? node : node.parentElement
    if (!el || !document.contains(el)) return
    const own = el.closest(SEL)
    if (own) fix(own)
    for (const b of el.querySelectorAll(SEL)) fix(b)
  }

  // The button joins the title bar's button row. It is a copy of a neighbour, so it
  // takes the site's own look: size, hover and the pressed state (aria-pressed).
  // The page has no way into the app except the console, so a click logs one coded
  // line that the app reads. Styles go through the element, because the page's CSP
  // blocks style tags, and the icon is built with DOM calls, not innerHTML.
  const BAR = '.epitaxy-titlebar-end'
  const BUTTON = 'claude-rtl-button'
  const LABEL = 'Right-to-left Hebrew'
  const SVG = 'http://www.w3.org/2000/svg'
  // A pilcrow with a left arrow under it: the usual right-to-left text icon.
  const ICON = 'M10.5 3.5V11M13.5 3.5V11M13.5 3.5H8.25a3.25 3.25 0 0 0 0 6.5H10.5M16.5 15.5H3.5M7 12.5l-3.5 3 3.5 3'
  let enabled = true

  const icon = () => {
    const svg = document.createElementNS(SVG, 'svg')
    const path = document.createElementNS(SVG, 'path')
    for (const [k, v] of Object.entries({ viewBox: '0 0 20 20', width: '1em', height: '1em', fill: 'none', stroke: 'currentColor', 'stroke-width': '1.4', 'stroke-linecap': 'round', 'stroke-linejoin': 'round', 'aria-hidden': 'true' })) svg.setAttribute(k, v)
    path.setAttribute('d', ICON)
    svg.appendChild(path)
    return svg
  }

  // The first solid background above the element, for the tooltip.
  const surface = el => {
    for (let e = el; e; e = e.parentElement) {
      const c = getComputedStyle(e).backgroundColor
      if (c !== 'rgba(0, 0, 0, 0)' && c !== 'transparent') return c
    }
    return 'Canvas'
  }

  let tip = null
  let tipTimer = 0
  const hideTip = () => {
    clearTimeout(tipTimer)
    if (tip) tip.remove()
    tip = null
  }
  const showTip = btn => {
    hideTip()
    tipTimer = setTimeout(() => {
      const r = btn.getBoundingClientRect()
      const color = getComputedStyle(btn).color
      tip = document.createElement('div')
      tip.textContent = LABEL + (enabled ? ': on' : ': off')
      tip.style.cssText = 'position:fixed;z-index:2147483647;pointer-events:none;white-space:nowrap;padding:4px 8px;border-radius:6px;font:12px/16px system-ui,sans-serif;box-shadow:0 2px 8px rgba(0,0,0,.35)'
      tip.style.color = color
      tip.style.background = `color-mix(in srgb, ${color} 14%, ${surface(btn)})`
      document.body.appendChild(tip)
      const w = tip.getBoundingClientRect().width
      tip.style.top = r.bottom + 6 + 'px'
      tip.style.left = Math.max(4, Math.min(innerWidth - w - 4, r.left + r.width / 2 - w / 2)) + 'px'
    }, 350)
  }

  const paint = btn => {
    btn.setAttribute('aria-pressed', String(enabled))
    // The site paints the pressed state itself on a copied button. A plain one needs it by hand.
    if (!btn.hasAttribute('data-cds')) btn.style.background = enabled ? 'rgba(128,128,128,.25)' : 'transparent'
  }

  const make = bar => {
    const src = bar.querySelector('button[data-cds="Button"]')
    let btn = src && src.cloneNode(true)
    let slot = btn && btn.querySelector('[data-cds="Icon"]')
    if (slot) {
      for (const a of ['id', 'aria-keyshortcuts', 'data-base-ui-tooltip-trigger']) btn.removeAttribute(a)
      btn.tabIndex = 0
      slot.replaceChildren()
    } else {
      btn = document.createElement('button')
      btn.type = 'button'
      btn.style.cssText = 'flex:none;width:28px;height:28px;padding:0;border:0;border-radius:8px;color:inherit;display:inline-flex;align-items:center;justify-content:center;cursor:pointer'
      slot = btn
    }
    btn.id = BUTTON
    btn.setAttribute('aria-label', LABEL)
    slot.appendChild(icon())
    slot.style.display = 'inline-flex'
    btn.addEventListener('mouseenter', () => showTip(btn))
    btn.addEventListener('mouseleave', hideTip)
    btn.addEventListener('click', () => {
      hideTip()
      set(!enabled)
      console.info('claude-rtl:' + enabled)
    })
    return btn
  }

  const ensureButton = () => {
    const bar = document.querySelector(BAR)
    if (!bar) return
    let btn = bar.querySelector('#' + BUTTON)
    if (!btn) {
      btn = make(bar)
      bar.prepend(btn)
    }
    paint(btn)
  }

  // A timer, not requestAnimationFrame: a hidden window never fires a frame.
  let obs = null
  let timer = 0
  const queued = new Set()
  const flush = () => {
    timer = 0
    ensureButton()
    for (const n of queued) {
      try {
        if (enabled) run(n)
      } catch {}
    }
    queued.clear()
  }

  // The observer stays on in both states, so the button survives a redraw of the bar.
  const set = on => {
    enabled = on
    if (!obs) {
      obs = new MutationObserver(ms => {
        for (const m of ms) {
          queued.add(m.target)
          for (const a of m.addedNodes) queued.add(a)
        }
        if (!timer) timer = setTimeout(flush, 30)
      })
      obs.observe(document.body, { childList: true, subtree: true, characterData: true })
    }
    ensureButton()
    if (enabled) {
      run(document.body)
    } else {
      queued.clear()
      for (const el of document.querySelectorAll('[data-claude-rtl]')) {
        el.removeAttribute('dir')
        el.removeAttribute('data-claude-rtl')
      }
    }
  }

  window.__claudeRtl = { set }
})()
