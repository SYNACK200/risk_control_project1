#requires -Version 7.2
param([Parameter(Mandatory)][string]$PythonExe, [switch]$InteractiveSynthetic)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot '..\credential_pipe.ps1')
$secret = $null
try {
    if ($InteractiveSynthetic) {
        # Enter ONLY the documented synthetic fixture, NEVER a real credential.
        $secret = Read-Host 'Synthetic fixture only' -AsSecureString
    } else {
        $fixture = 'Synthetic-' + [char]0x6f22 + [char]0x5b57 + '-' +
            [char]::ConvertFromUtf32(0x1f600) + '-!"\$` '
        $secret = ConvertTo-SecureString -String $fixture -AsPlainText -Force
        $fixture = $null
    }
    $result = Invoke-CredentialChild -PythonExe $PythonExe -Script (Join-Path $PSScriptRoot '..\authenticate_pipe.py') -Mode transport-test -Secret $secret
    if ($result.ExitCode -ne 0 -or $result.Result -ne 'TRANSPORT PASS') { throw 'Transport test failed' }
    'Credential pipe subprocess: PASS (synthetic fixture; no network)'
}
finally { if ($null -ne $secret) { $secret.Dispose() } }
