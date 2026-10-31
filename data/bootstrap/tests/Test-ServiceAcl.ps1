#requires -Version 7.2
# Pure in-memory tests + AST inspection. NEVER dot-source/invoke the target script.
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$source = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\05_prepare_service_acl.ps1')).Path
$tokens=$null; $parseErrors=$null
$ast=[System.Management.Automation.Language.Parser]::ParseFile($source,[ref]$tokens,[ref]$parseErrors)
if ($parseErrors.Count) { throw 'Target syntax errors' }
$definitions=@($ast.FindAll({param($node) $node -is [System.Management.Automation.Language.FunctionDefinitionAst]},$true))
foreach ($name in @('Get-Rules','Assert-BaseAcl','Assert-ApprovedAcl','Assert-SnapshotPath',
                    'Assert-SnapshotEqual','Get-BytesSha256','Assert-BackupIntegrity',
                    'Set-PrivateManagementRules','New-ServiceRule')) {
    $definition=@($definitions | Where-Object Name -EQ $name)
    if ($definition.Count -ne 1) { throw "Missing pure helper: $name" }
    . ([scriptblock]::Create($definition[0].Extent.Text))
}
$root='D:\RiskControlDemo\mysql84'
$parent='D:\RiskControlDemo'
$maintenanceSid='S-1-5-21-251875384-4178690216-1937418480-1001'
$baseSids=@($maintenanceSid,'S-1-5-18','S-1-5-32-544')
$serviceSid=[Security.Principal.SecurityIdentifier]::new('S-1-5-80-3787980702-3828273279-332142536-3330034793-389180887')
$passed=0
function Test-Case([string]$Name,[scriptblock]$Body) {
    & $Body
    $script:passed++
    Write-Output "PASS: $Name"
}
function Must-Reject([scriptblock]$Body,[string]$Reason = '') {
    $rejected=$false
    try { & $Body } catch {
        if ($Reason -and $_.Exception.Message -cne $Reason) { throw "Wrong rejection reason: $($_.Exception.Message)" }
        $rejected=$true
    }
    if (-not $rejected) { throw 'Expected rejection' }
}
function Assert-True([bool]$Condition) { if (-not $Condition) { throw 'Assertion failed' } }
function New-Snapshot {
    foreach ($index in 0..522) {
        $path=if ($index -eq 0) {$parent} elseif ($index -eq 1) {$root} else {Join-Path $root ('fixture-{0:D4}' -f $index)}
        [pscustomobject]@{Path=$path;OwnerSid=$maintenanceSid;Protected=($index -le 1);AccessSddl='D:P(A;;FA;;;SY)'}
    }
}
function Copy-Snapshot { return @($expected | ConvertTo-Json -Depth 4 | ConvertFrom-Json) }
$expected=@(New-Snapshot)
$bytes=[Text.UTF8Encoding]::new($false).GetBytes(($expected | ConvertTo-Json -Depth 4))
$hash=Get-BytesSha256 $bytes

Test-Case 'target parser: zero errors' { Assert-True ($parseErrors.Count -eq 0) }
Test-Case '523 records: JSON roundtrip and SHA256' {
    Assert-BackupIntegrity $expected (Copy-Snapshot) $hash $hash
}
Test-Case 'path-set comparison is independent of record order' {
    $copy=Copy-Snapshot
    [array]::Reverse($copy)
    Assert-SnapshotEqual $expected $copy
}
Test-Case 'duplicate path with unchanged count rejected' {
    $copy=Copy-Snapshot; $copy[522].Path=$copy[521].Path
    Must-Reject { Assert-SnapshotEqual $expected $copy } 'Duplicate snapshot path'
}
Test-Case 'case-variant duplicate path rejected' {
    $copy=Copy-Snapshot; $copy[522].Path=$copy[521].Path.ToUpperInvariant()
    Must-Reject { Assert-SnapshotEqual $expected $copy } 'Duplicate snapshot path'
}
Test-Case 'missing record rejected' {
    $copy=(Copy-Snapshot)[0..521]
    Must-Reject { Assert-SnapshotEqual $expected $copy } 'Snapshot object count mismatch'
}
Test-Case 'extra record rejected' {
    $copy=Copy-Snapshot
    $extra=[pscustomobject]@{Path=(Join-Path $root 'extra');OwnerSid=$maintenanceSid;Protected=$false;AccessSddl='D:P(A;;FA;;;SY)'}
    Must-Reject { Assert-SnapshotEqual $expected @($copy+$extra) } 'Snapshot object count mismatch'
}
Test-Case 'same count with replaced path rejected' {
    $copy=Copy-Snapshot; $copy[522].Path=Join-Path $root 'unknown-replacement'
    Must-Reject { Assert-SnapshotEqual $expected $copy } 'Missing/extra snapshot path'
}
Test-Case 'owner tampering rejected' {
    $copy=Copy-Snapshot; $copy[2].OwnerSid='S-1-5-18'
    Must-Reject { Assert-SnapshotEqual $expected $copy } 'Snapshot path/owner/protection/SDDL mismatch'
}
Test-Case 'inheritance protection tampering rejected' {
    $copy=Copy-Snapshot; $copy[2].Protected=$true
    Must-Reject { Assert-SnapshotEqual $expected $copy } 'Snapshot path/owner/protection/SDDL mismatch'
}
Test-Case 'SDDL tampering rejected' {
    $copy=Copy-Snapshot; $copy[2].AccessSddl='D:P(A;;FR;;;BU)'
    Must-Reject { Assert-SnapshotEqual $expected $copy } 'Snapshot path/owner/protection/SDDL mismatch'
}
Test-Case 'record field type tampering rejected' {
    $copy=Copy-Snapshot; $copy[2].Protected='False'
    Must-Reject { Assert-SnapshotEqual $expected $copy } 'Invalid snapshot fields/types'
}
Test-Case 'unexpected field rejected' {
    $copy=Copy-Snapshot; $copy[2] | Add-Member -NotePropertyName Unexpected -NotePropertyValue 1
    Must-Reject { Assert-SnapshotEqual $expected $copy } 'Invalid snapshot fields/types'
}
Test-Case 'path traversal rejected' {
    $copy=Copy-Snapshot; $copy[2].Path=$root+'\conf\..\..\MySQL80'
    Must-Reject { Assert-SnapshotEqual $expected $copy } 'Snapshot path outside the fixed instance scope or not canonical'
}
Test-Case 'outside-scope sibling rejected' {
    $copy=Copy-Snapshot; $copy[2].Path='D:\RiskControlDemo\mysql84-other\file'
    Must-Reject { Assert-SnapshotEqual $expected $copy } 'Snapshot path outside the fixed instance scope or not canonical'
}
Test-Case 'duplicate in pre-write snapshot rejected' {
    $copy=Copy-Snapshot; $copy[522].Path=$copy[521].Path
    Must-Reject { Assert-SnapshotEqual $copy $copy } 'Duplicate snapshot path'
}
Test-Case 'byte tampering changes expected hash and is rejected' {
    $changed=[byte[]]$bytes.Clone(); $changed[0]=$changed[0] -bxor 1
    $changedHash=Get-BytesSha256 $changed
    Assert-True ($changedHash -cne $hash)
    Must-Reject { Assert-BackupIntegrity $expected (Copy-Snapshot) $hash $changedHash } 'Backup bytes SHA256 mismatch'
}
Test-Case 'same-count data corruption rejected even with matching claimed hash' {
    $copy=Copy-Snapshot; $copy[2].OwnerSid='S-1-5-18'
    Must-Reject { Assert-BackupIntegrity $expected $copy $hash $hash } 'Snapshot path/owner/protection/SDDL mismatch'
}
Test-Case 'wrong expected hash encoding rejected' {
    Must-Reject { Assert-BackupIntegrity $expected (Copy-Snapshot) 'not-a-sha256' 'not-a-sha256' } 'Backup bytes SHA256 mismatch'
}
Test-Case 'UTF8 non-ASCII paths roundtrip without filesystem access' {
    $copy=Copy-Snapshot; $copy[2].Path=Join-Path $root '模拟路径'
    $encoded=[Text.UTF8Encoding]::new($false).GetBytes(($copy | ConvertTo-Json -Depth 4))
    $decoded=@([Text.UTF8Encoding]::new($false).GetString($encoded) | ConvertFrom-Json)
    $digest=Get-BytesSha256 $encoded
    Assert-BackupIntegrity $copy $decoded $digest $digest
}

Test-Case 'private log and backup DACL preserve only explicit management rights' {
    foreach ($kind in @('File','Directory')) {
        $acl=if($kind -eq 'File'){[Security.AccessControl.FileSecurity]::new()}else{[Security.AccessControl.DirectorySecurity]::new()}
        $acl.SetSecurityDescriptorSddlForm("D:AI(A;ID;FA;;;SY)(A;ID;FA;;;BA)(A;ID;FA;;;$maintenanceSid)")
        $acl=Set-PrivateManagementRules $acl
        Assert-BaseAcl $acl
        Assert-True $acl.AreAccessRulesProtected
        Assert-True (@(Get-Rules $acl | Where-Object IsInherited).Count -eq 0)
        Assert-True (@(Get-Rules $acl | Where-Object {$_.IdentityReference.Value -eq $serviceSid.Value}).Count -eq 0)
    }
}
Test-Case 'service RX/Modify exclude WRITE_DAC WRITE_OWNER and DELETE_CHILD' {
    $rx=New-ServiceRule $serviceSid ReadAndExecute $false
    $modify=New-ServiceRule $serviceSid Modify $true
    Assert-True ($rx.InheritanceFlags -eq 'None')
    Assert-True ($modify.InheritanceFlags -eq ([Security.AccessControl.InheritanceFlags]::ObjectInherit -bor [Security.AccessControl.InheritanceFlags]::ContainerInherit))
    foreach ($rule in @($rx,$modify)) {
        foreach ($forbidden in @('ChangePermissions','TakeOwnership','DeleteSubdirectoriesAndFiles')) {
            Assert-True (($rule.FileSystemRights -band [Security.AccessControl.FileSystemRights]$forbidden) -eq 0)
        }
    }
}
Test-Case 'reviewed baseline checks owner and exact ACE inheritance flags' {
    $acl=[Security.AccessControl.FileSecurity]::new()
    $acl.SetSecurityDescriptorSddlForm("D:AI(A;ID;FA;;;SY)(A;ID;FA;;;BA)(A;ID;FA;;;$maintenanceSid)")
    $acl.SetOwner([Security.Principal.SecurityIdentifier]::new($maintenanceSid))
    Assert-ApprovedAcl (Join-Path $root 'fixture') $acl $false
    $explicit=[Security.AccessControl.FileSecurity]::new()
    $explicit.SetSecurityDescriptorSddlForm("D:AI(A;;FA;;;SY)(A;;FA;;;BA)(A;;FA;;;$maintenanceSid)")
    $explicit.SetOwner([Security.Principal.SecurityIdentifier]::new($maintenanceSid))
    Must-Reject { Assert-ApprovedAcl (Join-Path $root 'fixture') $explicit $false } 'ACE inheritance/propagation baseline changed'
}

$main=@($ast.EndBlock.Statements | Where-Object {$_ -is [System.Management.Automation.Language.TryStatementAst]})
if ($main.Count -ne 1) { throw 'Expected single guarded main block' }
$main=$main[0]
$calls=@($main.Body.FindAll({param($node) $node -is [System.Management.Automation.Language.CommandAst]},$true))
$gate=@($main.Body.FindAll({param($node)
    $node -is [System.Management.Automation.Language.AssignmentStatementAst] -and
    $node.Left.Extent.Text -eq '$baselineValidated' -and $node.Right.Extent.Text -eq '$true'
},$true))
Test-Case 'all native programs occur after complete baseline gate' {
    Assert-True ($gate.Count -eq 1)
    $native=@($calls | Where-Object {$_.InvocationOperator -eq [System.Management.Automation.Language.TokenKind]::Ampersand})
    Assert-True ($native.Count -gt 0)
    foreach ($call in $native) {
        Assert-True ($call.Extent.StartOffset -gt $gate[0].Extent.EndOffset)
        Assert-True ($call.CommandElements[0].Extent.Text -in @('git','$scExe','$mysqldPath','$pwshExe'))
    }
    foreach ($name in @('Assert-ApprovedAcl','Assert-SnapshotEqual','Get-ServiceState','Old-InstanceFingerprint')) {
        Assert-True (@($calls | Where-Object {$_.GetCommandName() -eq $name -and $_.Extent.EndOffset -lt $gate[0].Extent.StartOffset}).Count -gt 0)
    }
}
Test-Case 'only MySQL invocation is no-defaults version query' {
    $mysql=@($calls | Where-Object {$_.CommandElements[0].Extent.Text -eq '$mysqldPath'})
    Assert-True ($mysql.Count -eq 1)
    Assert-True (($mysql[0].CommandElements.Extent.Text -join ' ') -ceq '$mysqldPath --no-defaults --version')
}
Test-Case 'backup semantic/hash gate precedes log isolation and all directory grants' {
    $backupCheck=@($calls | Where-Object {$_.GetCommandName() -eq 'Assert-BackupIntegrity'})
    $logWrite=@($calls | Where-Object {$_.GetCommandName() -eq 'Set-Acl' -and $_.Extent.Text -match '\$logPath'})
    $grants=@($calls | Where-Object {$_.GetCommandName() -eq 'Add-ServiceAccess'})
    Assert-True ($backupCheck.Count -eq 1 -and $logWrite.Count -eq 1 -and $grants.Count -eq 6)
    Assert-True ($backupCheck[0].Extent.EndOffset -lt $logWrite[0].Extent.StartOffset)
    foreach ($grant in $grants) { Assert-True ($grant.Extent.StartOffset -gt $logWrite[0].Extent.EndOffset) }
    Assert-True ($main.Extent.Text.Contains('FileMode]::CreateNew'))
    Assert-True ($main.Extent.Text.Contains('$stream.Flush($true)'))
    Assert-True ($main.Extent.Text.Contains("'Backup changed during verification'"))
}
Test-Case 'no service mutation, file deletion, SQL or initialization commands' {
    $all=@($ast.FindAll({param($node) $node -is [System.Management.Automation.Language.CommandAst]},$true))
    $forbidden=@('Start-Service','Stop-Service','Restart-Service','Set-Service','New-Service','Remove-Service',
                 'Remove-Item','Clear-Content','Move-Item','Rename-Item','Start-Process','Invoke-Expression')
    Assert-True (@($all | Where-Object {$_.GetCommandName() -in $forbidden}).Count -eq 0)
    Assert-True (-not ($ast.Extent.Text -match '--initialize|--install|--remove'))
    $git=@($calls | Where-Object {$_.GetCommandName() -eq 'git'})
    Assert-True ($git.Count -eq 3)
    foreach ($call in $git) { Assert-True ($call.Extent.Text -match '--no-optional-locks (branch|-c core.quotepath=false status)') }
    Assert-True ($main.CatchClauses.Count -eq 1)
    Assert-True ($main.CatchClauses[0].Extent.Text -match 'exit 1')
}
Test-Case 'test harness never invokes target main or filesystem ACL writes' {
    Assert-True (@($definitions | Where-Object Name -EQ 'Add-ServiceAccess').Count -eq 1)
    # Only the explicitly selected pure definitions above are imported, never that mutator.
    Assert-True ($ast.Extent.Text.Contains('$principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)'))
    Assert-True ($ast.Extent.Text.Contains('if ($identity.User.Value -ne $maintenanceSid)'))
}
Write-Output "Service ACL review: $passed PASS; PowerShell=$($PSVersionTable.PSVersion); pure memory/AST only; target main NOT executed."
