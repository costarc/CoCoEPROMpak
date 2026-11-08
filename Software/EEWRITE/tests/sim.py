"""Minimal 6809 + CoCo + AT28C256 model, for testing EEWRITE.
Only the instructions EEWRITE uses are implemented; anything else raises."""
import struct

E_HZ = 894886            # CoCo E clock
TBLC = 150e-6            # byte load cycle limit
TWC = 5e-3               # write cycle time (datasheet max 10 ms)
TRAP_POLCAT, TRAP_CHROUT = 0xA100, 0xA200


class EEPROM:
    def __init__(s, oe_mod=True, sdp=False, write_jumper=True, bank=0, stuck=None):
        s.mem = bytearray([0xFF]) * 32768
        s.oe_mod, s.sdp, s.wj, s.bank = oe_mod, sdp, write_jumper, bank
        s.stuck = stuck or {}      # chip address -> forced value (a bad cell)
        s.page = None; s.buf = {}; s.last_load = None
        s.busy_until = -1; s.last_byte = 0; s.writes_seen = 0; s.cycles_committed = 0
        s.errors = []

    def _tick(s, t):
        if s.page is not None and t - s.last_load > TBLC:
            for a, v in s.buf.items():
                s.mem[a] = s.stuck.get(a, v)
            s.busy_until = s.last_load + TWC
            s.cycles_committed += 1
            s.page = None; s.buf = {}

    def read(s, addr, t, irq_masked):
        s._tick(t)
        a = s.bank << 14 | addr
        if t < s.busy_until or s.page is not None:
            return s.last_byte ^ 0x80           # data polling: bit 7 inverted
        return s.mem[a]

    def write(s, addr, v, t, irq_masked):
        s._tick(t)
        s.writes_seen += 1
        if not irq_masked: s.errors.append('cart write with IRQ unmasked')
        if not s.wj or not s.oe_mod or s.sdp:     # /WE parked, /OE low, or locked
            return
        if t < s.busy_until:
            s.errors.append('write while busy'); return
        a = s.bank << 14 | addr
        pg = a >> 6
        if s.page is None: s.page = pg
        elif s.page != pg: s.errors.append('page crossed during load')
        s.buf[a] = v; s.last_load = t; s.last_byte = v


class CoCo:
    def __init__(s, chip, keys='', mpi=None, disk_rom=0x5A):
        s.ram = bytearray(0x8000)
        s.chip = chip; s.keys = list(keys); s.screen = ''
        s.mpi = mpi                  # None, or (pak_slot, disk_slot) 0-3
        s.mpireg = None if mpi is None else mpi[1] * 0x11
        s.mpi_writes = []
        s.disk_rom = disk_rom
        s.a = s.b = s.dp = 0; s.x = s.y = s.u = 0; s.s = 0x37F0; s.pc = 0; s.cc = 0x50
        s.cyc = 0; s.steps = 0

    # ---- bus ----
    def t(s): return s.cyc / E_HZ
    def cart_selected(s):
        return s.mpi is None or (s.mpireg >> 4 & 3) == s.mpi[0]
    def rd(s, a):
        a &= 0xFFFF
        if a < 0x8000: return s.ram[a]
        if a == 0xA000: return TRAP_POLCAT >> 8
        if a == 0xA001: return TRAP_POLCAT & 0xFF
        if a == 0xA002: return TRAP_CHROUT >> 8
        if a == 0xA003: return TRAP_CHROUT & 0xFF
        if 0xC000 <= a < 0xFF00:
            if s.cart_selected(): return s.chip.read(a - 0xC000, s.t(), s.cc & 0x10)
            return s.disk_rom
        if a >= 0xFF00: raise RuntimeError(f'read of I/O {a:04X}')
        return 0x12  # BASIC ROM
    def wr(s, a, v):
        a &= 0xFFFF; v &= 0xFF
        if a < 0x8000: s.ram[a] = v; return
        if a == 0xFF7F: s.mpi_writes.append(v); s.mpireg = v; return
        if 0xC000 <= a < 0xFF00:
            if s.cart_selected(): s.chip.write(a - 0xC000, v, s.t(), s.cc & 0x10)
            return
        raise RuntimeError(f'write to {a:04X} at PC {s.pc:04X}')
    def rw(s, a): return s.rd(a) << 8 | s.rd(a + 1)
    def ww(s, a, v): s.wr(a, v >> 8); s.wr(a + 1, v & 0xFF)
    def fetch(s): v = s.rd(s.pc); s.pc = (s.pc + 1) & 0xFFFF; return v
    def fetchw(s): return s.fetch() << 8 | s.fetch()

    # ---- registers ----
    @property
    def d(s): return s.a << 8 | s.b
    @d.setter
    def d(s, v): s.a, s.b = v >> 8 & 0xFF, v & 0xFF
    REGS = {0: 'x', 1: 'y', 2: 'u', 3: 's'}
    def nz8(s, v): s.cc = s.cc & ~0x0C | (0x08 if v & 0x80 else 0) | (0x04 if v & 0xFF == 0 else 0)
    def nz16(s, v): s.cc = s.cc & ~0x0C | (0x08 if v & 0x8000 else 0) | (0x04 if v & 0xFFFF == 0 else 0)
    def setv_c(s, v, c): s.cc = s.cc & ~0x03 | (0x02 if v else 0) | (0x01 if c else 0)
    def Z(s): return bool(s.cc & 4)
    def C(s): return bool(s.cc & 1)

    def ea(s):
        pb = s.fetch()
        if not pb & 0x80:
            r = s.REGS[pb >> 5 & 3]; off = pb & 0x1F
            if off & 0x10: off -= 32
            s.cyc += 1; return (getattr(s, r) + off) & 0xFFFF
        r = s.REGS[pb >> 5 & 3]; mode = pb & 0x1F
        if mode == 0x00: v = getattr(s, r); setattr(s, r, (v + 1) & 0xFFFF); s.cyc += 2; return v
        if mode == 0x01: v = getattr(s, r); setattr(s, r, (v + 2) & 0xFFFF); s.cyc += 3; return v
        if mode == 0x04: return getattr(s, r)
        if mode == 0x08:
            o = s.fetch(); o = o - 256 if o & 0x80 else o; s.cyc += 1
            return (getattr(s, r) + o) & 0xFFFF
        if mode == 0x09:
            o = s.fetchw(); s.cyc += 4; return (getattr(s, r) + o) & 0xFFFF
        if pb == 0x9F: a = s.fetchw(); s.cyc += 5; return s.rw(a)
        raise RuntimeError(f'indexed mode {pb:02X}')

    def push(s, v): s.s = (s.s - 1) & 0xFFFF; s.wr(s.s, v)
    def pull(s): v = s.rd(s.s); s.s = (s.s + 1) & 0xFFFF; return v
    def pushw(s, v): s.push(v & 0xFF); s.push(v >> 8)
    def pullw(s): return s.pull() << 8 | s.pull()

    def sub8(s, a, m):
        r = (a - m) & 0x1FF
        s.nz8(r); s.setv_c(((a ^ m) & (a ^ r)) & 0x80, r & 0x100); return r & 0xFF
    def sub16(s, a, m):
        r = (a - m) & 0x1FFFF
        s.nz16(r); s.setv_c(((a ^ m) & (a ^ r)) & 0x8000, r & 0x10000); return r & 0xFFFF
    def add8(s, a, m):
        r = a + m; s.nz8(r); s.setv_c((~(a ^ m) & (a ^ r)) & 0x80, r & 0x100); return r & 0xFF

    def branch(s, cond, long=False):
        if long: o = s.fetchw(); o = o - 65536 if o & 0x8000 else o
        else: o = s.fetch(); o = o - 256 if o & 0x80 else o
        if cond: s.pc = (s.pc + o) & 0xFFFF

    def trap(s):
        if s.pc == TRAP_POLCAT:
            if s.keys:
                s.a = ord(s.keys.pop(0)); s.cc &= ~4
            else:
                s.a = 0; s.cc |= 4; s.idle += 1
                if s.idle > 1000: raise TimeoutError('waiting for a key')
        else:
            c = chr(s.a); s.screen += '\n' if c == '\r' else c
        s.pc = s.pullw(); s.cyc += 50
        return True

    def run(s, start, max_steps=50_000_000):
        s.pc = start; s.idle = 0
        s.pushw(0xDEAD)               # return to "BASIC"
        while s.pc != 0xDEAD:
            s.steps += 1
            if s.steps > max_steps: raise RuntimeError('runaway')
            if s.pc in (TRAP_POLCAT, TRAP_CHROUT): s.trap(); continue
            s.step()

    def step(s):
        op = s.fetch()
        if op == 0x10:
            op2 = s.fetch()
            if op2 == 0x8E: s.y = s.fetchw(); s.nz16(s.y); s.cc &= ~2; s.cyc += 4; return
            if op2 == 0xBF: a = s.fetchw(); s.ww(a, s.y); s.nz16(s.y); s.cc &= ~2; s.cyc += 7; return
            if op2 == 0x8C: s.sub16(s.y, s.fetchw()); s.cyc += 5; return
            if op2 == 0x26: s.branch(not s.Z(), True); s.cyc += 6; return
            if op2 == 0x27: s.branch(s.Z(), True); s.cyc += 6; return
            raise RuntimeError(f'op 10 {op2:02X} at {s.pc-2:04X}')
        c = s.cyc
        if op == 0x86: s.a = s.fetch(); s.nz8(s.a); s.cc &= ~2; s.cyc += 2
        elif op == 0xA6: s.a = s.rd(s.ea()); s.nz8(s.a); s.cc &= ~2; s.cyc += 4
        elif op == 0xB6: s.a = s.rd(s.fetchw()); s.nz8(s.a); s.cc &= ~2; s.cyc += 5
        elif op == 0xC6: s.b = s.fetch(); s.nz8(s.b); s.cc &= ~2; s.cyc += 2
        elif op == 0xCC: s.d = s.fetchw(); s.nz16(s.d); s.cc &= ~2; s.cyc += 3
        elif op == 0xFC: s.d = s.rw(s.fetchw()); s.nz16(s.d); s.cc &= ~2; s.cyc += 6
        elif op == 0x8E: s.x = s.fetchw(); s.nz16(s.x); s.cc &= ~2; s.cyc += 3
        elif op == 0x9E: s.x = s.rw(s.fetch()); s.nz16(s.x); s.cc &= ~2; s.cyc += 5
        elif op == 0x9F: s.ww(s.fetch(), s.x); s.nz16(s.x); s.cc &= ~2; s.cyc += 5
        elif op == 0x96: s.a = s.rd(s.fetch()); s.nz8(s.a); s.cc &= ~2; s.cyc += 4
        elif op == 0xBE: s.x = s.rw(s.fetchw()); s.nz16(s.x); s.cc &= ~2; s.cyc += 6
        elif op == 0xCE: s.u = s.fetchw(); s.nz16(s.u); s.cc &= ~2; s.cyc += 3
        elif op == 0xA7: a = s.ea(); s.wr(a, s.a); s.nz8(s.a); s.cc &= ~2; s.cyc += 4
        elif op == 0xB7: s.wr(s.fetchw(), s.a); s.nz8(s.a); s.cc &= ~2; s.cyc += 5
        elif op == 0xFD: s.ww(s.fetchw(), s.d); s.nz16(s.d); s.cc &= ~2; s.cyc += 6
        elif op == 0xBF: s.ww(s.fetchw(), s.x); s.nz16(s.x); s.cc &= ~2; s.cyc += 6
        elif op == 0x81: s.sub8(s.a, s.fetch()); s.cyc += 2
        elif op == 0xA1: s.sub8(s.a, s.rd(s.ea())); s.cyc += 4
        elif op == 0x8C: s.sub16(s.x, s.fetchw()); s.cyc += 4
        elif op == 0x80: s.a = s.sub8(s.a, s.fetch()); s.cyc += 2
        elif op == 0x8B: s.a = s.add8(s.a, s.fetch()); s.cyc += 2
        elif op == 0x84: s.a &= s.fetch(); s.nz8(s.a); s.cc &= ~2; s.cyc += 2
        elif op == 0x8A: s.a |= s.fetch(); s.nz8(s.a); s.cc &= ~2; s.cyc += 2
        elif op == 0xBA: s.a |= s.rd(s.fetchw()); s.nz8(s.a); s.cc &= ~2; s.cyc += 5
        elif op == 0x85: s.nz8(s.a & s.fetch()); s.cc &= ~2; s.cyc += 2
        elif op == 0xC3:
            m = s.fetchw(); r = s.d + m; s.nz16(r); s.setv_c((~(s.d ^ m) & (s.d ^ r)) & 0x8000, r & 0x10000)
            s.d = r & 0xFFFF; s.cyc += 4
        elif op == 0xA3: a = s.ea(); s.d = s.sub16(s.d, s.rw(a)); s.cyc += 6
        elif op in (0x20, 0x22, 0x23, 0x25, 0x26, 0x27):
            cond = {0x20: True, 0x22: not s.C() and not s.Z(), 0x23: s.C() or s.Z(), 0x25: s.C(),
                    0x26: not s.Z(), 0x27: s.Z()}[op]
            s.branch(cond); s.cyc += 3
        elif op == 0x8D:
            o = s.fetch(); o = o - 256 if o & 0x80 else o; s.pushw(s.pc); s.pc = (s.pc + o) & 0xFFFF; s.cyc += 7
        elif op == 0x17:
            o = s.fetchw(); o = o - 65536 if o & 0x8000 else o; s.pushw(s.pc); s.pc = (s.pc + o) & 0xFFFF; s.cyc += 9
        elif op == 0xBD: a = s.fetchw(); s.pushw(s.pc); s.pc = a; s.cyc += 8
        elif op == 0xAD: a = s.ea(); s.pushw(s.pc); s.pc = a; s.cyc += 7
        elif op == 0x6E: s.pc = s.ea(); s.cyc += 3
        elif op == 0x7E: s.pc = s.fetchw(); s.cyc += 4
        elif op == 0x39: s.pc = s.pullw(); s.cyc += 5
        elif op == 0x34:
            m = s.fetch(); s.cyc += 5
            if m & 0x40: s.pushw(s.u); s.cyc += 2
            if m & 0x20: s.pushw(s.y); s.cyc += 2
            if m & 0x10: s.pushw(s.x); s.cyc += 2
            if m & 0x04: s.push(s.b); s.cyc += 1
            if m & 0x02: s.push(s.a); s.cyc += 1
            if m & ~0x76: raise RuntimeError('pshs mask')
        elif op == 0x35:
            m = s.fetch(); s.cyc += 5
            if m & 0x02: s.a = s.pull(); s.cyc += 1
            if m & 0x04: s.b = s.pull(); s.cyc += 1
            if m & 0x10: s.x = s.pullw(); s.cyc += 2
            if m & 0x20: s.y = s.pullw(); s.cyc += 2
            if m & 0x40: s.u = s.pullw(); s.cyc += 2
            if m & ~0x76: raise RuntimeError('puls mask')
        elif op in (0x30, 0x31, 0x33):
            v = s.ea(); s.cyc += 4
            if op == 0x30: s.x = v; s.cc = s.cc & ~4 | (4 if v == 0 else 0)
            elif op == 0x31: s.y = v; s.cc = s.cc & ~4 | (4 if v == 0 else 0)
            else: s.u = v                      # LEAU leaves Z alone
        elif op == 0x1F:
            pb = s.fetch(); s.cyc += 6
            if pb != 0x20: raise RuntimeError('tfr')
            s.d = s.y
        elif op == 0x7D: v = s.rd(s.fetchw()); s.nz8(v); s.cc &= ~2; s.cyc += 7
        elif op == 0x7F: s.wr(s.fetchw(), 0); s.cc = s.cc & ~0x0F | 4; s.cyc += 7
        elif op == 0x7C:
            a = s.fetchw(); v = (s.rd(a) + 1) & 0xFF; s.wr(a, v); s.nz8(v); s.cyc += 7
        elif op == 0x5A: s.b = (s.b - 1) & 0xFF; s.nz8(s.b); s.cyc += 2
        elif op == 0x5D: s.nz8(s.b); s.cc &= ~3; s.cyc += 2
        elif op == 0x4F: s.a = 0; s.cc = s.cc & ~0x0F | 4; s.cyc += 2
        elif op == 0x44: s.cc = s.cc & ~1 | (s.a & 1); s.a >>= 1; s.nz8(s.a); s.cyc += 2
        elif op == 0x48: s.cc = s.cc & ~1 | (s.a >> 7); s.a = (s.a << 1) & 0xFF; s.nz8(s.a); s.cyc += 2
        elif op == 0x1A: s.cc |= s.fetch(); s.cyc += 3
        elif op == 0x1C: s.cc &= s.fetch(); s.cyc += 3
        else: raise RuntimeError(f'opcode {op:02X} at {s.pc-1:04X}')


def load_decb(coco, data):
    i = 0; exec_ = None
    while i < len(data):
        kind, n, addr = struct.unpack('>BHH', data[i:i + 5]); i += 5
        if kind == 0xFF: exec_ = addr; break
        coco.ram[addr:addr + n] = data[i:i + n]; i += n
    return exec_
