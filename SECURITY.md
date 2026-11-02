# Security

This tool patches the Claude desktop app on your Mac, so a flaw in it matters. Please report one privately.

## How to report

Open the **Security** tab of this repository and click **Report a vulnerability**. GitHub keeps the report private between you and the maintainer. Please do not open a public issue for a security problem.

Useful to include: what you ran, your Claude version, your macOS version, and what happened.

## In scope

- `rtl.py`: the build, the swap into `/Applications/Claude.app`, the repair agent and the relaunch job.
- `payload.js` and `main-snippet.js`: the code the patch adds to the app.
- `hooks/`: the Claude Code plugin.
- `probe_windows.py`: the read-only Windows probe.

## What the tool does to your system

See [Security and trust](README.md#security-and-trust) in the README: what the patch changes, what it never touches, and what else it puts on your Mac.
