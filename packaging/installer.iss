; Inno-Setup-Skript für OCRDMS
; Bauen: "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" packaging\installer.iss
; Voraussetzung: dist\OCRDMS (PyInstaller-Build). Am einfachsten über packaginguild.ps1.
; Stilles Update (wie von der Update-Funktion verwendet): OCRDMS-Setup-x.y.z.exe /VERYSILENT
;   → übernimmt Port, Arbeitsordner, Betriebsart, HTTPS und Firewall der vorherigen Installation.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{6E7C3B0A-4D1E-4E8B-9C0E-0C2D6F0A1B37}
AppName=OCRDMS
AppVersion={#AppVersion}
AppVerName=OCRDMS {#AppVersion}
AppPublisher=OCRDMS
DefaultDirName={autopf}\OCRDMS
DefaultGroupName=OCRDMS
DisableProgramGroupPage=yes
DisableWelcomePage=no
DisableDirPage=no
UsePreviousAppDir=yes
DisableReadyPage=no
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist
OutputBaseFilename=OCRDMS-Setup-{#AppVersion}
SetupIconFile=..\src\ocrdms\resources\app.ico
UninstallDisplayIcon={app}\OCRDMS.exe
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
LicenseFile=..\LICENSE
CloseApplications=force

[Languages]
Name: "de"; MessagesFile: "compiler:Languages\German.isl"

[Tasks]
Name: "desktopicon"; Description: "Verknüpfung auf dem Desktop anlegen"; GroupDescription: "Zusätzliche Verknüpfungen:"

[Dirs]
Name: "{commonappdata}\OCRDMS"; Permissions: users-modify

[Files]
Source: "..\dist\OCRDMS\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\OCRDMS öffnen"; Filename: "{app}\OCRDMS.exe"
Name: "{group}\OCRDMS deinstallieren"; Filename: "{uninstallexe}"
Name: "{commondesktop}\OCRDMS"; Filename: "{app}\OCRDMS.exe"; Tasks: desktopicon
; Ohne Dienst: bei der Anmeldung im Hintergrund starten
Name: "{commonstartup}\OCRDMS"; Filename: "{app}\OCRDMS.exe"; Check: not UseService

[Run]
Filename: "{app}\OCRDMS.exe"; Description: "OCRDMS jetzt öffnen"; Flags: postinstall nowait skipifsilent runasoriginaluser
; Nach einem stillen Update im Infobereich-Betrieb wieder starten (der Dienst startet sich selbst)
Filename: "{app}\OCRDMS.exe"; Parameters: "--no-browser"; Flags: nowait runasoriginaluser; Check: WizardSilent and not UseService

[UninstallRun]
Filename: "{app}\OCRDMS.exe"; Parameters: "service stop"; Flags: runhidden waituntilterminated; RunOnceId: "SvcStop"
Filename: "{app}\OCRDMS.exe"; Parameters: "service remove"; Flags: runhidden waituntilterminated; RunOnceId: "SvcRemove"
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""OCRDMS"""; Flags: runhidden waituntilterminated; RunOnceId: "FwDelete"
Filename: "{sys}\taskkill.exe"; Parameters: "/F /IM OCRDMS.exe"; Flags: runhidden waituntilterminated; RunOnceId: "Kill"

[Code]
var
  NetPage: TInputQueryWizardPage;
  OptPage: TInputOptionWizardPage;
  DirPage: TInputDirWizardPage;

function ReadExistingPort(): String;
var
  S: AnsiString;
  P, I: Integer;
begin
  Result := '8443';
  if LoadStringFromFile(ExpandConstant('{commonappdata}\OCRDMS\server.json'), S) then
  begin
    P := Pos('"port":', S);
    if P > 0 then
    begin
      Result := '';
      I := P + 7;
      while (I <= Length(S)) and ((S[I] = ' ') or ((S[I] >= '0') and (S[I] <= '9'))) do
      begin
        if S[I] <> ' ' then Result := Result + S[I];
        I := I + 1;
      end;
      if Result = '' then Result := '8443';
    end;
  end;
end;

procedure InitializeWizard;
begin
  NetPage := CreateInputQueryPage(wpSelectDir,
    'Netzwerk', 'Unter welchem Port soll OCRDMS erreichbar sein?',
    'Die Weboberfläche ist danach im Browser unter https://<Servername>:<Port> erreichbar – ' +
    'auch vom Handy im selben Netz. Der Port lässt sich später in den Einstellungen ändern.');
  NetPage.Add('Port (1–65535):', False);
  NetPage.Values[0] := GetPreviousData('Port', ReadExistingPort());

  DirPage := CreateInputDirPage(NetPage.ID,
    'Arbeitsordner', 'Wo sollen Eingang und Ergebnisse liegen?',
    'In diesem Ordner werden die Unterordner Eingang, Verarbeitet, Originale und Fehler angelegt. ' +
    'Bei einer Aktualisierung bleiben bestehende Einstellungen erhalten.', False, '');
  DirPage.Add('');
  DirPage.Values[0] := GetPreviousData('WorkDir', ExpandConstant('{sd}\OCRDMS'));

  OptPage := CreateInputOptionPage(DirPage.ID,
    'Betriebsart', 'Wie soll OCRDMS laufen?', '', False, False);
  OptPage.Add('Als Windows-Dienst installieren (läuft immer, auch ohne angemeldeten Benutzer)');
  OptPage.Add('HTTPS verwenden (empfohlen – nötig für die Handy-Kamera im Browser)');
  OptPage.Add('Zugriff nur aus dem lokalen Netz erlauben (Windows-Firewall)');
  if RegKeyExists(HKLM, 'SYSTEM\CurrentControlSet\Services\OCRDMS') then
    OptPage.Values[0] := GetPreviousData('Service', '1') = '1'
  else
    OptPage.Values[0] := GetPreviousData('Service', '0') = '1';
  OptPage.Values[1] := GetPreviousData('Https', '1') = '1';
  OptPage.Values[2] := GetPreviousData('LocalOnly', '1') = '1';
end;

function BoolStr(B: Boolean): String;
begin
  if B then Result := '1' else Result := '0';
end;

procedure RegisterPreviousData(PreviousDataKey: Integer);
begin
  SetPreviousData(PreviousDataKey, 'Port', Trim(NetPage.Values[0]));
  SetPreviousData(PreviousDataKey, 'WorkDir', DirPage.Values[0]);
  SetPreviousData(PreviousDataKey, 'Service', BoolStr(OptPage.Values[0]));
  SetPreviousData(PreviousDataKey, 'Https', BoolStr(OptPage.Values[1]));
  SetPreviousData(PreviousDataKey, 'LocalOnly', BoolStr(OptPage.Values[2]));
end;

function PortInUse(Port: Integer): Boolean;
var
  Tmp: String;
  Lines: TArrayOfString;
  I, Code: Integer;
begin
  Result := False;
  Tmp := ExpandConstant('{tmp}\ports.txt');
  if not Exec(ExpandConstant('{cmd}'), '/C netstat -an -p TCP > "' + Tmp + '"', '', SW_HIDE, ewWaitUntilTerminated, Code) then Exit;
  if not LoadStringsFromFile(Tmp, Lines) then Exit;
  for I := 0 to GetArrayLength(Lines) - 1 do
    if (Pos(':' + IntToStr(Port) + ' ', Lines[I]) > 0) and
       ((Pos('LISTENING', Lines[I]) > 0) or (Pos('ABHÖREN', Lines[I]) > 0)) then
    begin
      Result := True;
      Exit;
    end;
end;

function NextButtonClick(CurPageID: Integer): Boolean;
var
  Port: Integer;
begin
  Result := True;
  if CurPageID = NetPage.ID then
  begin
    Port := StrToIntDef(Trim(NetPage.Values[0]), 0);
    if (Port < 1) or (Port > 65535) then
    begin
      MsgBox('Bitte einen gültigen Port zwischen 1 und 65535 eingeben.', mbError, MB_OK);
      Result := False;
    end
    // Bei einer Aktualisierung belegt OCRDMS den bisherigen Port selbst – dann nicht warnen
    else if (IntToStr(Port) <> GetPreviousData('Port', '')) and PortInUse(Port) then
      Result := MsgBox('Port ' + IntToStr(Port) + ' wird bereits von einem anderen Programm verwendet.' + #13#10 +
        'OCRDMS könnte dann nicht starten. Trotzdem diesen Port verwenden?', mbConfirmation, MB_YESNO) = IDYES;
  end;
end;

function UseService(): Boolean;
begin
  Result := OptPage.Values[0];
end;

function UpdateReadyMemo(Space, NewLine, MemoUserInfoInfo, MemoDirInfo, MemoTypeInfo,
  MemoComponentsInfo, MemoGroupInfo, MemoTasksInfo: String): String;
var
  Mode: String;
begin
  if OptPage.Values[0] then Mode := 'Windows-Dienst' else Mode := 'Programm im Infobereich (startet bei Anmeldung)';
  Result := MemoDirInfo + NewLine + NewLine +
    'Arbeitsordner:' + NewLine + Space + DirPage.Values[0] + NewLine + NewLine +
    'Netzwerk:' + NewLine + Space + 'Port ' + Trim(NetPage.Values[0]);
  if OptPage.Values[1] then Result := Result + ', HTTPS' else Result := Result + ', HTTP';
  if OptPage.Values[2] then Result := Result + ', nur lokales Netz';
  Result := Result + NewLine + NewLine + 'Betriebsart:' + NewLine + Space + Mode;
  if MemoTasksInfo <> '' then Result := Result + NewLine + NewLine + MemoTasksInfo;
end;

procedure RunHidden(const FileName, Params: String);
var
  Code: Integer;
begin
  Exec(FileName, Params, '', SW_HIDE, ewWaitUntilTerminated, Code);
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  Code: Integer;
begin
  // Laufende Instanz/Dienst vor dem Überschreiben der Dateien beenden
  Exec(ExpandConstant('{sys}\sc.exe'), 'stop OCRDMS', '', SW_HIDE, ewWaitUntilTerminated, Code);
  Sleep(1500);
  Exec(ExpandConstant('{sys}\taskkill.exe'), '/F /IM OCRDMS.exe', '', SW_HIDE, ewWaitUntilTerminated, Code);
  Result := '';
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  Exe, Port, Proto, Remote: String;
begin
  if CurStep <> ssPostInstall then Exit;
  Exe := ExpandConstant('{app}\OCRDMS.exe');
  Port := Trim(NetPage.Values[0]);
  if OptPage.Values[1] then Proto := '--https' else Proto := '--http';

  WizardForm.StatusLabel.Caption := 'Einstellungen werden geschrieben …';
  RunHidden(Exe, 'config --port ' + Port + ' ' + Proto + ' --arbeitsordner "' + DirPage.Values[0] + '"');

  WizardForm.StatusLabel.Caption := 'Firewall wird eingerichtet …';
  RunHidden(ExpandConstant('{sys}\netsh.exe'), 'advfirewall firewall delete rule name="OCRDMS"');
  if OptPage.Values[2] then Remote := ' remoteip=localsubnet' else Remote := '';
  RunHidden(ExpandConstant('{sys}\netsh.exe'),
    'advfirewall firewall add rule name="OCRDMS" dir=in action=allow protocol=TCP localport=' + Port + Remote);

  WizardForm.StatusLabel.Caption := 'Dienst wird eingerichtet …';
  RunHidden(Exe, 'service stop');
  RunHidden(Exe, 'service remove');
  if OptPage.Values[0] then
  begin
    DeleteFile(ExpandConstant('{commonstartup}\OCRDMS.lnk'));  // Wechsel von Infobereich-Betrieb zu Dienst
    RunHidden(Exe, 'service install');
    RunHidden(Exe, 'service start');
  end;
end;
