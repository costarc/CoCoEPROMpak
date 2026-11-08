"""Tiny 6809 assembler for the subset EEWRITE uses (lwasm syntax, --decb output).
Written only to test eewrite.asm when lwtools isn't available."""
import re, struct, sys

INH = {'rts':[0x39],'decb':[0x5A],'tstb':[0x5D],'clra':[0x4F],'lsra':[0x44],'lsla':[0x48],'clrb':[0x5F],'inca':[0x4C],'deca':[0x4A]}
# mnemonic: (imm, idx, ext, immsize)  prefix bytes included
OPS = {
 'lda':([0x86],[0xA6],[0xB6],1), 'ldb':([0xC6],[0xE6],[0xF6],1), 'ldd':([0xCC],[0xEC],[0xFC],2),
 'ldx':([0x8E],[0xAE],[0xBE],2), 'ldy':([0x10,0x8E],[0x10,0xAE],[0x10,0xBE],2), 'ldu':([0xCE],[0xEE],[0xFE],2),
 'sta':(None,[0xA7],[0xB7],0), 'stb':(None,[0xE7],[0xF7],0), 'std':(None,[0xED],[0xFD],0),
 'stx':(None,[0xAF],[0xBF],0), 'sty':(None,[0x10,0xAF],[0x10,0xBF],0), 'stu':(None,[0xEF],[0xFF],0),
 'cmpa':([0x81],[0xA1],[0xB1],1), 'cmpb':([0xC1],[0xE1],[0xF1],1),
 'cmpx':([0x8C],[0xAC],[0xBC],2), 'cmpy':([0x10,0x8C],[0x10,0xAC],[0x10,0xBC],2), 'cmpu':([0x11,0x83],[0x11,0xA3],[0x11,0xB3],2),
 'suba':([0x80],[0xA0],[0xB0],1), 'adda':([0x8B],[0xAB],[0xBB],1), 'anda':([0x84],[0xA4],[0xB4],1),
 'ora':([0x8A],[0xAA],[0xBA],1), 'bita':([0x85],[0xA5],[0xB5],1), 'addd':([0xC3],[0xE3],[0xF3],2), 'subd':([0x83],[0xA3],[0xB3],2),
 'jsr':(None,[0xAD],[0xBD],0), 'jmp':(None,[0x6E],[0x7E],0),
 'tst':(None,[0x6D],[0x7D],0), 'clr':(None,[0x6F],[0x7F],0), 'inc':(None,[0x6C],[0x7C],0), 'dec':(None,[0x6A],[0x7A],0),
 'leax':(None,[0x30],None,0), 'leay':(None,[0x31],None,0), 'leas':(None,[0x32],None,0), 'leau':(None,[0x33],None,0),
}
BR = {'bra':0x20,'bhi':0x22,'bls':0x23,'bhs':0x24,'bcc':0x24,'blo':0x25,'bcs':0x25,'bne':0x26,'beq':0x27,'bmi':0x2B,'bpl':0x2A,'bsr':0x8D}
LBR = {'lbra':[0x16],'lbsr':[0x17],'lbne':[0x10,0x26],'lbeq':[0x10,0x27],'lblo':[0x10,0x25]}
IMMCC = {'orcc':0x1A,'andcc':0x1C}
RR = {'x':0,'y':1,'u':2,'s':3}
TFR = {'d':0,'x':1,'y':2,'u':3,'s':4,'pc':5,'a':8,'b':9,'cc':10,'dp':11}
PSH = {'cc':1,'a':2,'b':4,'d':6,'dp':8,'x':0x10,'y':0x20,'u':0x40,'s':0x40,'pc':0x80}

def split_ops(s):
    # split on commas, but not inside quotes
    return [p.strip() for p in s.split(',')]

class Asm:
    def __init__(s): s.sym = {}
    def ev(s, e, final):
        e = e.strip()
        def rep(m):
            t = m.group(0)
            if t.startswith('$'): return str(int(t[1:], 16))
            if t.startswith("'"): return str(ord(t[1]))
            if t[0].isdigit(): return t
            if t in s.sym: return str(s.sym[t])
            if final: raise KeyError(t)
            return '0'
        e2 = re.sub(r"\$[0-9A-Fa-f]+|'.|[A-Za-z_][A-Za-z0-9_]*|\d+", rep, e)
        return int(eval(e2.replace('/', '//')))
    def known(s, e):
        try: s.ev(e, True); return True
        except KeyError: return False

    def indexed(s, op, final):
        op = op.strip()
        ind = op.startswith('[')
        if ind:
            inner = op[1:-1]
            if ',' not in inner:
                return [0x9F] + list(struct.pack('>H', s.ev(inner, final) & 0xFFFF))
            raise ValueError('indirect indexed not supported')
        off, reg = op.rsplit(',', 1)
        reg = reg.strip().lower()
        if reg.endswith('++'): return [0x80 | RR[reg[:-2]] << 5 | 1]
        if reg.endswith('+'): return [0x80 | RR[reg[:-1]] << 5]
        r = RR[reg] << 5
        if off.strip() == '': return [0x84 | r]
        n = s.ev(off, final) if (final or s.known(off)) else 999
        if -16 <= n <= 15: return [r | (n & 0x1F)]
        if -128 <= n <= 127: return [0x88 | r, n & 0xFF]
        return [0x89 | r] + list(struct.pack('>H', n & 0xFFFF))

    def line(s, mn, opnd, pc, final):
        mn = mn.lower()
        if mn in INH: return INH[mn]
        if mn in BR:
            t = s.ev(opnd, final); d = t - (pc + 2)
            if final and not -128 <= d <= 127: raise ValueError('branch out of range')
            return [BR[mn], d & 0xFF]
        if mn in LBR:
            n = len(LBR[mn]) + 2; d = s.ev(opnd, final) - (pc + n)
            return LBR[mn] + list(struct.pack('>H', d & 0xFFFF))
        if mn in IMMCC: return [IMMCC[mn], s.ev(opnd[1:], final) & 0xFF]
        if mn == 'tfr':
            a, b = [x.strip().lower() for x in opnd.split(',')]
            return [0x1F, TFR[a] << 4 | TFR[b]]
        if mn in ('pshs', 'puls'):
            m = 0
            for r in opnd.split(','): m |= PSH[r.strip().lower()]
            return [0x34 if mn == 'pshs' else 0x35, m]
        imm, idx, ext, isz = OPS[mn]
        if opnd.startswith('#'):
            v = s.ev(opnd[1:], final)
            return imm + (list(struct.pack('>H', v & 0xFFFF)) if isz == 2 else [v & 0xFF])
        if ',' in opnd or opnd.startswith('['):
            return idx + s.indexed(opnd, final)
        if s.known(opnd) and s.ev(opnd, True) < 0x100 and ext[-1] >> 4 in (0x7, 0xB, 0xF):
            return ext[:-1] + [ext[-1] - (0x70 if ext[-1] >> 4 == 0x7 else 0x20), s.ev(opnd, True)]
        return ext + list(struct.pack('>H', s.ev(opnd, final) & 0xFFFF))

    def run(s, src):
        for final in (False, True):
            pc = 0; out = {}; start = None; s.listing = []; rmb = set()
            for raw in src.splitlines():
                line = raw
                # strip comments (not inside quotes)
                m = re.match(r'^([^;"]*("[^"]*"[^;"]*)*)', line)
                line = m.group(1) if m else line
                if not line.strip(): continue
                lab = None
                if not line[0].isspace():
                    lab, _, line = line.partition(' ') if ' ' in line else (line.strip(), '', '')
                    lab = lab.strip()
                parts = line.strip().split(None, 1)
                mn = parts[0].lower() if parts else ''
                opnd = parts[1].strip() if len(parts) > 1 else ''
                if mn == 'equ':
                    s.sym[lab] = s.ev(opnd, final); continue
                if lab: s.sym[lab] = pc
                if not mn: continue
                if mn == 'org': pc = s.ev(opnd, final); continue
                if mn == 'end': start = s.ev(opnd, final) if opnd else None; continue
                if mn == 'fcc':
                    d = opnd[0]; txt = opnd[1:opnd.index(d, 1)]; b = list(txt.encode())
                elif mn == 'fcb': b = [s.ev(x, final) & 0xFF for x in split_ops(opnd)]
                elif mn == 'fdb': b = sum((list(struct.pack('>H', s.ev(x, final) & 0xFFFF)) for x in split_ops(opnd)), [])
                elif mn == 'rmb': b = [0] * s.ev(opnd, final); rmb.update(range(pc, pc + len(b)))
                else: b = s.line(mn, opnd, pc, final)
                for i, x in enumerate(b): out[pc + i] = x
                s.listing.append((pc, b, raw))
                pc += len(b)
        lo, hi = min(out), max(out)
        while hi in rmb: hi -= 1
        data = bytes(out.get(a, 0) for a in range(lo, hi + 1))
        return lo, data, start

if __name__ == '__main__':
    a = Asm(); lo, data, start = a.run(open(sys.argv[1]).read())
    binf = struct.pack('>BHH', 0, len(data), lo) + data + struct.pack('>BHH', 0xFF, 0, start)
    open(sys.argv[2], 'wb').write(binf)
    if len(sys.argv) > 3:
        with open(sys.argv[3], 'w') as f:
            for pc, b, raw in a.listing:
                f.write(f"{pc:04X} {' '.join('%02X' % x for x in b[:6]):18s} {raw}\n")
    print(f'{lo:04X}-{lo+len(data)-1:04X} ({len(data)} bytes), exec {start:04X}')
