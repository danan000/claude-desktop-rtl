# How it works

This page explains the design for people who want to check it, fix it, or port it. Numbers come from Claude 4.4212.0 (Electron 44.9.3) on 2026-11-01.

## The problem

The Code tab draws chat text inside the page class `epitaxy-markdown`. Its paragraphs have `direction: ltr` and `unicode-bidi: isolate`. A line with Hebrew and English in it is laid out by an LTR paragraph, so the word order scrambles and the line sits on the left. Only `epitaxy-document-prose` (used for documents) has `unicode-bidi: plaintext`.

I measured 15 variants of one mixed line against the real page CSS in Chrome, by taking the position of each word:

| Fix | Word order | Alignment |
|---|---|---|
| Invisible RLM mark in the text | wrong | left |
| RLI or RLE wrap in the text | right | left |
| `dir` tag written in the markdown | not applied | not applied |
| CSS `unicode-bidi: plaintext` alone | wrong when the line opens in English | left |
| **`dir="rtl"` on the paragraph element** | right | right |

Only the `dir` attribute on the element fixes both. Nothing in the text can set it.

## Why not a Claude Code plugin

A render hook changes what the app draws once, and the page redraws from the stored message a second later. A stream hook can store marks in the message, and I tried that. The marks are stored and the page still ignores them, for the reason in the table above. A plugin has no way to set an attribute on the page.

## The three parts

| File | Runs in | Job |
|---|---|---|
| `payload.js` | The claude.ai page | Sets `dir="rtl"` on text blocks, and adds the title bar button. |
| `main-snippet.js` | The app's main process | Runs the payload on each claude.ai page, adds the Hebrew menu, keeps the setting. |
| `rtl.py` | Your terminal | Builds the copy and checks it. |

### The text rule

A block is right-to-left when at least half of its words contain Hebrew or Arabic letters. A block that opens with such a word needs only a third. Words count, not letters, because long English names such as `production` would otherwise outweigh the Hebrew around them. Code, the composer and nested blocks are skipped. A list is right-to-left when more than half of its items are. A `MutationObserver` re-checks changed nodes, so streaming text and later messages are handled.

### The button

The button is a copy of the button next to it. The site's design system styles a button from its attributes: `data-cds="Button"`, `data-cds-ghost`, and `aria-pressed` with `data-cds-pressed-variant="selected"` for the highlighted state. A copy gets the size, the hover and the pressed look for free. If no such button is found, the code builds a plain one with inline styles.

The icon is an inline SVG built with DOM calls. The site's own icons are glyphs from an icon font with private codepoints, and those can move between versions. The page's CSP blocks style tags and `eval`, so styles go through the element and nothing is evaluated. The tooltip is a small div, because the site's tooltips are managed by its own framework.

### How the page tells the app

The page has no preload script and cannot call the app. A click logs one console line, `claude-rtl:true` or `claude-rtl:false`. The main process listens to console messages from claude.ai pages, accepts only that exact text, saves the setting, ticks the menu item, and tells every page. A line from any other host is ignored. Electron passes the message to the event handler in two shapes, as a details object in new versions and as separate arguments in old ones, and the code accepts both.

## The integrity check

Electron checks `app.asar` at every start. The app turns this check on, so editing the file is not enough. There are two layers:

1. `Info.plist` holds a SHA-256 hash of the asar header (`ElectronAsarIntegrity`).
2. The Electron Framework binary holds a SHA-256 digest of that whole dictionary. The digest sits in a slot that starts with the 32-byte sentinel `AGbevlPCksUGKNL8TSn7wGmJEuJsXb2A`, followed by a used byte, a version byte and 32 digest bytes. The binary is universal, so there is one slot per CPU type. The digest is computed over the keys in sorted order, and for each key its name, its algorithm and its hash, with no separators.

`rtl.py` rewrites the file hash inside the asar header, then the header hash in `Info.plist`, then every digest slot that held the old digest. Its tests check that the digest code reproduces the value stored in your installed Claude.

If a layer is wrong, the app stops at start with `Failed to get integrity for validatable asar archive`. The text is the same for every mismatch, so it does not say which layer. I found the second layer by testing an unpatched copy, a copy with a wrong plist hash, and a copy with a correct plist hash and an unchanged file. Only the first one started.

### The asar rewrite

`rtl.py` does not repack the asar. Every file stays where it was. The changed main file is added at the end, and only its header node points to the new place. The header differs in one node, and a test checks that.

## Signing

The copy is signed ad hoc with `codesign --force --deep --sign -`. This drops Anthropic's signature, the hardened runtime and the keychain access group. macOS then asks once for access to the "Claude Safe Storage" item, which holds the key to your session data.

## The smoke test

`rtl.py install` ends by running the copy for 10 seconds with an empty profile and `--use-mock-keychain`. A mock keychain means the test cannot touch your real login. A run that the timer ends counts as a pass. A run that prints a `FATAL` line, or exits early, fails the install.

## What breaks on an update

| Part | Breaks when |
|---|---|
| `.epitaxy-titlebar-end`, `epitaxy-*` classes | The page renames them. The button or the paragraph rule stops working. |
| `"use strict";` at the top of `.vite/build/index.pre.js` | The main file starts differently. The build refuses to patch. |
| The digest slot format, the sentinel | Electron changes the integrity scheme. The build refuses, or the smoke test fails. |
| `data-cds` button attributes | The design system changes. The plain button is used instead. |

In every case the original app keeps working, because it was never changed.

## In place, repair and the plugin

`install --in-place` builds the patched copy in `~/Applications/Claude-RTL.app`, runs it for 10 seconds on an empty profile, then swaps it into `/Applications/Claude.app`. The original goes to `~/Library/Application Support/Claude-RTL/Claude.original.app`. If the move fails half way, the original goes back.

A launch agent, `com.danan000.claude-rtl`, runs `rtl.py repair` at login and every 10 minutes. It does nothing while the app is patched, or while Claude runs. After an update it rebuilds the patch from the new app. A version that fails the 10 second test is skipped until the next update. The agent runs a copy of the tool kept in `~/Library/Application Support/Claude-RTL/tool`, so a moved clone does not break it.

`install --in-place --relaunch` starts a one-shot launchd job that closes Claude, installs and opens Claude again. The job lives outside Claude, so it survives the quit. The plugin's `/rtl install yes` runs this command.

The plugin (`hooks/`) is a Claude Code mod. It calls `rtl.py` and nothing else. The mod API cannot draw right-to-left text or add a title-bar button on the desktop, so the patch stays the part that does the work.

## Why the Keychain asks again after each update

Claude keeps the key to its login data in a Keychain item, "Claude Safe Storage". macOS lets an app read that item only when the app's "partition" is on the item's list. For an app signed by Anthropic the partition is `teamid:Q6L2SF6YDW`. For an app signed ad hoc, or with a self-signed certificate, the partition is `cdhash:<hash of the binary>` (Apple's `securityd`, `clientid.cpp`, `partitionIdForProcess`). The check is a plain string match (`acls.cpp`, `validatePartition`).

Each repair builds a new binary with a new hash, so macOS asks once. "Always Allow" adds the new hash to the list and keeps the key. A stable self-signed certificate would not help: its partition is still the binary hash. Only an Apple-issued certificate gives a stable `teamid:` partition. An independent report found the same on four machines: [hermes-agent issue 91115](https://github.com/NousResearch/hermes-agent/issues/91115).
