#requires -Version 7.2
# Library only. Credentials travel through this child's redirected anonymous stdin.
function Send-SecureCredentialFrame {
    param([Parameter(Mandatory)][IO.Stream]$Stream,
          [Parameter(Mandatory)][Security.SecureString]$Secret)
    $bstr = [IntPtr]::Zero
    $plain = $json = $payload = $null
    try {
        $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($Secret)
        $plain = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
        $json = ConvertTo-Json -Compress -InputObject @{value = $plain}
        $payload = [Text.UTF8Encoding]::new($false, $true).GetBytes($json)
        if ($payload.Length -gt 65536) { throw 'Input rejected' }
        $header = [BitConverter]::GetBytes([int]$payload.Length)
        if (-not [BitConverter]::IsLittleEndian) { [Array]::Reverse($header) }
        $Stream.Write($header, 0, 4)
        $Stream.Write($payload, 0, $payload.Length)
        $Stream.Flush()
    }
    finally {
        if ($null -ne $payload) { [Array]::Clear($payload, 0, $payload.Length) }
        $plain = $json = $payload = $null
        if ($bstr -ne [IntPtr]::Zero) { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr) }
    }
}

function Invoke-ProvisionDialogue {
    param([Parameter(Mandatory)][string]$PythonExe,
          [Parameter(Mandatory)][string]$Script,
          [Parameter(Mandatory)][ValidateSet('V2Deploy','CorePlan','CoreApply','CoreVerify','AcceptDA01','Initialize','InspectObjects','VerifyAdmin','VerifyRuntime','AuthenticateRuntime','InspectDown')][string]$Mode,
          [ValidatePattern('^[A-Za-z0-9_]+$')][string]$AdminUser = 'root',
          [switch]$Apply,
          [ValidatePattern('^[A-Fa-f0-9]{64}$')][string]$ExpectedDdlSha256,
          [string]$V2Root,
          # Injection points are library-only, for synthetic tests. Public entry exposes neither.
          [scriptblock]$SecretReader = { param($Account, $Phase) Read-Host "$Account password ($Phase)" -AsSecureString },
          [scriptblock]$ConfirmationReader = { param($Phrase) Read-Host "Type $Phrase to approve" })
    $proc = $null
    $secret = $null
    $stage = 'process:start'
    try {
        if (($Mode -in @('Initialize','CoreApply','V2Deploy')) -ne [bool]$Apply) { throw 'Apply mismatch' }
        if ($Mode -eq 'CoreApply' -and -not $ExpectedDdlSha256) { throw 'Approved DDL hash required' }
        $info = [Diagnostics.ProcessStartInfo]::new()
        $info.FileName = $PythonExe
        $info.UseShellExecute = $false
        $info.CreateNoWindow = $true
        $info.RedirectStandardInput = $true
        $info.RedirectStandardOutput = $true
        $info.RedirectStandardError = $true
        foreach ($arg in @('-B', $Script, $Mode, $AdminUser)) { $info.ArgumentList.Add($arg) }
        if ($Apply) { $info.ArgumentList.Add('--apply') }
        if ($ExpectedDdlSha256) { $info.ArgumentList.Add('--ddl-sha256'); $info.ArgumentList.Add($ExpectedDdlSha256.ToUpperInvariant()) }
        if ($V2Root) { $info.ArgumentList.Add('--v2-root'); $info.ArgumentList.Add($V2Root) }
        $proc = [Diagnostics.Process]::new()
        $proc.StartInfo = $info
        if (-not $proc.Start()) { throw 'Child unavailable' }
        $stderr = $proc.StandardError.ReadToEndAsync()
        while ($true) {
            $lineTask = $proc.StandardOutput.ReadLineAsync()
            if (-not $lineTask.Wait(30000)) { throw 'Child timeout' }
            $line = $lineTask.GetAwaiter().GetResult()
            if ($null -eq $line -or $line.Length -gt 4096) { throw 'Invalid protocol' }
            $message = ConvertFrom-Json -InputObject $line -AsHashtable
            if ($message.type -eq 'progress') {
                if ($Mode -ne 'V2Deploy' -or $message.stage -notin @('schema_ready','grants_ready','e2e_running')) { throw 'Invalid progress' }
                Write-Host "V2: $($message.stage)"
            }
            elseif ($message.type -eq 'secret') {
                $account = $message.account
                $phase = $message.phase
                $runtime = @('rc_demo_app','rc_demo_reader','rc_demo_audit_writer')
                $valid = ($Mode -eq 'VerifyRuntime' -and $account -in $runtime -and $phase -eq 'login') -or
                    ($Mode -eq 'V2Deploy' -and $account -eq 'rc_demo_app' -and $phase -eq 'login') -or
                    ($Mode -eq 'AcceptDA01' -and $account -in $runtime -and $phase -eq 'login') -or
                    ($Mode -eq 'AuthenticateRuntime' -and $account -eq $AdminUser -and $account -in $runtime -and $phase -eq 'login') -or
                    ($Mode -ne 'VerifyRuntime' -and $account -eq $AdminUser -and $phase -eq 'login') -or
                    ($Mode -eq 'Initialize' -and $Apply -and $account -in $runtime -and $phase -in @('new','confirm'))
                if (-not $valid) { throw 'Unexpected credential request' }
                $stage = "credential:${account}:${phase}"
                try {
                    $secret = & $SecretReader $account $phase
                    if ($secret -isnot [Security.SecureString]) { throw 'Secure input unavailable' }
                    Send-SecureCredentialFrame -Stream $proc.StandardInput.BaseStream -Secret $secret
                }
                finally { if ($null -ne $secret) { $secret.Dispose(); $secret = $null } }
            }
            elseif ($message.type -eq 'confirm') {
                if ($Mode -notin @('Initialize','CoreApply','V2Deploy') -or -not $Apply) { throw 'Unexpected confirmation' }
                $stage = 'confirmation'
                $phrase = if ($Mode -eq 'V2Deploy') { 'DEPLOY V2 DEMO 3307' } elseif ($Mode -eq 'CoreApply') { 'APPLY CORE 0001 ON DEMO 3307' } else { 'INITIALIZE RC DEMO 3307' }
                $answer = & $ConfirmationReader $phrase
                if ($answer -cne $phrase) { throw 'Confirmation rejected' }
                try {
                    $secret = ConvertTo-SecureString -String $answer -AsPlainText -Force
                    Send-SecureCredentialFrame -Stream $proc.StandardInput.BaseStream -Secret $secret
                }
                finally { $answer = $null; if ($null -ne $secret) { $secret.Dispose(); $secret = $null } }
            }
            elseif ($message.type -eq 'result') {
                if ($message.mode -ne $Mode -or $message.ok -isnot [bool]) { throw 'Result mismatch' }
                $proc.StandardInput.Close()
                if (-not $proc.WaitForExit(30000)) { throw 'Child exit timeout' }
                $null = $stderr.GetAwaiter().GetResult()
                if ($message.ok -ne ($proc.ExitCode -eq 0)) { throw 'Exit mismatch' }
                if ($Mode -eq 'V2Deploy' -and $message.ok) {
                    $report=$message.v2_report
                    if ($report.tables -ne 11 -or $report.contract_fields -ne 89 -or $report.transactions -ne 3) { throw 'Unexpected V2 acceptance counts' }
                    $safe=@{}
                    foreach ($key in @('task_id','tables','contract_fields','transactions','metrics','report_version')) {
                        if ($report[$key] -isnot [int] -and $report[$key] -isnot [long]) { throw 'Invalid V2 count' }
                        $safe[$key]=$report[$key]
                    }
                    foreach ($key in @('http_upload_ok','report_read_ok','privacy_ok','grants_ok','backup_sample_roundtrip')) {
                        if ($report[$key] -ne $true) { throw 'Incomplete V2 result' }; $safe[$key]=$true
                    }
                    if ($report.backup_file -notmatch '^v2-synthetic-backup-[a-f0-9]{32}[.]json$') { throw 'Invalid backup reference' }
                    $safe.backup_file=$report.backup_file
                    return [pscustomobject]@{ExitCode=0;Result='PASS: V2Deploy; upload/parse/store/metrics/report';V2Report=$safe}
                }
                if ($Mode -in @('CorePlan','CoreApply','CoreVerify') -and $message.ok) {
                    $report = $message.core_report
                    if ($report.schema_sha256 -notmatch '^[A-F0-9]{64}$' -or
                        $report.phase -notin @('fresh','applied','already_applied') -or
                        $report.migration_dependencies_ready -isnot [bool]) { throw 'Invalid core report' }
                    $safe = @{ schema_sha256=$report.schema_sha256; phase=$report.phase; migration_dependencies_ready=$report.migration_dependencies_ready }
                    foreach ($key in @('table_count','field_count')) {
                        if (($report[$key] -isnot [long] -and $report[$key] -isnot [int]) -or $report[$key] -lt 0 -or $report[$key] -gt 1000) { throw 'Invalid metadata count' }
                        $safe[$key]=$report[$key]
                    }
                    foreach ($key in @('tables_ok','fields_ok','primary_keys_ok','indexes_ok','constraints_ok','partitions_ok','show_create_partitioned','foreign_keys_absent','revision_ok','boundary_dml_tested','downgrade_tested')) {
                        if ($report.ContainsKey($key)) { if ($report[$key] -isnot [bool]) { throw 'Invalid core check' }; $safe[$key]=$report[$key] }
                    }
                    if ($report.ContainsKey('explain_matches')) {
                        if ($report.explain_matches -notin @(0,1,2,3,4)) { throw 'Invalid explain result' }
                        $safe.explain_matches=$report.explain_matches
                    }
                    if ($null -ne $report.baseline_file -and $report.baseline_file -notmatch '^core-before-[a-f0-9]{32}[.]json$') { throw 'Invalid baseline identifier' }
                    $safe.baseline_file=$report.baseline_file
                    return [pscustomobject]@{ExitCode=0; Result="PASS: $Mode; phase=$($report.phase); tables=$($report.table_count); fields=$($report.field_count)"; CoreReport=$safe}
                }
                if ($Mode -eq 'AcceptDA01' -and $message.ContainsKey('checks')) {
                    $expectedNames = @('admin_structure_and_isolation','runtime_metadata','rc_demo_app','rc_demo_reader','rc_demo_audit_writer')
                    $categories = @('PASS','ADMIN_CHECK_FAILED','METADATA_MISMATCH','AUTHENTICATION_REJECTED',
                        'CONNECTION_OR_CHECK_FAILED','EMPTY_INPUT','CONTROL_CHARACTER','TOO_SHORT','INPUT_REJECTED','IDENTITY_MISMATCH','ROLE_MISMATCH')
                    $checks = @()
                    if ($message.checks.Count -ne 5) { throw 'Incomplete acceptance' }
                    for ($i=0; $i -lt 5; $i++) {
                        $check = $message.checks[$i]
                        if ($check.name -ne $expectedNames[$i] -or $check.ok -isnot [bool] -or
                            $check.category -notin $categories -or $check.ok -ne ($check.category -eq 'PASS')) { throw 'Invalid acceptance check' }
                        if ($null -ne $check.code -and $check.code -isnot [int] -and $check.code -isnot [long]) { throw 'Invalid check code' }
                        $checks += @{ name=$check.name; ok=$check.ok; category=$check.category; code=$check.code }
                    }
                    $allPass = @($checks | Where-Object { -not $_.ok }).Count -eq 0
                    if ($allPass -ne $message.ok) { throw 'Acceptance result mismatch' }
                    $accounts = @()
                    foreach ($row in $message.runtime_accounts) {
                        if ($row.Count -ne 6 -or $row[0] -notin @('rc_demo_app','rc_demo_reader','rc_demo_audit_writer') -or
                            $row[1] -notmatch '^[A-Za-z0-9_.:%/-]{1,255}$' -or $row[2] -notin @('Y','N') -or
                            $row[3] -notmatch '^[A-Za-z0-9_]{1,80}$') { throw 'Invalid account metadata' }
                        if ($null -ne $row[4] -and $row[4] -notmatch '^[A-Za-z0-9_]{1,80}$') { throw 'Invalid role metadata' }
                        if ($null -ne $row[5] -and $row[5] -notmatch '^[A-Za-z0-9_.:%/-]{1,255}$') { throw 'Invalid role host' }
                        $accounts += @{ user=$row[0]; host=$row[1]; locked=$row[2]; plugin=$row[3]; default_role=$row[4]; default_role_host=$row[5] }
                    }
                    $text = if ($allPass) { 'PASS: AcceptDA01' } else { 'FAIL: AcceptDA01 (read-only; no changes)' }
                    foreach ($check in $checks) { $text += "`n$($check.name): $($check.category)"; if ($null -ne $check.code) { $text += " (code=$($check.code))" } }
                    foreach ($account in $accounts) { $text += "`naccount=$($account.user)@$($account.host); locked=$($account.locked); plugin=$($account.plugin); default_role=$($account.default_role)@$($account.default_role_host)" }
                    return [pscustomobject]@{ ExitCode=$proc.ExitCode; Result=$text; Checks=$checks; Accounts=$accounts }
                }
                if ($message.ok) {
                    $text = "PASS: $Mode"
                    if ($Mode -eq 'InspectObjects') {
                        if ($message.databases -isnot [long] -and $message.databases -isnot [int]) { throw 'Invalid count' }
                        if ($message.principals -isnot [long] -and $message.principals -isnot [int]) { throw 'Invalid count' }
                        $text += "; databases=$($message.databases); principals=$($message.principals)"
                        foreach ($row in $message.runtime_accounts) {
                            if ($row.Count -ne 6 -or $row[0] -notin @('rc_demo_app','rc_demo_reader','rc_demo_audit_writer') -or
                                $row[1] -notmatch '^[A-Za-z0-9_.:%/-]{1,255}$' -or $row[2] -notin @('Y','N') -or
                                $row[3] -notmatch '^[A-Za-z0-9_]{1,80}$') { throw 'Invalid account metadata' }
                            $role = if ($null -eq $row[4]) { '(none)' } elseif ($row[4] -match '^[A-Za-z0-9_]{1,80}$') { $row[4] } else { throw 'Invalid role metadata' }
                            $roleHost = if ($null -eq $row[5]) { '(none)' } elseif ($row[5] -match '^[A-Za-z0-9_.:%/-]{1,255}$') { $row[5] } else { throw 'Invalid role host' }
                            $text += "`naccount=$($row[0])@$($row[1]); locked=$($row[2]); plugin=$($row[3]); default_role=${role}@${roleHost}"
                        }
                    }
                    return [pscustomobject]@{ ExitCode = 0; Result = $text }
                }
                $allowed = @('INPUT_EOF','INPUT_REJECTED','EMPTY_INPUT','CONTROL_CHARACTER','TOO_SHORT',
                    'CONFIRMATION_MISMATCH','REUSED_CREDENTIAL','CONFIRMATION_REQUIRED','MODE_REJECTED',
                    'APPLY_REQUIRED','IDENTITY_MISMATCH','ROLE_MISMATCH','QUERY_LOGGING_ENABLED','INPUT_CANCELLED','AUTHENTICATION_REJECTED','DATABASE_OR_DEPENDENCY_FAILURE',
                    'ARTIFACT_MISMATCH','DA01_EVIDENCE_REQUIRED','TARGET_MISMATCH','UNEXPECTED_OBJECTS','PARTIAL_OR_UNKNOWN_OBJECTS','MODE_REJECTED',
                    'MIGRATION_DEPENDENCIES_OR_HASH','SCHEMA_MISMATCH','SCHEMA_NOT_CREATED','EXISTING_OBJECTS_STOP','CONFIRMATION_REQUIRED','CORE_EXECUTION_FAILED')
                if ($message.category -notin $allowed -or $message.stage -notmatch '^[A-Za-z0-9_:]{1,120}$' -or
                    $message.writes_started -isnot [bool]) { throw 'Invalid error category' }
                $code = if ($null -eq $message.code) { 'suppressed' } elseif ($message.code -is [long] -or $message.code -is [int]) { [string]$message.code } else { throw 'Invalid error code' }
                return [pscustomobject]@{ ExitCode = 1; Result = "STOP: stage=$($message.stage); category=$($message.category); error code=$code; writes_started=$($message.writes_started)" }
            }
            else { throw 'Unknown protocol message' }
        }
    }
    catch { return [pscustomobject]@{ ExitCode = 1; Result = "STOP: stage=$stage; category=INPUT_OR_TRANSPORT_FAILURE; writes_started=unknown; preserve partial state" } }
    finally {
        if ($null -ne $secret) { $secret.Dispose() }
        if ($null -ne $proc) {
            try { if (-not $proc.HasExited) { $proc.Kill(); $proc.WaitForExit() } } catch { }
            $proc.Dispose()
        }
    }
}

function Invoke-CredentialChild {
    param([Parameter(Mandatory)][string]$PythonExe,
          [Parameter(Mandatory)][string]$Script,
          [Parameter(Mandatory)][ValidateSet('authenticate','transport-test')][string]$Mode,
          [Parameter(Mandatory)][Security.SecureString]$Secret)
    $proc = $null
    $bstr = [IntPtr]::Zero
    $plain = $json = $payload = $null
    try {
        $info = [Diagnostics.ProcessStartInfo]::new()
        $info.FileName = $PythonExe
        $info.UseShellExecute = $false
        $info.CreateNoWindow = $true
        $info.RedirectStandardInput = $true
        $info.RedirectStandardOutput = $true
        $info.RedirectStandardError = $true
        foreach ($arg in @('-B', $Script, $Mode)) { $info.ArgumentList.Add($arg) }
        $proc = [Diagnostics.Process]::new()
        $proc.StartInfo = $info
        if (-not $proc.Start()) { throw 'Child unavailable' }
        $stdout = $proc.StandardOutput.ReadToEndAsync()
        $stderr = $proc.StandardError.ReadToEndAsync()
        $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($Secret)
        $plain = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
        $json = ConvertTo-Json -Compress -InputObject @{password = $plain}
        $payload = [Text.UTF8Encoding]::new($false, $true).GetBytes($json)
        if ($payload.Length -gt 65536) { throw 'Input rejected' }
        $header = [BitConverter]::GetBytes([int]$payload.Length)
        if (-not [BitConverter]::IsLittleEndian) { [Array]::Reverse($header) }
        $stream = $proc.StandardInput.BaseStream
        $stream.Write($header, 0, 4)
        $stream.Write($payload, 0, $payload.Length)
        $stream.Flush()
        $proc.StandardInput.Close()
        if (-not $proc.WaitForExit(30000)) { throw 'Child timeout' }
        $result = $stdout.GetAwaiter().GetResult().Trim()
        $null = $stderr.GetAwaiter().GetResult() # Never forward raw stderr.
        $allowed = @('AUTHENTICATION PASS','TRANSPORT PASS',
            'AUTHENTICATION FAIL: INPUT_REJECTED',
            'AUTHENTICATION FAIL: DEPENDENCY_UNAVAILABLE',
            'AUTHENTICATION FAIL: AUTHENTICATION_REJECTED',
            'AUTHENTICATION FAIL: CONNECTION_OR_TARGET_FAILURE')
        if ($result -notin $allowed) { throw 'Unexpected child result' }
        if (($proc.ExitCode -eq 0) -ne ($result -in @('AUTHENTICATION PASS','TRANSPORT PASS'))) {
            throw 'Child result mismatch'
        }
        [pscustomobject]@{ ExitCode = $proc.ExitCode; Result = $result }
    }
    catch { [pscustomobject]@{ ExitCode = 1; Result = 'AUTHENTICATION FAIL: TRANSPORT_FAILURE' } }
    finally {
        if ($null -ne $payload) { [Array]::Clear($payload, 0, $payload.Length) }
        $plain = $json = $payload = $null
        if ($bstr -ne [IntPtr]::Zero) { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr) }
        if ($null -ne $proc) {
            try { if (-not $proc.HasExited) { $proc.Kill(); $proc.WaitForExit() } } catch { }
            $proc.Dispose()
        }
    }
}
