// Pure: what /rtl answers, and whether it starts the install job. No engine calls.

export type Plan = { text: string; run: boolean }

export function plan(args: string, patched: boolean, line: string): Plan {
  const a = args.trim()
  if (a === 'install' || a === 'install yes') {
    if (patched) return { text: `Already active. ${line}`, run: false }
    if (a === 'install yes') {
      return { text: 'Claude closes in about 25 seconds, then opens again with the patch (about 2 minutes).', run: true }
    }
    return {
      text:
        'This closes Claude, patches the app and opens it again, about 2 minutes. Unsent drafts may be lost. Your sessions stay. Type /rtl install yes to go on.',
      run: false,
    }
  }
  return { text: `${line}\nTo set up or repair: /rtl install`, run: false }
}
