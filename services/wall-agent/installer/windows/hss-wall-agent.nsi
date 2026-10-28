; HSS Wall Agent installer for Windows wall PCs (NSIS, zlib licence).
;
; Interactive:  hss-wall-agent-setup.exe
; Silent:       hss-wall-agent-setup.exe /S /PLATFORM=https://hss.example.local /NODE=wall-pc-1
;                   /TOKEN=... [/BROWSER="C:\Program Files\Chromium\Application\chrome.exe"]
;                   [/CAFILE=\\server\share\hss-root-ca.crt]
; The agent runs in the signed-in user's session (a Windows service cannot show windows), started
; at sign-in by the "HSS Wall Agent" scheduled task, which also restarts it within a minute.

Unicode true
!include "MUI2.nsh"
!include "nsDialogs.nsh"
!include "FileFunc.nsh"
!include "WordFunc.nsh"
!include "LogicLib.nsh"
!include "x64.nsh"

!ifndef VERSION
  !define VERSION "0.0.0"
!endif
!ifndef AGENT_EXE
  !define AGENT_EXE "..\..\..\..\dist\wall-agent\hss-wall-agent-${VERSION}-windows-amd64.exe"
!endif
!ifndef OUTFILE
  !define OUTFILE "..\..\..\..\dist\wall-agent\hss-wall-agent-setup-${VERSION}.exe"
!endif

!define APPNAME "HSS Wall Agent"
!define TASKNAME "HSS Wall Agent"
!define UNINSTKEY "Software\Microsoft\Windows\CurrentVersion\Uninstall\HSSWallAgent"

Name "${APPNAME} ${VERSION}"
OutFile "${OUTFILE}"
RequestExecutionLevel admin
ShowInstDetails show

Var Platform
Var Node
Var Token
Var Browser
Var CAFile
Var PlatformField
Var NodeField
Var TokenField

!insertmacro MUI_PAGE_WELCOME
Page custom SettingsPage SettingsPageLeave
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "English"

Function .onInit
  ${IfNot} ${RunningX64}
    MessageBox MB_ICONSTOP "The HSS Wall Agent needs 64-bit Windows." /SD IDOK
    Abort
  ${EndIf}
  SetShellVarContext all
  StrCpy $INSTDIR "$APPDATA\HSS\WallAgent" ; $APPDATA is C:\ProgramData in the "all users" context
  ${GetParameters} $R0
  ${GetOptions} $R0 "/PLATFORM=" $Platform
  ${GetOptions} $R0 "/NODE=" $Node
  ${GetOptions} $R0 "/TOKEN=" $Token
  ${GetOptions} $R0 "/BROWSER=" $Browser
  ${GetOptions} $R0 "/CAFILE=" $CAFile
  ; Keep the settings of an earlier install when none are given.
  ${If} $Platform == ""
  ${AndIf} ${FileExists} "$INSTDIR\config.json"
    StrCpy $R9 "keep"
  ${EndIf}
  ${If} ${Silent}
  ${AndIf} $R9 != "keep"
    ${If} $Platform == ""
    ${OrIf} $Node == ""
    ${OrIf} $Token == ""
      SetErrorLevel 2
      Abort
    ${EndIf}
  ${EndIf}
FunctionEnd

Function SettingsPage
  ${If} $R9 == "keep"
    Abort ; existing settings are kept; skip this page
  ${EndIf}
  !insertmacro MUI_HEADER_TEXT "Wall settings" "Where is the platform, and what is this wall PC called?"
  nsDialogs::Create 1018
  Pop $0
  ${NSD_CreateLabel} 0 0 100% 12u "Platform address (for example https://hss.example.local):"
  ${NSD_CreateText} 0 13u 100% 12u "$Platform"
  Pop $PlatformField
  ${NSD_CreateLabel} 0 32u 100% 12u "Wall PC name (letters, digits, dot, dash; for example wall-pc-1):"
  ${NSD_CreateText} 0 45u 100% 12u "$Node"
  Pop $NodeField
  ${NSD_CreateLabel} 0 64u 100% 12u "Wall token (from the platform administrator):"
  ${NSD_CreatePassword} 0 77u 100% 12u "$Token"
  Pop $TokenField
  nsDialogs::Show
FunctionEnd

Function SettingsPageLeave
  ${NSD_GetText} $PlatformField $Platform
  ${NSD_GetText} $NodeField $Node
  ${NSD_GetText} $TokenField $Token
  ${If} $Platform == ""
  ${OrIf} $Node == ""
  ${OrIf} $Token == ""
    MessageBox MB_ICONEXCLAMATION "Please fill in all three fields."
    Abort
  ${EndIf}
FunctionEnd

; Values go into JSON, so refuse quotes and escape backslashes.
!macro JsonValue VAR
  ${WordFind} "${VAR}" '"' "E+1" $R1
  ${IfNot} ${Errors}
    MessageBox MB_ICONSTOP 'Settings must not contain the " character.' /SD IDOK
    SetErrorLevel 2
    Abort
  ${EndIf}
  ${WordReplace} "${VAR}" "\" "\\" "+" ${VAR}
!macroend

Section "Install"
  SetShellVarContext all
  ; Stop a running agent (and its browsers) before replacing files.
  nsExec::Exec 'schtasks /End /TN "${TASKNAME}"'
  nsExec::Exec 'taskkill /F /IM hss-wall-agent.exe'
  Sleep 1000

  SetOutPath "$INSTDIR\bin"
  File "/oname=hss-wall-agent.exe" "${AGENT_EXE}"
  ; The agent runs as the signed-in user and replaces itself on update, so users may write here.
  nsExec::ExecToLog 'icacls "$INSTDIR\bin" /grant *S-1-5-32-545:(OI)(CI)M'

  ${If} $R9 != "keep"
    SetOutPath "$INSTDIR"
    StrCpy $R2 ""
    ${If} $CAFile != ""
      CopyFiles /SILENT "$CAFile" "$INSTDIR\platform-ca.crt"
      StrCpy $R2 "$INSTDIR\platform-ca.crt"
    ${EndIf}
    !insertmacro JsonValue $Platform
    !insertmacro JsonValue $Node
    !insertmacro JsonValue $Token
    !insertmacro JsonValue $Browser
    !insertmacro JsonValue $R2
    FileOpen $0 "$INSTDIR\config.json" w
    FileWrite $0 '{$\r$\n'
    FileWrite $0 '  "platform_url": "$Platform",$\r$\n'
    FileWrite $0 '  "node_id": "$Node",$\r$\n'
    FileWrite $0 '  "token": "$Token",$\r$\n'
    FileWrite $0 '  "browser": "$Browser",$\r$\n'
    FileWrite $0 '  "ca_file": "$R2"$\r$\n'
    FileWrite $0 '}$\r$\n'
    FileClose $0
    ; Only administrators may change the settings; users (the agent) may read them.
    nsExec::ExecToLog 'icacls "$INSTDIR\config.json" /inheritance:r /grant *S-1-5-32-544:F /grant *S-1-5-18:F /grant *S-1-5-32-545:R'
  ${EndIf}

  ; Scheduled task: start at sign-in, check every minute, restart if it stops.
  InitPluginsDir
  File "/oname=$PLUGINSDIR\task.xml" "task-utf16.xml"
  nsExec::ExecToLog 'schtasks /Create /TN "${TASKNAME}" /XML "$PLUGINSDIR\task.xml" /F'
  Pop $0
  ${If} $0 != 0
    MessageBox MB_ICONSTOP "Could not create the scheduled task (error $0)." /SD IDOK
    SetErrorLevel 3
    Abort
  ${EndIf}

  WriteUninstaller "$INSTDIR\uninstall.exe"
  WriteRegStr HKLM "${UNINSTKEY}" "DisplayName" "${APPNAME}"
  WriteRegStr HKLM "${UNINSTKEY}" "DisplayVersion" "${VERSION}"
  WriteRegStr HKLM "${UNINSTKEY}" "Publisher" "HSS project"
  WriteRegStr HKLM "${UNINSTKEY}" "UninstallString" '"$INSTDIR\uninstall.exe"'
  WriteRegStr HKLM "${UNINSTKEY}" "QuietUninstallString" '"$INSTDIR\uninstall.exe" /S'
  WriteRegDWORD HKLM "${UNINSTKEY}" "NoModify" 1
  WriteRegDWORD HKLM "${UNINSTKEY}" "NoRepair" 1

  ; Start now if someone is signed in; otherwise it starts at the next sign-in.
  nsExec::Exec 'schtasks /Run /TN "${TASKNAME}"'
SectionEnd

Function un.onInit
  SetShellVarContext all
FunctionEnd

Section "Uninstall"
  SetShellVarContext all
  nsExec::Exec 'schtasks /End /TN "${TASKNAME}"'
  nsExec::Exec 'schtasks /Delete /TN "${TASKNAME}" /F'
  nsExec::Exec 'taskkill /F /IM hss-wall-agent.exe'
  Sleep 1000
  Delete "$INSTDIR\bin\hss-wall-agent.exe"
  Delete "$INSTDIR\bin\hss-wall-agent.exe.old"
  RMDir "$INSTDIR\bin"
  Delete "$INSTDIR\config.json"
  Delete "$INSTDIR\platform-ca.crt"
  Delete "$INSTDIR\uninstall.exe"
  RMDir "$INSTDIR"
  DeleteRegKey HKLM "${UNINSTKEY}"
  ; Browser profiles and logs in each user's %LOCALAPPDATA%\HSS\WallAgent are left in place.
SectionEnd
