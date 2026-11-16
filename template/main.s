; Project name: replace this line with one sentence about the program.
;
; This starting program reports checkpoint 1 and returns to AmigaDOS.
; Replace it with your program. Keep the checkpoint report, or move it to
; the point where your program has done the work that the check compares.

; --- CONTEXT: the checkpoint block that scripts/amiga.py reads (for the check only)
CHECK    equ $100
MAGIC    equ "CHKP"

        section code,CODE
start:
        move.l  #1,CHECK+4.w        ; the checkpoint number
        clr.l   CHECK+8.w           ; an address for the check to read; none yet
        move.l  #MAGIC,CHECK.w      ; write the magic last
        moveq   #0,d0               ; return code 0 to AmigaDOS
        rts
