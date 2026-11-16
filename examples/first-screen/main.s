; first-screen: show three colour bands with a copper list, then stop.
;
; There are two example parts: the copper list (part 1) and the steps that
; start it (part 2). The context reports the checkpoint and holds the program.

; Custom chip registers, as offsets from CUSTOM.
CUSTOM   equ $dff000
DMACON   equ $096            ; DMA control (write)
COP1LC   equ $080            ; copper list 1 location (long)
COPJMP1  equ $088            ; a write restarts the copper at COP1LC
BPLCON0  equ $100            ; bitplane control 0
COLOR00  equ $180            ; colour register 0: the background

; exec.library offsets from ExecBase.
Forbid   equ -132

; --- CONTEXT: the checkpoint block that scripts/amiga.py reads (for the check only)
CHECK    equ $100
MAGIC    equ "CHKP"

        section code,CODE
start:
; >>> EXAMPLE 2 of 2: stop the system changing the display, then start the list
        move.l  4.w,a6
        jsr     Forbid(a6)          ; no other task can load a new display
        lea     CUSTOM,a5
        move.w  #$0020,DMACON(a5)   ; clear SPREN: no sprites, so no pointer
        lea     copper,a0
    ifnd COPPER_OFF
        move.l  a0,COP1LC(a5)       ; the copper restarts here at each frame
        move.w  d0,COPJMP1(a5)      ; and at once, for this frame
    endif
; <<< END EXAMPLE

; --- CONTEXT: report checkpoint 1 with the list's address, then hold (for the check only)
    ifnd NO_CHECKPOINT
        move.l  #1,CHECK+4.w
        move.l  a0,CHECK+8.w
        move.l  #MAGIC,CHECK.w
    endif
.hold:  bra.s   .hold

; The copper reads its list with DMA, so the list must be in chip RAM.
        section copper,DATA_C
; >>> EXAMPLE 1 of 2: a copper list that sets the background on three bands of lines
copper:
        dc.w    BPLCON0,$0200       ; no bitplanes; colour output on
        dc.w    COLOR00,$000f       ; blue from the top of the frame
        dc.w    $6007,$fffe         ; wait for line $60
        dc.w    COLOR00,$0fff       ; white
        dc.w    $a007,$fffe         ; wait for line $a0
    ifnd WRONG_COLOUR
        dc.w    COLOR00,$0f80       ; orange to the bottom of the frame
    else
        dc.w    COLOR00,$00f0       ; failure control: green instead of orange
    endif
        dc.w    $ffff,$fffe         ; wait for a line that never comes: end of list
; <<< END EXAMPLE
