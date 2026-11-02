// Pure: what /rtl answers, and which job it starts, if any. No engine calls.

export type Plan = { text: string; run: 'install' | 'uninstall' | null }

export function plan(args: string, patched: boolean, line: string): Plan {
  const a = args.trim()
  if (a === 'install' || a === 'install yes') {
    if (patched) return { text: `Already active. ${line}`, run: null }
    if (a === 'install yes') {
      return {
        text:
          'Claude closes in about 25 seconds, then opens again with the patch (about 2 minutes). macOS then asks about "Claude Safe Storage": click Always Allow. Never click Deny.',
        run: 'install',
      }
    }
    return {
      text:
        'This closes Claude, patches the app and opens it again, about 2 minutes. Unsent drafts may be lost. Your sessions stay. Type /rtl install yes to go on.',
      run: null,
    }
  }
  if (a === 'uninstall' || a === 'uninstall yes') {
    if (!patched) return { text: `Not patched in this app. Nothing to undo. ${line}`, run: null }
    if (a === 'uninstall yes') {
      return {
        text:
          'Claude closes in about 25 seconds, then opens again as the original app. To stop the reminder at each session, also run /plugin uninstall rtl-hebrew.',
        run: 'uninstall',
      }
    }
    return {
      text: 'This closes Claude, puts your original app back and opens it again. Type /rtl uninstall yes to go on.',
      run: null,
    }
  }
  return { text: `${line}\nTo set up or repair: /rtl install. To undo: /rtl uninstall`, run: null }
}
