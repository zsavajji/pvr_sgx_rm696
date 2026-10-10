#!/usr/bin/env python3
"""Checks, without the phone, that this driver's pvrsrvkm.ko dispatches ioctls as Harmattan's does (the r125
userspace blobs' interface): same ioctl index range, same unhandled indices, same indices sharing a
handler, and the same first kernel call in each handler. Both modules inline their handlers into one
switch, so the switch's jump table is compared.
  check-abi.py [ours.ko] [harmattan.ko]   (default: the build kit's ../rm696_mainline_port/build/pvrsrvkm.ko and
  ../rm696_mainline_port/build/harmattan-pvrsrvkm.ko)
Harmattan's module: debugfs -R "dump /lib/modules/2.6.32.54-dfl61-20121301/pvrsrvkm.ko
../rm696_mainline_port/build/harmattan-pvrsrvkm.ko" <firmware rootfs.ext4>. Needs llvm-objdump (in PATH, or Homebrew's: brew install llvm)."""
import re, shutil, struct, subprocess, sys

OBJDUMP = shutil.which('llvm-objdump') or '/opt/homebrew/opt/llvm/bin/llvm-objdump'
INSN = re.compile(r'\s+([0-9a-f]+):\s+(\S+)\s*(.*)')
# calls most handlers make: they don't tell handlers apart
SKIP = {'printk', '_printk', '__memzero', 'memset', 'memcpy', '__stack_chk_fail', 'OSCopyToUser',
        'OSCopyFromUser', 'PVRSRVLookupHandle', 'PVRSRVLookupHandleAnyType', 'PVRSRVFindHandle',
        'PVRSRVAllocHandle', 'PVRSRVAllocSubHandle', 'PVRSRVReleaseHandle', 'PVRSRVNewHandleBatch',
        'PVRSRVCommitHandleBatch', 'PVRSRVReleaseHandleBatch', 'PVRSRVLookupAndReleaseHandle'}


def section(data, want):
    shoff, = struct.unpack_from('<I', data, 0x20)
    size, num, stridx = struct.unpack_from('<HHH', data, 0x2e)
    hdrs = [struct.unpack_from('<10I', data, shoff + i * size) for i in range(num)]
    names = hdrs[stridx][4]
    for h in hdrs:
        if data[names + h[0]:data.index(b'\0', names + h[0])].decode() == want:
            return h[4]  # file offset


def jump_table(path):
    """(targets per index, default target, disassembly lines, address -> line index)"""
    data = open(path, 'rb').read()
    lines = subprocess.run([OBJDUMP, '-dr', '--no-show-raw-insn', '-j', '.text', path],
                           capture_output=True, text=True, check=True).stdout.splitlines()
    insns = [(k, int(m[1], 16), m[2], m[3]) for k, l in enumerate(lines) if (m := INSN.match(l))]
    pos = {a: k for k, a, _, _ in insns}
    text = section(data, '.text')
    best = None
    for n, (_, a, op, args) in enumerate(insns):
        m = re.fullmatch(r'(r\d+), #(\d+)', args)
        if op != 'cmp' or not m or int(m[2]) < 64 or (best and int(m[2]) <= best[0]):
            continue
        count, nxt = int(m[2]) + 1, insns[n + 1:n + 6]
        if nxt[0][2] == 'ldrls' and nxt[0][3].startswith('pc, [pc'):  # GCC 4.4: word table after b
            base, default = nxt[0][1] + 8, int(nxt[1][3].split()[0], 16)
            targets = [struct.unpack_from('<I', data, text + base + 4 * i)[0] for i in range(count)]
        elif nxt[0][2] == 'bhi' and any(i[2] == 'add' and i[3].startswith('pc, pc') for i in nxt):
            # GCC 14: halfword offsets in .rodata (base from a literal), pc-relative, scaled by 4
            addpc = next(i for i in nxt if i[2] == 'add' and i[3].startswith('pc, pc'))
            ldrh = next(i for i in nxt if i[2] == 'ldrh')
            basereg = re.search(r'\[(r\d+),', ldrh[3])[1]
            lit = next(int(re.search(r'@ 0x([0-9a-f]+)', i[3])[1], 16) for i in reversed(insns[n - 8:n])
                       if i[2] == 'ldr' and i[3].startswith(basereg + ', [pc'))
            tab = section(data, '.rodata') + struct.unpack_from('<I', data, text + lit)[0]
            default = int(nxt[0][3].split()[0], 16)
            targets = [addpc[1] + 8 + 4 * struct.unpack_from('<H', data, tab + 2 * i)[0]
                       for i in range(count)]
        else:
            continue
        best = (count - 1, targets, default)
    assert best, f'{path}: no ioctl jump table found'
    return best[1], best[2], lines, pos


def first_call(lines, pos, addr, budget=120):
    """The first kernel function a handler calls (bookkeeping calls skipped), following its
    unconditional branches; None if it returns or branches away first"""
    k, follows = pos[addr], 0
    while budget > 0 and k < len(lines):
        l = lines[k]
        k += 1
        m = re.search(r'R_ARM_(?:CALL|JUMP24)\s+(\S+)', l)
        if m and m[1] not in SKIP:
            return m[1]
        m = INSN.match(l)
        if not m:
            continue
        budget -= 1
        op, args = m[2], m[3]
        if op == 'b' and follows < 3 and int(args.split()[0], 16) in pos:
            follows += 1
            k = pos[int(args.split()[0], 16)]
        elif op in ('b', 'bx') or ('pc' in args.split('}')[0] and op.startswith(('pop', 'ldm'))):
            return None


def reachable_calls(lines, pos, addr, budget=300):
    """Kernel functions called within budget instructions of addr, through any branch"""
    seen, todo, calls = set(), [addr], set()
    while todo and budget > 0:
        a = todo.pop(0)
        if a in seen or a not in pos:
            continue
        seen.add(a)
        for l in lines[pos[a]:]:
            m = re.search(r'R_ARM_(?:CALL|JUMP24)\s+(\S+)', l)
            if m and m[1] not in SKIP:
                calls.add(m[1])
            m = INSN.match(l)
            if not m:
                continue
            budget -= 1
            if m[2].startswith('b') and not m[2].startswith(('bl', 'bic', 'bx')):
                todo.append(int(m[3].split()[0], 16))
                if m[2] == 'b':
                    break
            elif m[2] == 'bx' or ('pc' in m[3].split('}')[0] and m[2].startswith(('pop', 'ldm'))):
                break
    return calls


def summary(path):
    targets, default, lines, pos = jump_table(path)
    handlers = {}
    for i, t in enumerate(targets):
        handlers.setdefault(t, []).append(i)
    unhandled = handlers.pop(default, [])
    calls = {i: (first_call(lines, pos, t), lambda t=t: reachable_calls(lines, pos, t))
             for i, t in enumerate(targets) if t != default}
    return len(targets), unhandled, sorted(handlers.values()), calls


if __name__ == '__main__':
    ours, theirs = (sys.argv[1:] + ['../rm696_mainline_port/build/pvrsrvkm.ko', '../rm696_mainline_port/build/harmattan-pvrsrvkm.ko'][len(sys.argv) - 1:])[:2]
    o, h = summary(ours), summary(theirs)
    ok = True
    for what, a, b in (('ioctl indices', o[0], h[0]), ('unhandled', o[1], h[1]), ('handler groups', o[2], h[2])):
        print(f'{what}: {"same" if a == b else f"DIFFERENT: ours {a}, Harmattan {b}"}')
        ok &= a == b
    # a handler matches when its first call is the other's, or reachable in the other's handler
    # (compilers order an inlined handler's paths differently)
    both = [i for i in o[3] if o[3][i][0] and h[3].get(i, (None,))[0]]
    bad = [(i, o[3][i][0], h[3][i][0]) for i in both if o[3][i][0] != h[3][i][0]
           and h[3][i][0] not in o[3][i][1]() and o[3][i][0] not in h[3][i][1]()]
    print(f'first kernel call: same in {len(both) - len(bad)} of {len(both)} comparable handlers')
    for i, a, b in bad:
        print(f'  ioctl {i}: ours {a}, Harmattan {b}')
    sys.exit(0 if ok and not bad else 1)
