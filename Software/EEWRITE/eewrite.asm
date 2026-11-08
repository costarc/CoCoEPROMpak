; ---------------------------------------------------------------
; EEWRITE  -  write a ROM image into the AT28C256 on a CoCoEPROMpak
;
; For the Tandy Color Computer 1 and 2 (32K or 64K), Color BASIC
; or Disk Extended Color BASIC.
;
; The Pak needs the /OE modification described in the book:
; chip pin 22 (/OE) cut away from /CTS and driven by an inverted
; R/W, so the chip can tell a read from a write.
; The write-enable jumper (JP3) must be on pins 1-2 (R/W) and the
; autostart jumper (JP1) must be removed while writing.
;
; How to use it:
;   CLEAR 200,&H37FF
;   LOADM "EEWRITE"          (or CLOADM from cassette)
;   LOADM "GAME_A"           (an image made by rom2coco.py)
;   EXEC
;
; The image sits in RAM at $4000-$7EFF and is copied to the Pak
; window at $C000-$FEFF. The top 256 bytes of each 16 KB bank
; can't be reached from the CoCo ($FF00 is where the I/O lives),
; so rom2coco.py keeps a small label there instead.
;
; Assemble with lwtools:
;   lwasm --decb -o EEWRITE.BIN eewrite.asm
;
; Roni Costa, 2026. GPL v3, like the original Pak by Mark J. Blair.
; ---------------------------------------------------------------

POLCAT  equ     $A000           ; ROM vector: read the keyboard
CHROUT  equ     $A002           ; ROM vector: print the char in A
CURPOS  equ     $0088           ; BASIC's cursor address on screen
MPIREG  equ     $FF7F           ; Multi-Pak slot select register

BUFFER  equ     $4000           ; where the ROM image waits in RAM
CART    equ     $C000           ; start of the Pak window
CARTEND equ     $FF00           ; first address we must NOT touch
LABEL   equ     $7F00           ; image label written by rom2coco.py
PAGE    equ     64              ; AT28C256 page size in bytes

        org     $3800

start   ldx     #msg_title
        jsr     print
        lbsr    checkimg        ; is there an image in RAM?
        lbne    quit
        lbsr    askslots        ; Multi-Pak or not?

menu    ldx     #msg_menu
        jsr     print
menukey jsr     getkey
        cmpa    #3              ; BREAK
        lbeq    quit
        cmpa    #'V
        beq     doverify
        cmpa    #'W
        bne     menukey

; ----- write ----------------------------------------------------
        ldx     #msg_writing
        jsr     print
        lbsr    writeall
        tst     timeout
        beq     wr_ok
        ldx     #msg_timeout    ; the chip never finished a write
        jsr     print
        ldd     failaddr
        lbsr    phexd
        ldx     #msg_check
        jsr     print
        bra     quit
wr_ok   ldx     #msg_pages
        jsr     print
        ldd     written
        lbsr    pdec
        lda     #13
        jsr     [CHROUT]

; ----- verify ---------------------------------------------------
doverify
        ldx     #msg_verify
        jsr     print
        lbsr    verifyall
        ldd     bad
        bne     vbad
        ldx     #msg_match
        jsr     print
        bra     quit
vbad    lda     #13             ; the count goes on a new line
        jsr     [CHROUT]
        ldd     bad
        lbsr    pdec
        ldx     #msg_differ
        jsr     print
        ldd     firstbad
        lbsr    phexd
        lda     #13
        jsr     [CHROUT]
quit    rts                     ; back to BASIC

; ---------------------------------------------------------------
; checkimg: look for the "EEIMG1" label at $7F00 and show its name.
; Returns Z set if an image is there.
; ---------------------------------------------------------------
checkimg
        ldx     #LABEL
        ldy     #sig
ck1     lda     ,y+
        beq     ck_ok
        cmpa    ,x+
        beq     ck1
        ldx     #msg_noimg
        jsr     print
        lda     #1              ; clear Z: no image
        rts
ck_ok   ldx     #msg_image
        jsr     print
        ldx     #LABEL+8        ; the name, ends with a 0
        jsr     print
        ldx     #msg_bank
        jsr     print
        lda     LABEL+6         ; 'A' (low half) or 'B' (high half)
        jsr     [CHROUT]
        lda     #13
        jsr     [CHROUT]
        clra                    ; set Z: image found
        rts

; ---------------------------------------------------------------
; askslots: find out whether a Multi-Pak is in use, and which
; slots hold the EEPROM Pak and the disk controller.
; ---------------------------------------------------------------
askslots
        clr     usempi
        ldx     #msg_mpi
        jsr     print
as1     jsr     getkey
        cmpa    #13             ; ENTER: no Multi-Pak
        beq     as_none
        lbsr    isslot
        bne     as1
        jsr     [CHROUT]
        suba    #'1
        sta     pakslot
        ldx     #msg_disk
        jsr     print
as2     jsr     getkey
        lbsr    isslot
        bne     as2
        jsr     [CHROUT]
        suba    #'1             ; A = disk slot, 0 to 3
        sta     mpihome
        lsla                    ; home: CTS and SCS both on the disk
        lsla
        lsla
        lsla
        ora     mpihome
        sta     mpihome
        lda     pakslot         ; pak: CTS on the Pak, SCS on the disk
        lsla
        lsla
        lsla
        lsla
        sta     mpipak
        lda     mpihome
        anda    #$03
        ora     mpipak
        sta     mpipak
        inc     usempi
        lda     #13
        jmp     [CHROUT]
as_none ldx     #msg_nompi
        jmp     print

; Z set if A holds '1' to '4'
isslot  cmpa    #'1
        blo     is_no
        cmpa    #'4
        bhi     is_no
        orcc    #$04            ; set Z
        rts
is_no   andcc   #$FB            ; clear Z
        rts

; ---------------------------------------------------------------
; writeall: copy BUFFER to the Pak, one 64-byte page at a time.
; Pages that already match are skipped, which saves time and wear.
; Interrupts are off for the whole job: the chip wants the bytes
; of a page less than 150 microseconds apart, and with a Multi-Pak
; the Disk BASIC ROM is switched out while we work.
; ---------------------------------------------------------------
writeall
        orcc    #$50            ; no IRQ, no FIRQ
        lbsr    selpak
        clr     timeout
        ldd     #0
        std     written
        ldu     #BUFFER         ; U = source in RAM
        ldy     #CART           ; Y = destination in the Pak
wpage   pshs    u,y             ; does this page need writing?
        ldb     #PAGE
wcmp    lda     ,u+
        cmpa    ,y+
        bne     wneed
        decb
        bne     wcmp
        puls    u,y             ; it matches: skip it
        leau    PAGE,u
        leay    PAGE,y
        bra     wmark
wneed   puls    u,y
        ldb     #PAGE           ; load the page: 64 quick writes
wload   lda     ,u+
        sta     ,y+
        decb
        bne     wload
; Data polling: while the chip is busy, reading the last byte gives
; back bit 7 upside down. When it reads back right, the write is done.
        lda     -1,u            ; the last byte we wrote
        ldx     #0              ; give up after 65536 tries (~1 s)
wpoll   cmpa    -1,y
        beq     wdone
        leax    -1,x
        bne     wpoll
        leay    -PAGE,y         ; timed out: remember where
        sty     failaddr
        inc     timeout
        bra     wexit
wdone   cmpa    -1,y            ; read once more, to be sure
        bne     wpoll
        ldd     written
        addd    #1
        std     written
wmark   tfr     y,d             ; every 512 bytes, put a * on screen
        tstb
        bne     wnext
        bita    #1
        bne     wnext
        ldx     CURPOS
        lda     #'*+$40         ; screen code for a green '*'
        sta     ,x+
        stx     CURPOS
wnext   cmpy    #CARTEND
        blo     wpage
wexit   lbsr    selhome
        andcc   #$AF            ; interrupts back on
        lda     CURPOS+1        ; new line, unless we're already at the start of one
        anda    #$1F
        beq     wx_rts
        lda     #13
        jmp     [CHROUT]
wx_rts  rts

; ---------------------------------------------------------------
; verifyall: compare the Pak with BUFFER, count the bad bytes.
; ---------------------------------------------------------------
verifyall
        orcc    #$50
        lbsr    selpak
        ldu     #BUFFER
        ldy     #CART
        ldx     #0              ; X = bad byte count
vloop   lda     ,u+
        cmpa    ,y+
        beq     vnext
        leax    1,x
        cmpx    #1
        bne     vnext
        leay    -1,y            ; first bad one: remember where
        sty     firstbad
        leay    1,y
vnext   cmpy    #CARTEND
        blo     vloop
        stx     bad
        lbsr    selhome
        andcc   #$AF
        rts

; ----- Multi-Pak switching -------------------------------------
selpak  tst     usempi
        beq     sel_rts
        lda     mpipak
        sta     MPIREG
sel_rts rts
selhome tst     usempi
        beq     sel_rts
        lda     mpihome
        sta     MPIREG
        rts

; ----- small helpers -------------------------------------------
getkey  jsr     [POLCAT]        ; wait for a key, return it in A
        beq     getkey
        rts

print   lda     ,x+             ; print the text at X, up to a 0
        beq     pr_end
        jsr     [CHROUT]
        bra     print
pr_end  rts

phexd   pshs    b               ; print D as $XXXX
        pshs    a
        lda     #'$
        jsr     [CHROUT]
        puls    a
        bsr     phexa
        puls    a
phexa   pshs    a               ; print A as two hex digits
        lsra
        lsra
        lsra
        lsra
        bsr     phexn
        puls    a
        anda    #$0F
phexn   adda    #'0
        cmpa    #'9
        bls     phexo
        adda    #7
phexo   jmp     [CHROUT]

pdec    std     num             ; print D in decimal
        ldx     #tens
        clr     started
pd1     lda     #'0
        sta     digit
        ldd     num
pd2     subd    ,x              ; count how many times it fits
        blo     pd3
        std     num
        inc     digit
        bra     pd2
pd3     lda     digit
        cmpx    #tens+8         ; always print the last digit
        beq     pd4
        tst     started         ; skip leading zeros
        bne     pd4
        cmpa    #'0
        beq     pd5
pd4     inc     started
        jsr     [CHROUT]
pd5     leax    2,x
        cmpx    #tens+10
        blo     pd1
        rts
tens    fdb     10000,1000,100,10,1

; ----- text ----------------------------------------------------
sig         fcc     "EEIMG1"
            fcb     0
msg_title   fcc     "EEWRITE 1.0 - AT28C256 WRITER"
            fcb     13
            fcc     "FOR THE COCOEPROMPAK (OE MOD)"
            fcb     13,13,0
msg_noimg   fcc     "NO ROM IMAGE AT $4000. LOADM AN"
            fcb     13
            fcc     "IMAGE MADE BY ROM2COCO FIRST."
            fcb     13,0
msg_image   fcc     "IMAGE: "
            fcb     0
msg_bank    fcc     " BANK "
            fcb     0
msg_mpi     fcc     "MULTI-PAK SLOT OF EEPROM PAK"
            fcb     13
            fcc     "(1-4, OR ENTER IF NONE)? "
            fcb     0
msg_disk    fcb     13
            fcc     "DISK CONTROLLER SLOT (1-4)? "
            fcb     0
msg_nompi   fcb     13
            fcc     "NO MULTI-PAK"
            fcb     13,0
msg_menu    fcb     13
            fcc     "CHECK: AUTOSTART JUMPER OFF,"
            fcb     13
            fcc     "WRITE JUMPER ON R/W (1-2)."
            fcb     13
            fcc     "W=WRITE V=VERIFY BREAK=QUIT"
            fcb     13,0
msg_writing fcc     "WRITING"
            fcb     13,0
msg_pages   fcc     "PAGES WRITTEN: "
            fcb     0
msg_verify  fcc     "VERIFYING... "
            fcb     0
msg_match   fcc     "ALL OK!"
            fcb     13,0
msg_differ  fcc     " BYTES DIFFER,"
            fcb     13
            fcc     "FIRST AT "
            fcb     0
msg_timeout fcc     "THE CHIP DID NOT FINISH A"
            fcb     13
            fcc     "WRITE AT "
            fcb     0
msg_check   fcb     13
            fcc     "CHECK THE OE MOD, THE WRITE"
            fcb     13
            fcc     "JUMPER, AND THAT SDP IS OFF."
            fcb     13,0

; ----- variables -----------------------------------------------
usempi      rmb     1
pakslot     rmb     1
mpipak      rmb     1
mpihome     rmb     1
timeout     rmb     1
written     rmb     2
failaddr    rmb     2
bad         rmb     2
firstbad    rmb     2
num         rmb     2
digit       rmb     1
started     rmb     1

            end     start
