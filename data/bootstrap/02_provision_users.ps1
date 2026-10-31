#requires -Version 7.2
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$PythonExe,
    [ValidateSet('CheckDependencies','AuthenticateOnly','AuthenticateRuntime','InspectObjects','VerifyAdmin','VerifyRuntime','InspectDown','Initialize')]
    [string]$Mode = 'VerifyAdmin',
    [ValidatePattern('^[A-Za-z0-9_]+$')][string]$AdminUser = 'root',
    [ValidateSet('rc_demo_app','rc_demo_reader','rc_demo_audit_writer')][string]$RuntimeUser = 'rc_demo_app',
    [switch]$Apply
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
try {
    if (-not $IsWindows -or -not [IO.Path]::IsPathFullyQualified($PythonExe) -or
        -not (Test-Path -LiteralPath $PythonExe -PathType Leaf)) { throw 'Invalid interpreter' }
    if (($Mode -eq 'Initialize') -ne [bool]$Apply) { throw 'Initialize requires -Apply; other modes forbid it' }
    if ($Mode -eq 'AuthenticateOnly') {
        if ($AdminUser -ne 'root') { throw 'Diagnostic is root-only' }
        & (Join-Path $PSHOME 'pwsh.exe') -NoProfile -File (Join-Path $PSScriptRoot '06_authenticate_secure.ps1') -PythonExe $PythonExe
        exit $LASTEXITCODE
    }
    if ($Mode -ne 'CheckDependencies') {
        & (Join-Path $PSHOME 'pwsh.exe') -NoProfile -File (Join-Path $PSScriptRoot 'preflight.ps1') -Mode Ready -Phase AfterStart
        if ($LASTEXITCODE -ne 0) { throw 'OS identity/readiness failed' }
    }
    # No credentials are read or transmitted by this dependency-only command.
    $dependencyCode = 'import sys; sys.path.insert(0, sys.argv[1]); from authenticate_pipe import dependencies; dependencies(); print("DEPENDENCIES PASS: Python " + sys.version.split()[0])'
    $checkOutput = & $PythonExe -B -c $dependencyCode $PSScriptRoot 2>&1
    if ($LASTEXITCODE -ne 0) { throw 'Dependency admission failed' }
    $checkText = [string]($checkOutput -join "`n")
    if ($checkText -notmatch '^DEPENDENCIES PASS: Python 3[.](11|12)[.]\d+$') { throw 'Unexpected dependency result' }
    Write-Output $checkText
    if ($Mode -eq 'CheckDependencies') { exit 0 }
    if ([Console]::IsInputRedirected) { throw 'Real interactive terminal required' }
    . (Join-Path $PSScriptRoot 'credential_pipe.ps1')
    $targetUser = if ($Mode -eq 'AuthenticateRuntime') { $RuntimeUser } else { $AdminUser }
    $result = Invoke-ProvisionDialogue -PythonExe $PythonExe -Script (Join-Path $PSScriptRoot 'provision_core.py') -Mode $Mode -AdminUser $targetUser -Apply:$Apply
    Write-Output $result.Result
    exit $result.ExitCode
}
catch { Write-Output 'STOP: category=INPUT_OR_PREREQUISITE_FAILURE; no automatic cleanup'; exit 1 }
