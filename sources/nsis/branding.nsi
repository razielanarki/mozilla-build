!include MUI.nsh

!define AB_CD                 "@AB_CD@"

!define MUI_ABORTWARNING

!define MUI_ICON "..\setup.ico"
!define MUI_UNICON "..\setup.ico"

!define MUI_WELCOMEPAGE_TITLE_3LINES
!define MUI_WELCOMEFINISHPAGE_BITMAP wizWatermark.bmp

!define MUI_HEADERIMAGE
!define MUI_HEADERIMAGE_RIGHT

; By default MUI_BGCOLOR is hardcoded to FFFFFF, which is only correct if the
; Windows theme or high-contrast mode hasn't changed it, so we need to
; override that with GetSysColor(COLOR_WINDOW) (this string ends up getting
; passed to SetCtlColors, which uses this custom syntax to mean that).
!define MUI_BGCOLOR SYSCLR:WINDOW

; Use a right to left header image when the language is right to left
!ifdef ${AB_CD}_rtl
!define MUI_HEADERIMAGE_BITMAP_RTL wizHeaderRTL.bmp
!else
!define MUI_HEADERIMAGE_BITMAP wizHeader.bmp
!endif

/** Installation Pages */
; Welcome Page
!define MUI_PAGE_CUSTOMFUNCTION_PRE preWelcome
!define MUI_PAGE_CUSTOMFUNCTION_SHOW showWelcome
!define MUI_PAGE_CUSTOMFUNCTION_LEAVE leaveWelcome
!insertmacro MUI_PAGE_WELCOME

!insertmacro MUI_PAGE_LICENSE "${LICENSEDATA}"

; Select Install Directory Page
!define MUI_PAGE_CUSTOMFUNCTION_PRE preDirectory
!define MUI_PAGE_CUSTOMFUNCTION_LEAVE leaveDirectory
!define MUI_DIRECTORYPAGE_VERIFYONLEAVE
!insertmacro MUI_PAGE_DIRECTORY

; Install Files Page
!insertmacro MUI_PAGE_INSTFILES

; Finish Page
!define MUI_FINISHPAGE_TITLE_3LINES
!define MUI_FINISHPAGE_RUN
!define MUI_FINISHPAGE_RUN_FUNCTION LaunchApp
!define MUI_FINISHPAGE_RUN_TEXT $(LAUNCH_TEXT)
!define MUI_PAGE_CUSTOMFUNCTION_PRE preFinish
!define MUI_PAGE_CUSTOMFUNCTION_SHOW showFinish
!define MUI_PAGE_CUSTOMFUNCTION_LEAVE postFinish
!insertmacro MUI_PAGE_FINISH

################################################################################
# Installer Sections

Section "Dummy Section" SecDummy
  SetOutPath "$INSTDIR"
  WriteUninstaller "$INSTDIR\Uninstall.exe"
SectionEnd

Section "Uninstall"
  Delete "$INSTDIR\Uninstall.exe"
  RMDir "$INSTDIR"
SectionEnd

################################################################################
# Page pre, show, and leave functions

Function preWelcome
  StrCpy $PageName "Welcome"
  ${If} ${FileExists} "$EXEDIR\core\distribution\modern-wizard.bmp"
    Delete "$PLUGINSDIR\modern-wizard.bmp"
    CopyFiles /SILENT "$EXEDIR\core\distribution\modern-wizard.bmp" "$PLUGINSDIR\modern-wizard.bmp"
  ${EndIf}

  ; We don't want the header bitmap showing on the welcome page.
  GetDlgItem $0 $HWNDPARENT 1046
  ShowWindow $0 ${SW_HIDE}

  System::Call "kernel32::GetTickCount()l .s"
  Pop $IntroPhaseStart
FunctionEnd

Function showWelcome
  ; The welcome and finish pages don't get the correct colors for their labels
  ; like the other pages do, presumably because they're built by filling in an
  ; InstallOptions .ini file instead of from a dialog resource like the others.
  ; Field 2 is the header and Field 3 is the body text.
  ReadINIStr $0 "$PLUGINSDIR\ioSpecial.ini" "Field 2" "HWND"
  SetCtlColors $0 SYSCLR:WINDOWTEXT SYSCLR:WINDOW
  ReadINIStr $0 "$PLUGINSDIR\ioSpecial.ini" "Field 3" "HWND"
  SetCtlColors $0 SYSCLR:WINDOWTEXT SYSCLR:WINDOW

  ; We need to overwrite the sidebar image so that we get it drawn with proper
  ; scaling if the display is scaled at anything above 100%.
  ${ChangeMUISidebarImage} "$PLUGINSDIR\modern-wizard.bmp"
FunctionEnd

Function leaveWelcome
  ; Bring back the header bitmap for the next pages.
  GetDlgItem $0 $HWNDPARENT 1046
  ShowWindow $0 ${SW_SHOW}
FunctionEnd

Function preDirectory
  StrCpy $PageName "Directory"
  ${PreDirectoryCommon}

  StrCpy $DefaultInstDir $INSTDIR
FunctionEnd

Function leaveDirectory
  ${If} $InstallType == ${INSTALLTYPE_BASIC}
    Call CheckExistingInstall
  ${EndIf}
  ${LeaveDirectoryCommon} "$(WARN_DISK_SPACE)" "$(WARN_WRITE_ACCESS)"
FunctionEnd

; When we add an optional action to the finish page the cancel button is
; enabled. This disables it and leaves the finish button as the only choice.
Function preFinish
  System::Call "kernel32::GetTickCount()l .s"
  Pop $FinishPhaseStart

  StrCpy $PageName ""
  ${EndInstallLog} "${BrandFullName}"
  !insertmacro MUI_INSTALLOPTIONS_WRITE "ioSpecial.ini" "settings" "cancelenabled" "0"

  ; We don't want the header bitmap showing on the finish page.
  GetDlgItem $0 $HWNDPARENT 1046
  ShowWindow $0 ${SW_HIDE}
FunctionEnd

Function showFinish
  ReadINIStr $0 "$PLUGINSDIR\ioSpecial.ini" "Field 2" "HWND"
  SetCtlColors $0 SYSCLR:WINDOWTEXT SYSCLR:WINDOW

  ReadINIStr $0 "$PLUGINSDIR\ioSpecial.ini" "Field 3" "HWND"
  SetCtlColors $0 SYSCLR:WINDOWTEXT SYSCLR:WINDOW

  ; We need to overwrite the sidebar image so that we get it drawn with proper
  ; scaling if the display is scaled at anything above 100%.
  ${ChangeMUISidebarImage} "$PLUGINSDIR\modern-wizard.bmp"

  ; Field 4 is the launch checkbox. Since it's a checkbox, we need to
  ; clear the theme from it before we can set its background color.
  ReadINIStr $0 "$PLUGINSDIR\ioSpecial.ini" "Field 4" "HWND"
  System::Call 'uxtheme::SetWindowTheme(i $0, w " ", w " ")'
  SetCtlColors $0 SYSCLR:WINDOWTEXT SYSCLR:WINDOW
FunctionEnd

Function postFinish
  System::Call "kernel32::GetTickCount()l .s"
  Pop $FinishPhaseEnd
FunctionEnd