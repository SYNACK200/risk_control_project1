#requires -Version 7.2
param([Parameter(Mandatory)][string]$PythonExe, [switch]$InteractiveSynthetic)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot '..\credential_pipe.ps1')
$fixture = Join-Path $PSScriptRoot 'provision_dialogue_fixture.py'
if ($InteractiveSynthetic) {
    # This starts ONLY the FakeDriver fixture, never the production entry or MySQL.
    $result = Invoke-ProvisionDialogue -PythonExe $PythonExe -Script $fixture -Mode Initialize -Apply
    if ($result.ExitCode -ne 0) { throw 'Synthetic interactive dialogue failed' }
    'PASS: interactive Read-Host multi-frame dialogue; fake database only'
    exit 0
}
$goodReader = { param($Account, $Phase) ConvertTo-SecureString -String ("Synthetic-${Account}-42!" + [char]0x6f22 + [char]::ConvertFromUtf32(0x1f600)) -AsPlainText -Force }
$confirm = { 'INITIALIZE RC DEMO 3307' }
foreach ($mode in @('InspectObjects','VerifyAdmin','VerifyRuntime','InspectDown','Initialize')) {
    $result = Invoke-ProvisionDialogue -PythonExe $PythonExe -Script $fixture -Mode $mode -Apply:($mode -eq 'Initialize') -SecretReader $goodReader -ConfirmationReader $confirm
    if ($result.ExitCode -ne 0 -or -not $result.Result.StartsWith("PASS: $mode")) { throw "Synthetic dialogue failed: $mode; $($result.Result)" }
    "PASS: real subprocess dialogue $mode (in-memory DB only)"
}
$result = Invoke-ProvisionDialogue -PythonExe $PythonExe -Script $fixture -Mode AuthenticateRuntime -AdminUser rc_demo_app -SecretReader $goodReader
if ($result.ExitCode -ne 0 -or $result.Result -ne 'PASS: AuthenticateRuntime') { throw 'Synthetic single-account auth failed' }
'PASS: single runtime account authentication (in-memory DB only)'
$result = Invoke-ProvisionDialogue -PythonExe $PythonExe -Script $fixture -Mode AcceptDA01 -SecretReader $goodReader
if ($result.ExitCode -ne 0 -or $result.Checks.Count -ne 5) { throw 'Synthetic unified acceptance failed' }
'PASS: unified acceptance, one admin and three runtime prompts (in-memory DB only)'
$result = Invoke-ProvisionDialogue -PythonExe $PythonExe -Script (Join-Path $PSScriptRoot 'provision_acceptance_failure_fixture.py') -Mode AcceptDA01 -SecretReader $goodReader
if ($result.ExitCode -ne 1 -or $result.Checks.Count -ne 5 -or $result.Checks[2].code -ne 1045 -or
    -not $result.Checks[3].ok -or -not $result.Checks[4].ok -or $result.Result -match 'SYNTHETIC-DO-NOT-PRINT') {
    throw 'Failed-account aggregation regression'
}
'PASS: 1045 aggregate retains all accounts, suppresses raw exception (in-memory DB only)'
$cases = @(
    @{Name='mismatch'; Category='CONFIRMATION_MISMATCH'; Reader={param($Account,$Phase) ConvertTo-SecureString -String "Synthetic-${Phase}-42!" -AsPlainText -Force}},
    @{Name='reuse'; Category='REUSED_CREDENTIAL'; Reader={param($Account,$Phase) ConvertTo-SecureString -String 'Synthetic-reused-42!' -AsPlainText -Force}},
    @{Name='empty'; Category='EMPTY_INPUT'; Reader={param($Account,$Phase) [Security.SecureString]::new()}},
    @{Name='control'; Category='CONTROL_CHARACTER'; Reader={param($Account,$Phase) ConvertTo-SecureString -String ('Synthetic' + [char]22 + '42!') -AsPlainText -Force}},
    @{Name='cancel'; Category='INPUT_OR_TRANSPORT_FAILURE'; Reader={param($Account,$Phase) if($Account -eq 'rc_demo_reader'){throw 'synthetic cancel'}; ConvertTo-SecureString -String "Synthetic-${Account}-42!" -AsPlainText -Force}}
)
foreach ($case in $cases) {
    $result = Invoke-ProvisionDialogue -PythonExe $PythonExe -Script $fixture -Mode Initialize -Apply -SecretReader $case.Reader -ConfirmationReader $confirm
    if ($result.ExitCode -ne 1 -or $result.Result -notmatch $case.Category) { throw "Synthetic negative test failed: $($case.Name)" }
    "PASS: real subprocess $($case.Name), no real DB"
}
$result = Invoke-ProvisionDialogue -PythonExe $PythonExe -Script $fixture -Mode Initialize -Apply -SecretReader $goodReader -ConfirmationReader { 'NO' }
if ($result.ExitCode -ne 1) { throw 'Bad confirmation accepted' }
'Provision dialogue: 14 PASS; synthetic credentials; fake database only'
