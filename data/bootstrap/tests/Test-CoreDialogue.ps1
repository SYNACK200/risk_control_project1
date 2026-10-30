#requires -Version 7.2
param([Parameter(Mandatory)][string]$PythonExe)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot '..\credential_pipe.ps1')
foreach ($mode in @('CorePlan','CoreVerify')) {
    $result = Invoke-ProvisionDialogue -PythonExe $PythonExe -Script (Join-Path $PSScriptRoot 'core_dialogue_fixture.py') -Mode $mode -SecretReader {param($Account,$Phase) ConvertTo-SecureString -String 'Synthetic-fixture-42!' -AsPlainText -Force}
    if ($result.ExitCode -ne 0 -or $null -eq $result.CoreReport) { throw "Core fixture failed: $mode; $($result.Result)" }
    "PASS: $mode native pipe protocol (in-memory metadata only)"
}
$digest = (Get-FileHash -Algorithm SHA256 (Join-Path $PSScriptRoot '..\..\core\schema.sql')).Hash
$result = Invoke-ProvisionDialogue -PythonExe $PythonExe -Script (Join-Path $PSScriptRoot 'core_dialogue_fixture.py') -Mode CoreApply -Apply -ExpectedDdlSha256 $digest -SecretReader {param($Account,$Phase) ConvertTo-SecureString -String 'Synthetic-fixture-42!' -AsPlainText -Force} -ConfirmationReader { 'APPLY CORE 0001 ON DEMO 3307' }
if ($result.ExitCode -ne 0 -or $result.CoreReport.phase -ne 'applied') { throw 'Fake apply dialogue failed' }
'PASS: CoreApply hash/confirmation protocol; temporary-file and in-memory migration fixture only'
'Core dialogue: 3 PASS; no actual MySQL or migration'
