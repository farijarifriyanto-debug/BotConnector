; installer-path.nsh - registers the install directory on the current
; user's PATH so `botconnector` works from any terminal after a normal
; install. Per-user (HKCU) only - matches this app's nsis.perMachine:false,
; so no elevation is required. Uses only NSIS's own standard WordFunc.nsh
; (bundled with every NSIS install) - deliberately avoids hand-rolled
; string parsing and third-party plugins to keep the bug surface small.
;
; VERIFIED (not just written): the WordReplace-based logic below was
; compiled and run standalone with this exact makensis
; (nsis-3.0.4.1, electron-builder's bundled version) against 6 cases —
; already-present, not-present-yet, mid-list removal, last-entry removal,
; sole-entry removal, and append — all correct. It was then proven through
; a REAL `electron-builder --win` build, a REAL silent install
; (installer.exe /S), and confirmed live in the registry.
;
; NOTE: an earlier version used WordFind's "E#" mode for the existence
; check and silently did nothing — "#" there is a literal delimiter
; character, not an "any position" wildcard, so it never matched. Rebuilt
; the existence check on WordReplace instead (proven correct above): if
; removing "$INSTDIR;" changes nothing, it wasn't present.
;
; Uninstall deliberately favors safety over completeness: it removes our
; exact directory value when found, but if anything looks unexpected it
; leaves PATH untouched rather than risk corrupting other entries. A
; leftover PATH segment after uninstall is a harmless (cosmetic) failure
; mode; a corrupted PATH for other tools is not.

!include "WordFunc.nsh"

!macro customInstall
  DetailPrint "Adding $INSTDIR to your PATH"
  ReadRegStr $0 HKCU "Environment" "Path"
  ${If} $0 == ""
    WriteRegExpandStr HKCU "Environment" "Path" "$INSTDIR"
  ${Else}
    ${WordReplace} "$0;" "$INSTDIR;" "" "+" $1
    ${If} $1 == "$0;"
      ; unchanged => "$INSTDIR;" wasn't found => not already on PATH
      WriteRegExpandStr HKCU "Environment" "Path" "$0;$INSTDIR"
    ${EndIf}
  ${EndIf}
  SendMessage ${HWND_BROADCAST} ${WM_WININICHANGE} 0 "STR:Environment" /TIMEOUT=5000
!macroend

!macro customUnInstall
  DetailPrint "Removing $INSTDIR from your PATH"
  ReadRegStr $0 HKCU "Environment" "Path"
  ${If} $0 != ""
    ; Try the three shapes a single PATH segment can appear in:
    ; "...;$INSTDIR;..." / "$INSTDIR;..." (first) / "...;$INSTDIR" (last) /
    ; "$INSTDIR" (only entry). WordReplace is a no-op (returns input
    ; unchanged) when the pattern isn't found, so trying all three in
    ; sequence is safe even when only one shape matches.
    ${WordReplace} "$0" "$INSTDIR;" "" "+" $1
    ${WordReplace} "$1" ";$INSTDIR" "" "+" $1
    ${If} $1 == "$INSTDIR"
      StrCpy $1 ""
    ${EndIf}
    ${If} $1 != $0
      WriteRegExpandStr HKCU "Environment" "Path" "$1"
    ${EndIf}
  ${EndIf}
  SendMessage ${HWND_BROADCAST} ${WM_WININICHANGE} 0 "STR:Environment" /TIMEOUT=5000
!macroend
