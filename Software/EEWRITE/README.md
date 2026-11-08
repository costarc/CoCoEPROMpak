# EEWRITE: write a ROM into the CoCoEPROMpak from the CoCo itself

EEWRITE burns a ROM image into the AT28C256 on the AT28C256 version of the
CoCoEPROMpak while the Pak sits in the CoCo's cartridge slot. No programmer, and
no taking the chip in and out. It is the CoCo counterpart of the MSX writer in
[AT28C256-Programmer-Z80](https://github.com/costarc/AT28C256-Programmer-Z80).

It works on the Tandy Color Computer 1 and 2 (32K or more), with Color BASIC or
Disk Extended Color BASIC. The CoCo 3 handles the cartridge area differently, so
it is untried there.

## What is here

| File | What it is |
|------|------------|
| `eewrite.asm` | The 6809 writer, in lwasm syntax. |
| `EEWRITE.BIN` | The writer, assembled, ready for `LOADM` / `CLOADM`. |
| `rom2coco.py` | Runs on the PC. Wraps a `.ROM` file as images the CoCo can load. |
| `tests/` | A tiny 6809 assembler, a model of a CoCo with a writable AT28C256 Pak, and the test script. |

## Before you start

- The Pak needs the **/OE modification**: chip pin 22 (/OE) cut away from /CTS and
  driven by an inverted R/W, so the chip can tell a read from a write.
- The chip must have **SDP (software data protection) switched off**. A chip last
  written by the MSX writer has it switched on, so unlock it first.
- Put the write jumper (JP3) on pins 1-2 (R/W) and **remove the autostart jumper
  (JP1) while writing**.

The hardware side is explained in Chapter 7 of the book (see the main README).

## How to use it

1. On the PC, wrap the ROM. A ROM of up to 16 KB gives one image (bank A, the
   low half of the chip). Up to 32 KB gives two (bank A and bank B).

        python3 rom2coco.py game.rom --writer EEWRITE.BIN

   For each image you get `GAMEA.BIN` (disk, `LOADM`), `GAMEA.CAS` (cassette
   image, for emulators such as XRoar) and `GAMEA.WAV` (the same cassette as
   sound, to play into a real CoCo). With `--writer` you also get `GAME.DSK`, a
   Disk BASIC floppy image holding the writer and the images.

2. On the CoCo:

        CLEAR 200,&H37FF
        LOADM "EEWRITE"
        LOADM "GAMEA"
        EXEC

   From cassette use `CLOADM` instead of `LOADM`.

The image sits in RAM at `$4000-$7EFF` and is copied to the Pak window at
`$C000-$FEFF` one 64-byte page at a time. Pages that already match are skipped,
and everything is verified afterwards. The top 256 bytes of each 16 KB half can't
be reached from the CoCo (`$FF00` upwards is I/O), so `rom2coco.py` keeps a small
label there and warns if your ROM has data in that range.

## Building the writer

    lwasm --decb -o EEWRITE.BIN eewrite.asm

`EEWRITE.BIN` in this folder was built with the small assembler in `tests/`, which
follows lwasm's rules. Rebuilding with lwasm (4.25 assembles it with no errors or
warnings) is still the safest choice.

## Tests

    python3 tests/test.py

Runs 16 checks against a simulator of a CoCo and an AT28C256 Pak: both banks,
skipping unchanged pages, a missing /OE mod, a chip with SDP on, a bad byte, a
Multi-Pak, verify-only, no image loaded and BREAK. It needs only Python 3 and
leaves its scratch files in a temporary folder.

## Status

- XRoar 1.6.6 (CoCo 2B, Disk Extended BASIC 1.1): the banner, image label, verify
  and the "did not finish a write" path behave as expected, BASIC is fine
  afterwards, and `CLOADM` works from both the `.CAS` and the `.WAV`.
- Real writes are tested only in the simulator, because no emulator models a
  writable AT28C256 Pak.
- **Not yet run on a real CoCo with a modified Pak.**

Roni Costa, 2026. GPL v3, like the original Pak by Mark J. Blair.
