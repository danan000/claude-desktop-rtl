#!/usr/bin/env python3
"""Read-only probe of the Claude desktop app on Windows.

It finds the app, reads a few files and runs read-only Windows commands. It changes
nothing, sends nothing over the network, and reads no chat data, cookies or keys.
It writes one report file, claude-rtl-probe.txt, in the folder you run it from.
Your Windows user name is replaced with <user> in the report.

  py -3 probe_windows.py              find the app and probe it
  py -3 probe_windows.py --app DIR    probe one folder (the one with Claude.exe and resources)
"""
import argparse
import getpass
import json
import os
import platform
import re
import subprocess
import sys
from pathlib import Path

import rtl

SENTINEL = b'dL7pKGdnNz796PbbjQWNKmHXBZaB9tsX'
FUSES = ['RunAsNode', 'EnableCookieEncryption', 'EnableNodeOptionsEnvironmentVariable',
         'EnableNodeCliInspectArguments', 'EnableEmbeddedAsarIntegrityValidation', 'OnlyLoadAppFromAsar',
         'LoadBrowserProcessSpecificV8Snapshot', 'GrantFileProtocolExtraPrivileges']
STATE = {ord('0'): 'disabled', ord('1'): 'enabled', ord('r'): 'removed'}


def redact(text, user):
    """Replace the user name where it is a whole path part, so a short name cannot garble words."""
    return re.sub(rf'(?<=[\\/]){re.escape(user)}(?=[\\/])', '<user>', text, flags=re.I) if user else text


def find_hash(data, hexhash):
    """How often the hash appears in the binary, as text and as UTF-16 text."""
    h = hexhash.lower()
    return {'ascii': data.count(h.encode()) + data.count(h.upper().encode()),
            'utf16': data.count(h.encode('utf-16-le')) + data.count(h.upper().encode('utf-16-le'))}


def read_fuses(data):
    """The Electron fuse wire: which switches the app was built with. None when there is none."""
    i = data.find(SENTINEL)
    if i < 0:
        return None
    at = i + len(SENTINEL)
    version, size = data[at], data[at + 1]
    wire = data[at + 2:at + 2 + size]
    names = FUSES + [f'fuse #{n}' for n in range(len(FUSES), size)]
    return {'version': version, 'raw': wire.decode('latin-1'),
            'states': {name: STATE.get(b, '?') for name, b in zip(names, wire)}}


def ps(command):
    """One read-only PowerShell command. The output, or the error as text."""
    try:
        r = subprocess.run(['powershell', '-NoProfile', '-NonInteractive', '-Command', command],
                           capture_output=True, text=True, timeout=60)
        return (r.stdout or r.stderr).strip()
    except Exception as e:  # a probe reports a failure, it never stops on one
        return f'could not run: {e}'


def find_asars(root, depth=5):
    root = Path(root)
    found = []
    if not root.is_dir():
        return found
    base = len(root.parts)
    for folder, dirs, files in os.walk(root):
        if len(Path(folder).parts) - base >= depth:
            dirs[:] = []
        if 'app.asar' in files and Path(folder).name == 'resources':
            found.append(Path(folder) / 'app.asar')
    return found


def candidate_apps():
    """App folders (the one that holds resources/app.asar's parent) on this Windows machine."""
    roots, notes = [], []
    local, programs = os.environ.get('LOCALAPPDATA', ''), os.environ.get('ProgramFiles', '')
    for base, name in ((local, 'AnthropicClaude'), (local, r'Programs\Claude'), (programs, 'Claude'), (programs, 'Anthropic')):
        if base:
            roots.append(Path(base) / name)
    out = ps('Get-AppxPackage -Name *Claude* | Select-Object Name,Version,InstallLocation,SignatureKind | ConvertTo-Json -Compress')
    notes.append(f'Get-AppxPackage: {out or "no package named Claude"}')
    try:
        data = json.loads(out)
        for p in (data if isinstance(data, list) else [data]):
            if p.get('InstallLocation'):
                roots.append(Path(p['InstallLocation']))
    except (ValueError, AttributeError):
        pass
    apps = []
    for root in roots:
        for asar in find_asars(root):
            if asar.parent.parent not in apps:
                apps.append(asar.parent.parent)
    return apps, notes


def report_for_app(app):
    app = Path(app)
    if not app.is_dir():
        return f'{app}: not found'
    lines = [f'== {app}']
    exes = sorted(app.glob('*.exe'))
    exe = next((e for e in exes if e.name.lower() == 'claude.exe'), exes[0] if exes else None)
    asar = app / 'resources' / 'app.asar'
    lines.append(f'exe: {exe.name if exe else "none found"}' + (f', {exe.stat().st_size} bytes' if exe else ''))
    lines.append(f'app.asar: {asar.stat().st_size} bytes' if asar.exists() else 'app.asar: not found')
    version = app / 'version'
    if version.exists():
        lines.append(f'electron version file: {version.read_text(errors="replace").strip()}')
    lines.append(f'folder writable by this user: {os.access(app, os.W_OK)}; app.asar writable: {os.access(asar, os.W_OK) if asar.exists() else "n/a"}')
    if exe:
        try:
            data = exe.read_bytes()
        except OSError as e:
            data = None
            lines.append(f'could not read the exe: {e}')
        if data is not None:
            fuses = read_fuses(data)
            lines.append('fuses: ' + (json.dumps(fuses) if fuses else 'none found'))
            if asar.exists():
                try:
                    h = rtl.header_hash(asar)
                    lines.append(f'asar header hash: {h}')
                    lines.append(f'that hash inside the exe: {find_hash(data, h)}')
                except Exception as e:
                    lines.append(f'could not hash the asar header: {e}')
            lines.append('marker "ElectronAsar" in the exe: ' + str({'ascii': data.count(b'ElectronAsar'),
                                                                       'utf16': data.count('ElectronAsar'.encode('utf-16-le'))}))
            lines.append(f'digest sentinel (second integrity layer) in the exe: {data.count(b"AGbevlPCksUGKNL8TSn7wGmJEuJsXb2A")}')
        if sys.platform == 'win32':
            sig = ps(f"(Get-AuthenticodeSignature -LiteralPath '{exe}') | Select-Object Status,@{{n='Signer';e={{$_.SignerCertificate.Subject}}}} | ConvertTo-Json -Compress")
            lines.append(f'authenticode: {sig}')
            lines.append('product version: ' + ps(f"(Get-Item -LiteralPath '{exe}').VersionInfo.ProductVersion"))
    return '\n'.join(lines)


def running():
    try:
        r = subprocess.run(['tasklist', '/FI', 'IMAGENAME eq Claude.exe'], capture_output=True, text=True, timeout=30)
        return 'Claude.exe is running' if 'Claude.exe' in r.stdout else 'Claude.exe is not running'
    except Exception as e:
        return f'could not run tasklist: {e}'


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--app', type=Path, help='probe this app folder only')
    a = p.parse_args()
    head = [f'claude-rtl windows probe', f'os: {platform.platform()}', f'machine: {platform.machine()}',
            f'python: {sys.version.split()[0]}']
    body = []
    if a.app:
        body.append(report_for_app(a.app))
    elif sys.platform == 'win32':
        apps, notes = candidate_apps()
        body += notes + [running()]
        body += [report_for_app(x) for x in apps] or ['no Claude app folder found in the usual places']
    else:
        body.append('This probe is for Windows. Use --app DIR to probe one folder.')
    text = redact('\n'.join(head + [''] + body) + '\n', getpass.getuser())
    Path('claude-rtl-probe.txt').write_text(text, encoding='utf-8')
    print(text)
    print('Report saved to claude-rtl-probe.txt. Read it, then send it to the project owner.')


if __name__ == '__main__':
    main()
