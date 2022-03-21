;----------------------------------------------------------------------------
; Includes

  !include LogicLib.nsh
  !include WinVer.nsh
  !include x64.nsh
  !include helpers.nsi
  !include MUI2.nsh

;----------------------------------------------------------------------------
; Defines

  !define NAME "MozillaBuild"
  !define VERSION @VERSION@
  !define INSTDIR_DEFAULT "C:\mozilla-build"

  !cd mozilla-build
  !define DATADIR ".."

  !define ICON "${DATADIR}\setup.ico"
  !define LICENSEDATA "${DATADIR}\license.rtf"

  !define OUTFILE "${DATADIR}\${NAME}Setup${VERSION}.exe"

;----------------------------------------------------------------------------
; General

  Name "${NAME} ${VERSION}"
  Icon "${ICON}"

  ManifestSupportedOS Win7
  ManifestLongPathAware true
  RequestExecutionLevel highest

  Unicode true
  SetCompressor /SOLID lzma

  ShowInstDetails show
  OutFile "${OUTFILE}"

;--------------------------------
;Interface Settings

  !define MUI_ICON "${ICON}"
  !define MUI_WELCOMEFINISHPAGE_BITMAP "${DATADIR}\mozillabuild.bmp"
  !define MUI_FINISHPAGE_NOAUTOCLOSE
  !define MUI_ABORTWARNING

;--------------------------------
; Pages

  !insertmacro MUI_PAGE_WELCOME
  !insertmacro MUI_PAGE_LICENSE "${LICENSEDATA}"
  !insertmacro MUI_PAGE_DIRECTORY
  !insertmacro MUI_PAGE_INSTFILES
  !insertmacro MUI_PAGE_FINISH

;--------------------------------
;Languages

  !insertmacro MUI_LANGUAGE "English"

;----------------------------------------------------------------------------
; Check for Win7x64

Function .onInit
${IfNot} ${RunningX64}
${OrIfNot} ${AtLeastWin7}
  MessageBox MB_OK|MB_ICONSTOP "${NAME} ${VERSION} requires 64-bit Windows 7+."
  Quit
${EndIf}

; Install to a unique directory by default if this is a test build.
${StrContains} $0 "pre" ${VERSION}
${If} "$0" == ""
  StrCpy $INSTDIR ${INSTDIR_DEFAULT}
${Else}
  StrCpy $INSTDIR "${INSTDIR_DEFAULT}-${VERSION}"
${EndIf}
FunctionEnd

;--------------------------------
;Installer

Section "Installer"
  IfSilent continue
  MessageBox MB_YESNO|MB_ICONQUESTION "Previous installations in $INSTDIR will be overwritten (user-created files will be preserved). Do you want to continue?" /SD IDYES IDYES continue
  SetErrors
  return

continue:
  SetOutPath $INSTDIR
  Delete "$INSTDIR\guess-msvc.bat"
  Delete "$INSTDIR\start-l10n.bat"
  Delete "$INSTDIR\start-msvc71.bat"
  Delete "$INSTDIR\start-msvc8.bat"
  Delete "$INSTDIR\start-msvc8-x64.bat"
  Delete "$INSTDIR\start-msvc9.bat"
  Delete "$INSTDIR\start-msvc9-x64.bat"
  Delete "$INSTDIR\start-msvc10.bat"
  Delete "$INSTDIR\start-msvc10-x64.bat"
  Delete "$INSTDIR\start-msvc11.bat"
  Delete "$INSTDIR\start-msvc11-x64.bat"
  Delete "$INSTDIR\start-msvc12.bat"
  Delete "$INSTDIR\start-msvc12-x64.bat"
  Delete "$INSTDIR\start-shell-l10n.bat"
  Delete "$INSTDIR\start-shell-msvc2010.bat"
  Delete "$INSTDIR\start-shell-msvc2010-x64.bat"
  Delete "$INSTDIR\start-shell-msvc2012.bat"
  Delete "$INSTDIR\start-shell-msvc2012-x64.bat"
  Delete "$INSTDIR\start-shell-msvc2013.bat"
  Delete "$INSTDIR\start-shell-msvc2013-x64.bat"
  Delete "$INSTDIR\start-shell-msvc2015.bat"
  Delete "$INSTDIR\start-shell-msvc2015-x64.bat"
  Delete "$INSTDIR\bin\mozmake.exe"
  Delete "$INSTDIR\moztools\bin\gmake.exe"
  Delete "$INSTDIR\moztools\bin\shmsdos.exe"
  Delete "$INSTDIR\moztools\bin\uname.exe"
  RMDir /r "$INSTDIR\7zip"
  RMDir /r "$INSTDIR\atlthunk_compat"
  RMDir /r "$INSTDIR\bin\upx394w"
  RMDir /r "$INSTDIR\bin\wget-1.19.4"
  RMDir /r "$INSTDIR\blat261"
  RMDir /r "$INSTDIR\emacs-24.2"
  RMDir /r "$INSTDIR\emacs-24.3"
  RMDir /r "$INSTDIR\hg"
  RMDir /r "$INSTDIR\info-zip"
  RMDir /r "$INSTDIR\mozmake"
  RMDir /r "$INSTDIR\moztools"
  RMDir /r "$INSTDIR\moztools-x64"
  RMDir /r "$INSTDIR\msys\lib\perl5\site_perl\5.6.1\msys"
  RMDir /r "$INSTDIR\node-v8.9.1-win-x64"
  RMDir /r "$INSTDIR\node-v8.11.1-win-x64"
  RMDir /r "$INSTDIR\nsis-2.33u"
  RMDir /r "$INSTDIR\nsis-2.46u"
  RMDir /r "$INSTDIR\nsis-3.0b1"
  RMDir /r "$INSTDIR\nsis-3.0b3"
  RMDir /r "$INSTDIR\nsis-3.01"
  RMDir /r "$INSTDIR\upx203w"
  RMDir /r "$INSTDIR\upx391w"
  RMDir /r "$INSTDIR\upx394w"
  RMDir /r "$INSTDIR\watchman"
  RMDir /r "$INSTDIR\wget"
  RMDir /r "$INSTDIR\wix-351728"
  RMDir /r "$INSTDIR\yasm"
  File /r *.*
SectionEnd
