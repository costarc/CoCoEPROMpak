import random, subprocess, sys, os, shutil, tempfile
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from sim import *
# Run from a scratch folder so the .rom/.BIN/.CAS files rom2coco.py makes don't pile up here.
WRITER = os.path.join(HERE, '..', 'EEWRITE.BIN')
ROM2COCO = os.path.join(HERE, '..', 'rom2coco.py')
os.chdir(tempfile.mkdtemp(prefix='eewrite-test-'))
shutil.copy(WRITER, 'EEWRITE.BIN')
W = open('EEWRITE.BIN','rb').read()
random.seed(7)
rom = bytes(random.randrange(256) for _ in range(30000))
open('t.rom','wb').write(rom)
subprocess.run([sys.executable,ROM2COCO,'t.rom','--writer','EEWRITE.BIN'],check=True,capture_output=True)
A = open('TA.BIN','rb').read(); B = open('TB.BIN','rb').read()
padded = rom + b'\xff'*(32768-len(rom))

def go(chip, keys, img=A, mpi=None, load_img=True):
    chip.busy_until = -1; chip.writes_seen = 0
    c = CoCo(chip, keys, mpi); c.ram[0x88] = 0x04; c.ram[0x89] = 0x00
    e1 = load_decb(c, W)
    e2 = load_decb(c, img) if load_img else e1
    assert e1 == e2 == 0x3800
    c.run(0x3800)
    return c

def show(name, c):
    print(f'--- {name}: {c.cyc/E_HZ:.2f} s emulated, chip errors={c.chip.errors}')
    print(c.screen.rstrip()); print('screen stars:', c.ram[0x400:0x440].count(0x6A))

ok = True
def check(cond, msg):
    global ok
    print(('PASS ' if cond else 'FAIL ') + msg); ok &= bool(cond)

# 1 blank chip, bank A, no Multi-Pak
chip = EEPROM(); c = go(chip, '\rW'); show('write bank A', c)
check(chip.mem[:0x3F00] == padded[:0x3F00], 'bank A contents match')
check(chip.mem[0x3F00:0x4000] == b'\xff'*256, 'last 256 bytes untouched')
check('ALL OK' in c.screen and 'PAGES WRITTEN: 252' in c.screen, 'messages')
# 2 rewrite same: nothing to do
c = go(chip, '\rW'); show('rewrite same', c)
check('PAGES WRITTEN: 0' in c.screen and 'ALL OK' in c.screen, 'skips unchanged pages')
# 3 bank B
chip.bank = 1; c = go(chip, '\rW', img=B); show('write bank B', c)
check(chip.mem[0x4000:0x7F00] == padded[0x4000:0x7F00] and chip.mem[:0x3F00]==padded[:0x3F00], 'bank B contents, bank A kept')
check(' BANK B' in c.screen, 'bank label shown')
# 4 change a few bytes
rom2 = bytearray(padded); rom2[100]^=1; rom2[5000]^=0xFF
open('t.rom','wb').write(rom2); subprocess.run([sys.executable,ROM2COCO,'t.rom'],check=True,capture_output=True)
chip.bank = 0; c = go(chip, '\rW', img=open('TA.BIN','rb').read()); show('small change', c)
check('PAGES WRITTEN: 2' in c.screen and chip.mem[:0x3F00]==bytes(rom2[:0x3F00]), 'only two pages rewritten')
# 5 unmodified board
chip = EEPROM(oe_mod=False); c = go(chip, '\rW'); show('no /OE mod', c)
check('DID NOT FINISH' in c.screen and '$C000' in c.screen, 'timeout reported at first page')
# 6 SDP on
chip = EEPROM(sdp=True); c = go(chip, '\rW'); show('SDP on', c)
check('DID NOT FINISH' in c.screen, 'SDP locked chip reported')
# 7 write jumper parked
chip = EEPROM(write_jumper=False); c = go(chip, '\rW'); show('write jumper off', c)
check('DID NOT FINISH' in c.screen, 'jumper off reported')
# 8 stuck cell
chip = EEPROM(stuck={0x1234: 0x00}); c = go(chip, '\rW'); show('bad cell', c)
check('BYTES DIFFER' in c.screen and '$D234' in c.screen, 'bad byte found at D234')
# 9 Multi-Pak: pak in slot 1, disk in slot 4
chip = EEPROM(); c = go(chip, '14W', mpi=(0,3)); show('multi-pak', c)
check(chip.mem[:0x3F00] == padded[:0x3F00] and 'ALL OK' in c.screen, 'writes through Multi-Pak')
check(c.mpireg == 0x33 and 0x03 in c.mpi_writes, f'MPI back on disk slot (writes {[hex(v) for v in c.mpi_writes]})')
# 10 verify only
c = go(chip, '14V', mpi=(0,3)); show('verify only', c)
check('ALL OK' in c.screen and 'WRITING' not in c.screen and chip.writes_seen == 0, 'verify only does not write')
# 11 no image loaded
chip = EEPROM(); c = go(chip, '', load_img=False); show('no image', c)
check('NO ROM IMAGE' in c.screen and chip.writes_seen == 0, 'refuses without an image')
# 12 BREAK quits
chip = EEPROM(); c = go(chip, '\r\x03'); show('break', c)
check(chip.writes_seen == 0, 'BREAK quits without writing')
print('ALL TESTS PASSED' if ok else 'SOME TESTS FAILED')
