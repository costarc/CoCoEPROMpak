#!/usr/bin/env python3
"""rom2coco.py - turn a CoCo ROM file into images that EEWRITE can burn.

The CoCo can't read a raw .ROM file by itself, but it can load a
machine-code file with LOADM (disk) or CLOADM (cassette). So this
script wraps the ROM up as a file that loads into RAM at $4000,
ready for EEWRITE to copy into the AT28C256.

A ROM of up to 16 KB gives one image (bank A, the low half of the chip).
A ROM of up to 32 KB gives two images: bank A and bank B (the high half).

For each image you get:
  NAMEA.BIN  for LOADM, from a disk (or a CoCo SDC, or DriveWire)
  NAMEA.CAS  a cassette image, for emulators such as XRoar
  NAMEA.WAV  the same cassette as sound, to play into a real CoCo

With --writer EEWRITE.BIN you also get NAME.DSK, a Disk BASIC floppy
image holding the writer and the images together.

Usage:  python3 rom2coco.py game.rom [--writer EEWRITE.BIN]

Roni Costa, 2026. GPL v3.
"""

import argparse
import math
import os
import struct
import sys
import wave

LOAD = 0x4000      # where the image sits in RAM
EXEC = 0x3800      # EEWRITE's start address
REACH = 0x3F00     # bytes per bank the CoCo can reach ($C000-$FEFF)
BANK = 0x4000      # 16 KB


def make_image(data, bank, name):
    """One bank of ROM data plus the label EEWRITE looks for at $7F00."""
    label = b"EEIMG1" + bank.encode() + b"\0" + name.upper().encode()[:15] + b"\0"
    return data[:REACH] + label


# ----- Disk BASIC LOADM format -----------------------------------
def decb_bin(image):
    out = struct.pack(">BHH", 0, len(image), LOAD) + image
    return out + struct.pack(">BHH", 0xFF, 0, EXEC)


# ----- cassette ---------------------------------------------------
def cas_block(btype, payload):
    csum = (btype + len(payload) + sum(payload)) & 0xFF
    return bytes([0x55, 0x3C, btype, len(payload)]) + payload + bytes([csum, 0x55])


def cas_file(image, name):
    """Return (namefile part, data part) of a CLOADM cassette file."""
    fname = name.upper().encode()[:8].ljust(8)
    header = fname + struct.pack(">BBBHH", 2, 0, 0, EXEC, LOAD)
    leader = bytes([0x55]) * 128
    part1 = leader + cas_block(0x00, header)
    part2 = leader
    for i in range(0, len(image), 255):
        part2 += cas_block(0x01, image[i:i + 255])
    part2 += cas_block(0xFF, b"")
    return part1, part2


def cas_wav(parts, path, rate=9600):
    """1200 baud: a 0 is one cycle at 1200 Hz, a 1 is one cycle at 2400 Hz."""
    def cycle(freq):
        n = rate // freq
        return bytes(int(128 + 100 * math.sin(2 * math.pi * i / n)) for i in range(n))
    zero, one = cycle(1200), cycle(2400)
    silence = bytes([128]) * (rate // 2)        # half a second, for the motor
    audio = bytearray(silence)
    for part in parts:
        for byte in part:
            for bit in range(8):                # least significant bit first
                audio += one if (byte >> bit) & 1 else zero
        audio += silence
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(1)
        w.setframerate(rate)
        w.writeframes(bytes(audio))


# ----- Disk BASIC floppy (35 tracks, 18 sectors of 256 bytes) ----
def decb_dsk(files):
    disk = bytearray([0xFF]) * (35 * 18 * 256)

    def sector(track, sec):
        off = (track * 18 + sec - 1) * 256
        return off

    fat = bytearray([0xFF]) * 68
    directory = []
    gran = 0
    for fname, ext, content in files:
        first = None
        prev = None
        left = content
        while True:
            # two granules per track, skipping track 17 (the directory)
            track = gran // 2 if gran < 34 else gran // 2 + 1
            base = sector(track, 1 + 9 * (gran % 2))
            chunk, left = left[:9 * 256], left[9 * 256:]
            disk[base:base + len(chunk)] = chunk
            if first is None:
                first = gran
            if prev is not None:
                fat[prev] = gran
            prev = gran
            gran += 1
            if not left:
                fat[prev] = 0xC0 + math.ceil(len(chunk) / 256)
                break
        last = len(content) % 256 or 256
        entry = (fname.upper().encode()[:8].ljust(8) + ext.upper().encode()[:3].ljust(3)
                 + bytes([2, 0, first]) + struct.pack(">H", last) + bytes(16))
        directory.append(entry)
    fat_sector = bytearray(256)
    fat_sector[:68] = fat
    off = sector(17, 2)
    disk[off:off + 256] = fat_sector
    off = sector(17, 3)
    for i, entry in enumerate(directory):
        disk[off + 32 * i:off + 32 * i + 32] = entry
    return bytes(disk)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("rom")
    ap.add_argument("--writer", help="EEWRITE.BIN, to build a .DSK as well")
    ap.add_argument("--name", help="short name for the files (default: from the ROM)")
    args = ap.parse_args()

    rom = open(args.rom, "rb").read()
    if len(rom) > 2 * BANK:
        sys.exit("That ROM is bigger than 32 KB, which won't fit the AT28C256.")
    size = BANK if len(rom) <= BANK else 2 * BANK
    rom = rom + b"\xFF" * (size - len(rom))     # $FF is what a blank chip holds

    base = args.name or os.path.splitext(os.path.basename(args.rom))[0]
    base = "".join(c for c in base.upper() if c.isalnum())[:7] or "ROM"
    outdir = os.path.dirname(os.path.abspath(args.rom))
    disk_files = []
    if args.writer:
        disk_files.append(("EEWRITE", "BIN", open(args.writer, "rb").read()))

    for i, bank in enumerate("AB"[:size // BANK]):
        data = rom[i * BANK:(i + 1) * BANK]
        lost = data[REACH:]
        if lost.strip(b"\xFF"):
            print(f"Warning: bank {bank} has data in its last 256 bytes. The CoCo "
                  "can't reach those, so they will not be written.")
        name = base + bank
        image = make_image(data, bank, os.path.basename(args.rom))
        path = os.path.join(outdir, name)
        open(path + ".BIN", "wb").write(decb_bin(image))
        parts = cas_file(image, name)
        open(path + ".CAS", "wb").write(b"".join(parts))
        cas_wav(parts, path + ".WAV")
        disk_files.append((name, "BIN", decb_bin(image)))
        print(f"Bank {bank}: {name}.BIN, {name}.CAS and {name}.WAV")

    if args.writer:
        dsk = os.path.join(outdir, base + ".DSK")
        open(dsk, "wb").write(decb_dsk(disk_files))
        print(f"Disk image: {base}.DSK")


if __name__ == "__main__":
    main()
