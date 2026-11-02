#!/usr/bin/env python3
"""Right-to-left Hebrew for the Claude desktop app (macOS). Unofficial.

Makes a patched copy of the app, ~/Applications/Claude-RTL.app, that shows Hebrew
and Arabic the right way round, with an icon button in the title bar and a
"Hebrew" menu to turn it on and off. The original app is never touched.

  python3 rtl.py install      make the copy from /Applications/Claude.app
  python3 rtl.py update       make it again, after Claude updates
  python3 rtl.py status       say if the copy is current
  python3 rtl.py smoke        run the copy for 10 s with an empty profile; exit 0 if it starts
  python3 rtl.py uninstall    delete the copy

  --state-file PATH   where the on/off setting is kept
                      (default ~/Library/Application Support/Claude-RTL/state.json)

Python standard library only. Electron checks app.asar twice at every start: a hash
in Info.plist, and a digest of that list inside the Electron Framework binary. This
keeps both checks ON: it rewrites the hash and the digest, then signs the copy ad hoc.
How and why: docs/how-it-works.md.
"""
import argparse
import hashlib
import json
import os
import plistlib
import shlex
import shutil
import signal
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = Path('/Applications/Claude.app')
DEST = Path.home() / 'Applications' / 'Claude-RTL.app'
DEFAULT_STATE = Path.home() / 'Library' / 'Application Support' / 'Claude-RTL' / 'state.json'
KEEP = Path.home() / 'Library' / 'Application Support' / 'Claude-RTL'
BACKUP = KEEP / 'Claude.original.app'
FAILED = KEEP / 'failed-version'
TOOL = KEEP / 'tool'
LOG = Path.home() / 'Library' / 'Logs' / 'claude-rtl-install.log'
LABEL = 'com.danan000.claude-rtl'
ONCE = 'com.danan000.claude-rtl-once'
AGENT = Path.home() / 'Library' / 'LaunchAgents' / f'{LABEL}.plist'
MAIN = '.vite/build/index.pre.js'
FRAMEWORK = 'Contents/Frameworks/Electron Framework.framework/Versions/A/Electron Framework'
SENTINEL = b'AGbevlPCksUGKNL8TSn7wGmJEuJsXb2A'
BLOCK = 4 * 1024 * 1024
DIRECTIVE = b'"use strict";'


def read_asar(path):
    """(header dict, raw header json, offset where file data starts)."""
    with open(path, 'rb') as f:
        f.read(4)
        hdr_size = struct.unpack('<I', f.read(4))[0]
        f.read(4)
        raw = f.read(struct.unpack('<I', f.read(4))[0])
    return json.loads(raw), raw, 8 + hdr_size


def nodes(header, prefix=''):
    """Every packed file as (path, node). Unpacked files live outside the asar."""
    for name, node in header.get('files', {}).items():
        path = f'{prefix}/{name}' if prefix else name
        if 'files' in node:
            yield from nodes(node, path)
        elif 'offset' in node:
            yield path, node


def header_hash(path):
    return hashlib.sha256(read_asar(path)[1]).hexdigest()


def integrity(data):
    return {
        'algorithm': 'SHA256',
        'hash': hashlib.sha256(data).hexdigest(),
        'blockSize': BLOCK,
        'blocks': [hashlib.sha256(data[i:i + BLOCK]).hexdigest() for i in range(0, len(data), BLOCK)],
    }


def read_file(path, name):
    header, _, base = read_asar(path)
    node = dict(nodes(header))[name]
    with open(path, 'rb') as f:
        f.seek(base + int(node['offset']))
        return f.read(node['size'])


def write_asar(src, dst, replace):
    """Copy an asar, swapping the files in `replace` ({path: bytes}).

    Every other file stays where it is. A swapped file is added at the end and its
    header node points there, so the header differs in those nodes and no others.
    The old bytes stay in the file, unused."""
    header, _, base = read_asar(src)
    table = dict(nodes(header))
    end = max(int(n['offset']) + n['size'] for n in table.values())
    tail = b''
    for name, data in replace.items():
        node = table[name]
        node['offset'] = str(end + len(tail))
        node['size'] = len(data)
        if 'integrity' in node:
            node['integrity'] = integrity(data)
        tail += data
    raw = json.dumps(header, separators=(',', ':'), ensure_ascii=False).encode()
    padded = raw + b'\0' * (-len(raw) % 4)
    with open(src, 'rb') as f, open(dst, 'wb') as out:
        out.write(struct.pack('<IIII', 4, 8 + len(padded), 4 + len(padded), len(raw)) + padded)
        f.seek(base)
        left = end
        while left:
            chunk = f.read(min(left, 1 << 20))
            if not chunk:
                raise ValueError('asar is shorter than its header says')
            out.write(chunk)
            left -= len(chunk)
        out.write(tail)


def verify_asar(path):
    """Problems found, same as the check the app runs: each file against its header hash."""
    header, _, base = read_asar(path)
    problems = []
    with open(path, 'rb') as f:
        for name, node in nodes(header):
            f.seek(base + int(node['offset']))
            data = f.read(node['size'])
            if len(data) != node['size']:
                problems.append(f'{name}: short read')
            elif 'integrity' in node and integrity(data) != node['integrity']:
                problems.append(f'{name}: integrity mismatch')
    return problems


def make_snippet(folder, state):
    snippet = (folder / 'main-snippet.js').read_text()
    for token in ('__RTL_PAYLOAD__', '__RTL_STATE__'):
        if snippet.count(token) != 1:
            raise ValueError(f'main-snippet.js must hold {token} exactly once')
    snippet = snippet.replace('__RTL_PAYLOAD__', json.dumps((folder / 'payload.js').read_text()))
    return snippet.replace('__RTL_STATE__', json.dumps(str(state)))


def patched_main(original, snippet):
    if not original.startswith(DIRECTIVE):
        raise ValueError('the app main file no longer starts with "use strict"; this build needs a new look')
    if b'claude-rtl-menu' in original:
        raise ValueError('the app is already patched; build from the original, not from a patched app')
    return DIRECTIVE + snippet.encode() + original[len(DIRECTIVE):]


def set_asar_hash(plist, value):
    data = plistlib.loads(plist.read_bytes())
    data['ElectronAsarIntegrity']['Resources/app.asar']['hash'] = value
    plist.write_bytes(plistlib.dumps(data))


def integrity_digest(integ):
    """Electron's digest of the ElectronAsarIntegrity dictionary: SHA-256 over each
    key, its algorithm and its hash, keys in sorted order, no separators."""
    h = hashlib.sha256()
    for key in sorted(integ):
        for part in (key, integ[key]['algorithm'], integ[key]['hash']):
            h.update(part.encode())
    return h.digest()


def digest_slots(data):
    """(offset, digest) of every live digest slot: the sentinel, a used byte, a version byte, 32 bytes."""
    out, i = [], data.find(SENTINEL)
    while i >= 0:
        at = i + len(SENTINEL)
        if data[at] == 1:
            if data[at + 1] != 1:
                raise ValueError(f'digest slot version {data[at + 1]} is not 1; this build needs a new look')
            out.append((at + 2, data[at + 2:at + 34]))
        i = data.find(SENTINEL, i + 1)
    return out


def patch_digest(data, old, new):
    """Swap `old` for `new` in every slot that holds it. Other slots stay as they are."""
    hits = [at for at, d in digest_slots(data) if d == old]
    if not hits:
        raise ValueError('no digest slot holds the expected digest; this build needs a new look')
    out = bytearray(data)
    for at in hits:
        out[at:at + 32] = new
    return bytes(out)


def integrity_of(app):
    return plistlib.loads((Path(app) / 'Contents/Info.plist').read_bytes())['ElectronAsarIntegrity']


def remove(dest):
    dest = Path(dest)
    if dest.name != 'Claude-RTL.app' or dest.parent != Path.home() / 'Applications':
        raise ValueError(f'refusing to delete {dest}')
    shutil.rmtree(dest, ignore_errors=True)


def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    print(f'exit {r.returncode}: {" ".join(map(str, cmd))}')
    if r.returncode:
        raise SystemExit(r.stderr.strip() or f'{cmd[0]} failed')


def build(src, dest, state, force=False):
    src, dest = Path(src), Path(dest)
    if dest.resolve() == src.resolve() or dest.name == 'Claude.app':
        raise ValueError('the copy must not replace the original app')
    if dest.exists():
        if not force:
            raise SystemExit(f'{dest} exists; run "python3 rtl.py update" to rebuild it')
        remove(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    run(['ditto', src, dest])
    asar = dest / 'Contents/Resources/app.asar'
    patched = asar.with_suffix('.new')
    write_asar(asar, patched, {MAIN: patched_main(read_file(asar, MAIN), make_snippet(HERE, state))})
    problems = verify_asar(patched)
    if problems:
        raise SystemExit('patched asar failed its own check: ' + '; '.join(problems[:3]))
    patched.replace(asar)
    plist = dest / 'Contents/Info.plist'
    old = integrity_digest(integrity_of(src))
    set_asar_hash(plist, header_hash(asar))
    framework = dest / FRAMEWORK
    framework.write_bytes(patch_digest(framework.read_bytes(), old, integrity_digest(integrity_of(dest))))
    run(['codesign', '--force', '--deep', '--sign', '-', dest])
    run(['codesign', '--verify', '--deep', '--strict', dest])
    ok, detail = smoke(dest)
    print(f'smoke launch: {"ok" if ok else "FAILED"} {detail}')
    if not ok:
        raise SystemExit(1)
    print(f'built {dest}')


def state_path(arg):
    """The state file: the given path, expanded and absolute, else the default.
    A symlink stays a symlink, so a dotfiles repo can move without breaking saves."""
    return Path(os.path.abspath(os.path.expanduser(arg))) if arg else DEFAULT_STATE


def problems(src):
    """What stops an install, one line each. Empty when all is well."""
    found = []
    if sys.platform != 'darwin':
        found.append('This tool works on macOS only.')
    if sys.version_info < (3, 9):
        found.append('Python 3.9 or newer is required.')
    if not (Path(src) / 'Contents/Info.plist').exists():
        found.append(f'{src} not found. Install Claude from claude.ai/download, or pass --src.')
    for tool in ('ditto', 'codesign', 'perl'):
        if not shutil.which(tool):
            found.append(f'The macOS tool "{tool}" is missing.')
    return found


def running(app, ps_text=None):
    """Process ids of everything running from inside `app`."""
    if ps_text is None:
        ps_text = subprocess.run(['ps', '-axo', 'pid=,command='], capture_output=True, text=True).stdout
    prefix = str(app) + '/'
    out = []
    for line in ps_text.splitlines():
        pid, _, command = line.strip().partition(' ')
        if pid.isdigit() and command.lstrip().startswith(prefix):
            out.append(int(pid))
    return out


def install(src, dest, state, force=False, announce=True):
    found = problems(src)
    if found:
        raise SystemExit('\n'.join(found))
    pids = running(dest)
    if pids:
        raise SystemExit(f'{dest.name} is running (process {pids[0]}). Quit it with Cmd+Q, then run this again.')
    build(src, dest, state, force)
    if announce:
        print(f'''
Done. The setting is kept in {state}.

Next:
  1. Quit Claude with Cmd+Q. The copy and the original share one data folder.
  2. Run:  open -n {dest}
  3. macOS asks for access to "Claude Safe Storage". Read the prompt, then click Allow.
  4. Look for the RTL icon at the left end of the top-right button row.''')


def smoke(app, seconds=10):
    """Run the app for a few seconds with an empty profile and a mock keychain, so it
    cannot touch the real login. (True, note) if the timer ended it, else (False, why)."""
    profile = tempfile.mkdtemp(prefix='rtl-profile.')
    try:
        p = subprocess.run(
            ['perl', '-e', f'alarm {seconds}; exec @ARGV', str(Path(app) / 'Contents/MacOS/Claude'),
             f'--user-data-dir={profile}', '--use-mock-keychain'],
            capture_output=True, text=True)
        subprocess.run(['pkill', '-f', f'user-data-dir={profile}'], capture_output=True)
    finally:
        shutil.rmtree(profile, ignore_errors=True)
    fatal = [l.strip() for l in (p.stdout + p.stderr).splitlines() if 'FATAL' in l]
    if p.returncode == -signal.SIGALRM:
        return True, f'ran {seconds} s until the timer'
    return False, (fatal[0] if fatal else f'exit {p.returncode} before the timer')


def version(app):
    return plistlib.loads((Path(app) / 'Contents/Info.plist').read_bytes())['CFBundleShortVersionString']


def status(src, dest):
    if is_patched(src):
        print(f'Claude {version(src)}: patched in place')
        return 0
    if Path(BACKUP).exists():
        print(f'Claude {version(src)}: not patched. A Claude update removed the patch. '
              'Run: python3 rtl.py repair (or /rtl install yes)')
        return 1
    if not Path(dest).exists():
        print('no copy yet; run: python3 rtl.py install')
        return 1
    a, b = version(src), version(dest)
    print(f'Claude {a}, copy {b}: ' + ('current' if a == b else 'OLD, run: python3 rtl.py update'))
    return int(a != b)


def is_patched(app):
    return b'claude-rtl-menu' in read_file(Path(app) / 'Contents/Resources/app.asar', MAIN)


def stop_if_running(app):
    pids = running(app)
    if pids:
        raise SystemExit(f'{Path(app).name} is running (process {pids[0]}). Quit it with Cmd+Q, then run this again.')


def swap_in(src, staged, backup):
    """Put the tested copy where the original is. The original goes to `backup`,
    and comes back if the move fails half way."""
    src, staged, backup = Path(src), Path(staged), Path(backup)
    stop_if_running(src)
    stop_if_running(staged)
    backup.parent.mkdir(parents=True, exist_ok=True)
    if backup.exists():
        shutil.rmtree(backup)
    shutil.move(src, backup)
    try:
        shutil.move(staged, src)
    except OSError:
        shutil.move(backup, src)
        raise


def swap_out(src, backup):
    src, backup = Path(src), Path(backup)
    if not backup.exists():
        raise SystemExit(f'no saved original at {backup}; nothing to restore')
    stop_if_running(src)
    shutil.rmtree(src)
    shutil.move(backup, src)


def agent_plist(script, state):
    return plistlib.dumps({'Label': LABEL, 'RunAtLoad': True, 'StartInterval': 600,
                           'ProgramArguments': [sys.executable, str(script), 'repair', '--state-file', str(state)]})


def stage_tool(dest=TOOL):
    """Copy what repair needs to a folder that stays put, so a moved clone or an
    updated plugin cannot break the background job."""
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    for name in ('rtl.py', 'payload.js', 'main-snippet.js'):
        shutil.copy2(HERE / name, dest / name)
    return dest / 'rtl.py'


def relaunch_script(script, state, log, delay=25):
    q = shlex.quote
    py, quit_after = sys.executable, 45
    return f'''#!/bin/bash
# One-shot: quit Claude, patch it in place, open it again. Started by launchd so it outlives Claude.
exec > {q(str(log))} 2>&1
echo "start $(date '+%F %T')"
apps() {{ ps -axo pid=,command= | awk '/Claude(-RTL)?\\.app\\/Contents/ && !/awk/ {{print $1}}'; }}
mains() {{ ps -axo pid=,command= | awk '$2 ~ /Claude(-RTL)?\\.app\\/Contents\\/MacOS\\/Claude$/ {{print $1}}'; }}
sleep {delay}
for p in $(mains); do kill -TERM "$p"; done
for i in $(seq 1 {quit_after}); do [ -z "$(apps)" ] && break; sleep 1; done
if [ -n "$(apps)" ]; then
  for p in $(apps); do kill -KILL "$p"; done
  sleep 3
fi
{q(py)} {q(str(script))} install --in-place --state-file {q(str(state))}
echo "install exit $?"
sleep 2
open /Applications/Claude.app
echo "open exit $?"
launchctl bootout "gui/$(id -u)/{ONCE}" 2>/dev/null
echo "done $(date '+%F %T')"
'''


def relaunch(state):
    """Patch the app while it runs: a job outside Claude closes it, installs and opens it again."""
    tool = stage_tool()
    sh = KEEP / 'relaunch.sh'
    sh.write_text(relaunch_script(tool, state, LOG))
    sh.chmod(0o755)
    plist = KEEP / f'{ONCE}.plist'
    plist.write_bytes(plistlib.dumps({'Label': ONCE, 'RunAtLoad': True, 'ProgramArguments': ['/bin/bash', str(sh)],
                                      'EnvironmentVariables': {'PATH': '/usr/bin:/bin:/usr/sbin:/sbin'}}))
    target = f'gui/{os.getuid()}'
    subprocess.run(['launchctl', 'bootout', f'{target}/{ONCE}'], capture_output=True)
    run(['launchctl', 'bootstrap', target, plist])
    print(f'Claude closes in about 25 seconds, then opens again with the patch (about 2 minutes). Log: {LOG}')


def agent_on(state):
    AGENT.parent.mkdir(parents=True, exist_ok=True)
    AGENT.write_bytes(agent_plist(stage_tool(), state))
    target = f'gui/{os.getuid()}'
    subprocess.run(['launchctl', 'bootout', f'{target}/{LABEL}'], capture_output=True)
    run(['launchctl', 'bootstrap', target, AGENT])


def agent_off():
    subprocess.run(['launchctl', 'bootout', f'gui/{os.getuid()}/{LABEL}'], capture_output=True)
    AGENT.unlink(missing_ok=True)


def install_in_place(src, dest, state):
    # A second install must not save the patched app as the "original".
    if is_patched(src):
        print(f'{src} is already patched. Nothing to build.')
        return
    install(src, dest, state, force=True, announce=False)
    swap_in(src, dest, BACKUP)
    FAILED.unlink(missing_ok=True)
    print(f'The patch is now in {src}. The original is kept in {BACKUP}.')


def repair(src, dest, state, failed=FAILED):
    """Run by the agent: put the patch back after Claude updated itself. Returns a note.
    A version that failed its own smoke test is not tried again until Claude updates."""
    if is_patched(src):
        return 'patched'
    if running(src):
        return 'waiting: Claude is running'
    if Path(failed).exists() and Path(failed).read_text() == version(src):
        return f'skipped: {version(src)} failed before'
    try:
        install_in_place(src, dest, state)
    except SystemExit:
        Path(failed).parent.mkdir(parents=True, exist_ok=True)
        Path(failed).write_text(version(src))
        raise
    return 'repaired'


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('cmd', choices=['install', 'update', 'repair', 'status', 'smoke', 'uninstall'])
    p.add_argument('--relaunch', action='store_true',
                   help='with --in-place: close Claude, patch it and open it again, even when it runs now')
    p.add_argument('--in-place', action='store_true',
                   help='patch /Applications/Claude.app itself, keep the original, and put the patch back after each Claude update')
    p.add_argument('--src', default=SRC, type=Path, help='the original app (default /Applications/Claude.app)')
    p.add_argument('--dest', default=DEST, type=Path, help='where the copy goes (default ~/Applications/Claude-RTL.app)')
    p.add_argument('--state-file', help='where the on/off setting is kept')
    a = p.parse_args()
    if a.cmd in ('install', 'update') and a.in_place and a.relaunch:
        relaunch(state_path(a.state_file))
    elif a.cmd in ('install', 'update') and a.in_place:
        state = state_path(a.state_file)
        install_in_place(a.src, a.dest, state)
        agent_on(state)
    elif a.cmd in ('install', 'update'):
        install(a.src, a.dest, state_path(a.state_file), force=a.cmd == 'update')
    elif a.cmd == 'repair':
        print(repair(a.src, a.dest, state_path(a.state_file)))
    elif a.cmd == 'status':
        sys.exit(status(a.src, a.dest))
    elif a.cmd == 'smoke':
        ok, detail = smoke(a.dest)
        print(('ok: ' if ok else 'FAILED: ') + detail)
        sys.exit(0 if ok else 1)
    elif BACKUP.exists():
        swap_out(a.src, BACKUP)
        agent_off()
        print(f'restored the original {a.src}. Your setting file stays where it was.')
    else:
        pids = running(a.dest)
        if pids:
            raise SystemExit(f'{a.dest.name} is running (process {pids[0]}). Quit it with Cmd+Q, then run this again.')
        remove(a.dest)
        print(f'removed {a.dest}. Your setting file stays where it was; delete it by hand if you want.')


if __name__ == '__main__':
    main()
