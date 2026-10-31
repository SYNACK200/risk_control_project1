#requires -Version 7.2
<#
Run ONCE in an elevated PowerShell 7 terminal as the approved maintenance user.
Only prepares ACLs for the already registered, STOPPED RiskControlMySQL84.
Never reads initialize.err contents, starts services, initializes data or runs SQL.
Any mismatch stops; partial changes are preserved, never automatically restored.
#>
[CmdletBinding()]
param()
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$root = 'D:\RiskControlDemo\mysql84'
$parent = 'D:\RiskControlDemo'
$backupRoot = 'C:\ProgramData\RiskControlDemoAclBackup'
$maintenanceSid = 'S-1-5-21-251875384-4178690216-1937418480-1001'
$baseSids = @($maintenanceSid,'S-1-5-18','S-1-5-32-544')
$expectedServiceSid = 'S-1-5-80-3787980702-3828273279-332142536-3330034793-389180887'
$runtimeHash = 'D88488116138E8F573BC0E470855614891E794BDB3C16C9DED949496BF2C0AC3'
$logPath = Join-Path $root 'logs\initialize.err'
$stage = 'elevation'
$locationPushed = $false
$backup = $null
$baselineValidated = $false
$mysqldPath = Join-Path $root 'server\bin\mysqld.exe'
$configPath = Join-Path $root 'conf\my.ini'
$pwshExe = Join-Path $PSHOME 'pwsh.exe'
$scExe = Join-Path ([Environment]::SystemDirectory) 'sc.exe'

function Get-Rules($Acl) {
    return @($Acl.GetAccessRules($true,$true,[Security.Principal.SecurityIdentifier]))
}

function Assert-NoReparse([string]$Path) {
    $walk = [IO.Path]::GetFullPath($Path)
    while ($walk) {
        if ((Get-Item -LiteralPath $walk -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) {
            throw 'Reparse path detected'
        }
        $walk = Split-Path -Path $walk -Parent
    }
}

function Assert-BaseAcl($Acl) {
    $rules = @(Get-Rules $Acl)
    if ($rules.Count -ne 3 -or @($rules.IdentityReference.Value | Select-Object -Unique).Count -ne 3) {
        throw 'Unexpected baseline rule set'
    }
    foreach ($rule in $rules) {
        if ($rule.IdentityReference.Value -notin $baseSids -or
            $rule.AccessControlType -ne 'Allow' -or
            $rule.FileSystemRights -ne [Security.AccessControl.FileSystemRights]::FullControl) {
            throw 'Unexpected baseline principal or rights'
        }
    }
}

function Assert-ApprovedAcl([string]$Path,$Acl,[bool]$Directory) {
    Assert-BaseAcl $Acl
    if ($Acl.GetOwner([Security.Principal.SecurityIdentifier]).Value -ne $maintenanceSid) { throw 'Owner baseline changed' }
    $isRoot = $Path -in @($parent,$root)
    if ($Acl.AreAccessRulesProtected -ne $isRoot) { throw 'Inheritance baseline changed' }
    $flags = [Security.AccessControl.InheritanceFlags]::None
    if ($Directory -and $Path -ne $parent) {
        $flags = [Security.AccessControl.InheritanceFlags]::ObjectInherit -bor
                 [Security.AccessControl.InheritanceFlags]::ContainerInherit
    }
    foreach ($rule in @(Get-Rules $Acl)) {
        if ($rule.IsInherited -ne (-not $isRoot) -or $rule.InheritanceFlags -ne $flags -or
            $rule.PropagationFlags -ne [Security.AccessControl.PropagationFlags]::None) {
            throw 'ACE inheritance/propagation baseline changed'
        }
    }
}

function Assert-SnapshotPath([string]$Path) {
    if (-not $Path -or $Path -cne [IO.Path]::GetFullPath($Path) -or
        ($Path -ne $parent -and $Path -ne $root -and
         -not $Path.StartsWith($root+'\',[StringComparison]::OrdinalIgnoreCase))) {
        throw 'Snapshot path outside the fixed instance scope or not canonical'
    }
}

function Assert-SnapshotEqual([object[]]$Expected,[object[]]$Actual,[int]$Count = 523) {
    if ($Expected.Count -ne $Count -or $Actual.Count -ne $Count) { throw 'Snapshot object count mismatch' }
    $maps = @()
    foreach ($records in @(@{Items=$Expected},@{Items=$Actual})) {
        $map = [Collections.Generic.Dictionary[string,object]]::new([StringComparer]::OrdinalIgnoreCase)
        foreach ($record in $records.Items) {
            $names = @($record.PSObject.Properties.Name | Sort-Object)
            if (($names -join ',') -cne 'AccessSddl,OwnerSid,Path,Protected' -or
                $record.Path -isnot [string] -or $record.OwnerSid -isnot [string] -or
                $record.Protected -isnot [bool] -or $record.AccessSddl -isnot [string] -or
                -not $record.OwnerSid -or -not $record.AccessSddl) { throw 'Invalid snapshot fields/types' }
            Assert-SnapshotPath $record.Path
            if ($map.ContainsKey($record.Path)) { throw 'Duplicate snapshot path' }
            $map.Add($record.Path,$record)
        }
        $maps += ,$map
    }
    foreach ($path in $maps[0].Keys) {
        if (-not $maps[1].ContainsKey($path)) { throw 'Missing/extra snapshot path' }
        $left = $maps[0][$path]; $right = $maps[1][$path]
        if ($left.Path -cne $right.Path -or $left.OwnerSid -cne $right.OwnerSid -or
            $left.Protected -ne $right.Protected -or $left.AccessSddl -cne $right.AccessSddl) {
            throw 'Snapshot path/owner/protection/SDDL mismatch'
        }
    }
}

function Get-BytesSha256([byte[]]$Bytes) {
    return [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($Bytes))
}

function Assert-BackupIntegrity([object[]]$Expected,[object[]]$Actual,
                               [string]$ExpectedHash,[string]$ActualHash) {
    if ($ExpectedHash -cnotmatch '^[0-9A-F]{64}$' -or $ActualHash -cne $ExpectedHash) {
        throw 'Backup bytes SHA256 mismatch'
    }
    Assert-SnapshotEqual -Expected $Expected -Actual $Actual
}

function Set-PrivateManagementRules($Acl) {
    # Construct the entire explicit DACL in memory, then the caller persists ONCE.
    # Do not rely on Windows/.NET converting inherited ACE flags consistently.
    Assert-BaseAcl $Acl
    $Acl.SetAccessRuleProtection($true,$false)
    foreach ($rule in @(Get-Rules $Acl)) { $Acl.RemoveAccessRuleSpecific($rule) }
    $flags = [Security.AccessControl.InheritanceFlags]::None
    if ($Acl -is [Security.AccessControl.DirectorySecurity]) {
        $flags = [Security.AccessControl.InheritanceFlags]::ObjectInherit -bor
                 [Security.AccessControl.InheritanceFlags]::ContainerInherit
    }
    foreach ($sidText in $baseSids) {
        $rule = [Security.AccessControl.FileSystemAccessRule]::new(
            [Security.Principal.SecurityIdentifier]::new($sidText),
            [Security.AccessControl.FileSystemRights]::FullControl,
            $flags,[Security.AccessControl.PropagationFlags]::None,
            [Security.AccessControl.AccessControlType]::Allow)
        $Acl.AddAccessRule($rule)
    }
    return $Acl
}

function Get-ServiceState {
    $service = @(Get-CimInstance Win32_Service -Filter "Name='RiskControlMySQL84'")
    if ($service.Count -ne 1) { throw 'Expected exactly one registered Demo service' }
    $service = $service[0]
    $expected = '^"?D:\\RiskControlDemo\\mysql84\\server\\bin\\mysqld\.exe"?\s+--defaults-file=(?:"D:\\RiskControlDemo\\mysql84\\conf\\my\.ini"|D:\\RiskControlDemo\\mysql84\\conf\\my\.ini)\s+RiskControlMySQL84$'
    if ($service.State -ne 'Stopped' -or $service.ProcessId -ne 0 -or
        $service.StartMode -ne 'Manual' -or $service.StartName -ne 'NT SERVICE\RiskControlMySQL84' -or
        $service.PathName -notmatch $expected) { throw 'Service state/identity/configuration mismatch' }
    $sidType = (Get-ItemProperty -LiteralPath 'HKLM:\SYSTEM\CurrentControlSet\Services\RiskControlMySQL84' -Name ServiceSidType).ServiceSidType
    if ($sidType -ne 1) { throw 'Expected UNRESTRICTED service SID type' }
    return $service
}

function New-ServiceRule([Security.Principal.SecurityIdentifier]$Sid,
                         [Security.AccessControl.FileSystemRights]$Rights,
                         [bool]$Inherit) {
    $flags = [Security.AccessControl.InheritanceFlags]::None
    if ($Inherit) {
        $flags = [Security.AccessControl.InheritanceFlags]::ObjectInherit -bor
                 [Security.AccessControl.InheritanceFlags]::ContainerInherit
    }
    return [Security.AccessControl.FileSystemAccessRule]::new(
        $Sid,$Rights,$flags,[Security.AccessControl.PropagationFlags]::None,
        [Security.AccessControl.AccessControlType]::Allow)
}

function Add-ServiceAccess([string]$Path,[Security.AccessControl.FileSystemRights]$Rights,[bool]$Inherit) {
    $null = Get-ServiceState
    Assert-NoReparse $Path
    $acl = Get-Acl -LiteralPath $Path
    Assert-BaseAcl $acl
    $acl.AddAccessRule((New-ServiceRule $serviceSid $Rights $Inherit))
    Set-Acl -LiteralPath $Path -AclObject $acl
}

function Old-InstanceFingerprint {
    $old = @(Get-CimInstance Win32_Service -Filter "Name='MySQL80'")
    if ($old.Count -ne 1 -or $old[0].State -ne 'Running') { throw 'MySQL80 not running' }
    $listeners = @(Get-NetTCPConnection -State Listen | Where-Object LocalPort -EQ 3306)
    if (-not $listeners.Count) { throw 'Old listener missing' }
    foreach ($listener in $listeners) {
        $process = Get-CimInstance Win32_Process -Filter "ProcessId=$($listener.OwningProcess)"
        if ($process.ProcessId -ne $old[0].ProcessId -and $process.ParentProcessId -ne $old[0].ProcessId) {
            throw 'Old listener identity mismatch'
        }
    }
    return [ordered]@{
        Service = ($old | Select-Object Name,State,ProcessId,PathName,StartMode,StartName | ConvertTo-Json -Compress)
        Listeners = ($listeners | Sort-Object LocalAddress,OwningProcess | Select-Object LocalAddress,LocalPort,OwningProcess | ConvertTo-Json -Compress)
    } | ConvertTo-Json -Compress
}

try {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [Security.Principal.WindowsPrincipal]::new($identity)
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw 'Elevated Windows administrator token required; no ACL changes performed'
    }
    if ($identity.User.Value -ne $maintenanceSid) { throw 'Approved maintenance identity required' }
    $repo = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\..')).Path
    Push-Location -LiteralPath $repo
    $locationPushed = $true
    $stage = 'read-only baseline'
    # No native program (including git/sc/MySQL/preflight) executes before this gate.
    foreach ($path in @($parent,$root,$mysqldPath,$configPath,$logPath)) { Assert-NoReparse $path }
    $null = Get-ServiceState
    $serviceSid = ([Security.Principal.NTAccount]::new('NT SERVICE\RiskControlMySQL84')).Translate([Security.Principal.SecurityIdentifier])
    if ($serviceSid.Value -ne $expectedServiceSid) { throw 'Service SID mismatch' }
    $oldBefore = Old-InstanceFingerprint
    if (@(Get-NetTCPConnection -State Listen | Where-Object LocalPort -EQ 3307).Count) { throw '3307 occupied' }
    $items = @(Get-Item -LiteralPath $parent) + @(Get-Item -LiteralPath $root) + @(Get-ChildItem -LiteralPath $root -Recurse -Force)
    if ($items.Count -ne 523) { throw 'Object baseline changed; stop for review' }
    $snapshot = foreach ($item in $items) {
        Assert-NoReparse $item.FullName
        $acl = Get-Acl -LiteralPath $item.FullName
        Assert-ApprovedAcl $item.FullName $acl $item.PSIsContainer
        [pscustomobject]@{
            Path=$item.FullName
            OwnerSid=$maintenanceSid
            Protected=$acl.AreAccessRulesProtected
            AccessSddl=$acl.GetSecurityDescriptorSddlForm([Security.AccessControl.AccessControlSections]::Access)
        }
    }
    Assert-SnapshotEqual -Expected $snapshot -Actual $snapshot
    foreach ($path in @($mysqldPath,$configPath,$logPath,
                         (Join-Path $root 'server\bin\mysql.exe'),(Join-Path $root 'server\bin\mysqladmin.exe'))) {
        Assert-SnapshotPath $path
        if ($path -cnotin $snapshot.Path -or -not (Test-Path -LiteralPath $path -PathType Leaf)) {
            throw 'Required executable/configuration/log missing from approved object scope'
        }
    }
    if ((Get-FileHash -LiteralPath $configPath).Hash -ne $runtimeHash) { throw 'Runtime config changed' }
    $log = Get-Item -LiteralPath $logPath -Force
    if ($log.PSIsContainer -or $log.Length -le 0) { throw 'Expected existing nonempty initialization log' }
    Assert-NoReparse $backupRoot
    $backupAcl = Get-Acl -LiteralPath $backupRoot
    Assert-BaseAcl $backupAcl
    if (-not $backupAcl.AreAccessRulesProtected) { throw 'Backup root must be protected' }
    if ($backupAcl.GetOwner([Security.Principal.SecurityIdentifier]).Value -ne $maintenanceSid) { throw 'Backup owner mismatch' }
    $null = Get-ServiceState
    if ((Old-InstanceFingerprint) -cne $oldBefore) { throw 'MySQL80 changed during baseline inspection' }
    $baselineValidated = $true

    $stage = 'verified external read-only queries'
    if (-not $baselineValidated) { throw 'Baseline gate not completed' }
    $branch = & git --no-optional-locks branch --show-current
    if ($LASTEXITCODE -ne 0 -or $branch -ne 'feat/data-bootstrap') { throw 'Unexpected Git workspace' }
    $gitBefore = @(& git --no-optional-locks -c core.quotepath=false status --porcelain=v1 --untracked-files=all)
    if ($LASTEXITCODE -ne 0) { throw 'Cannot inspect Git state' }
    foreach ($operation in @('qc','qsidtype','showsid')) {
        & $scExe $operation RiskControlMySQL84
        if ($LASTEXITCODE -ne 0) { throw 'Service query failed' }
    }
    $version = & $mysqldPath --no-defaults --version
    if ($LASTEXITCODE -ne 0 -or "$version" -notmatch 'Ver 8\.4\.13 ') { throw 'Expected server 8.4.13' }
    & $pwshExe -NoProfile -File (Join-Path $PSScriptRoot 'preflight.ps1') -Mode Ready -Phase BeforeStart
    if ($LASTEXITCODE -ne 0) { throw 'BeforeStart identity preflight failed' }

    $stage = 'protected ACL metadata backup'
    $backup = Join-Path $backupRoot ('service-acl-20261030-' + [guid]::NewGuid().ToString('N'))
    if (Test-Path -LiteralPath $backup) { throw 'Backup path occupied' }
    $null = [IO.Directory]::CreateDirectory($backup)
    $acl = Get-Acl -LiteralPath $backup
    Assert-BaseAcl $acl
    $acl = Set-PrivateManagementRules $acl
    Set-Acl -LiteralPath $backup -AclObject $acl
    $snapshotPath = Join-Path $backup 'before-service-acl.json'
    $bytes = [Text.UTF8Encoding]::new($false).GetBytes(($snapshot | ConvertTo-Json -Depth 4))
    $expectedBackupHash = Get-BytesSha256 $bytes
    $stream = [IO.File]::Open($snapshotPath,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::None)
    try { $stream.Write($bytes,0,$bytes.Length); $stream.Flush($true) } finally { $stream.Dispose() }
    Assert-BaseAcl (Get-Acl -LiteralPath $snapshotPath)
    $saved = @(Get-Content -LiteralPath $snapshotPath -Raw -Encoding UTF8 | ConvertFrom-Json)
    $actualBackupHash = (Get-FileHash -LiteralPath $snapshotPath -Algorithm SHA256).Hash
    Assert-BackupIntegrity -Expected $snapshot -Actual $saved -ExpectedHash $expectedBackupHash -ActualHash $actualBackupHash
    # Rehash after semantic validation as well; never enter real-instance ACL writes on mismatch.
    if ((Get-FileHash -LiteralPath $snapshotPath -Algorithm SHA256).Hash -cne $expectedBackupHash) { throw 'Backup changed during verification' }
    Write-Output "ACL_METADATA_BACKUP=$backup"
    Write-Output "ACL_METADATA_SHA256=$((Get-FileHash -LiteralPath $snapshotPath).Hash)"

    $stage = 'protect initialization credential log BEFORE directory grants'
    $null = Get-ServiceState
    $acl = Get-Acl -LiteralPath $logPath
    Assert-BaseAcl $acl
    $acl = Set-PrivateManagementRules $acl
    Set-Acl -LiteralPath $logPath -AclObject $acl
    $acl = Get-Acl -LiteralPath $logPath
    Assert-BaseAcl $acl
    if (-not $acl.AreAccessRulesProtected -or @(Get-Rules $acl | Where-Object IsInherited).Count) {
        throw 'Initialization log isolation failed; no directory grants allowed'
    }

    $stage = 'bounded directory grants'
    Add-ServiceAccess $parent ReadAndExecute $false
    Add-ServiceAccess $root ReadAndExecute $false
    Add-ServiceAccess (Join-Path $root 'conf') ReadAndExecute $true
    Add-ServiceAccess (Join-Path $root 'server') ReadAndExecute $true
    Add-ServiceAccess (Join-Path $root 'data') Modify $true
    Add-ServiceAccess (Join-Path $root 'logs') Modify $true

    $stage = 'verify every object and credential exception'
    $after = @(Get-Item -LiteralPath $parent) + @(Get-Item -LiteralPath $root) + @(Get-ChildItem -LiteralPath $root -Recurse -Force)
    if ($after.Count -ne $snapshot.Count -or @(Compare-Object @($snapshot.Path | Sort-Object) @($after.FullName | Sort-Object)).Count) {
        throw 'Object set changed during ACL operation'
    }
    foreach ($item in $after) {
        Assert-NoReparse $item.FullName
        $acl = Get-Acl -LiteralPath $item.FullName
        if ($acl.GetOwner([Security.Principal.SecurityIdentifier]).Value -ne $maintenanceSid) { throw 'Owner unexpectedly changed' }
        $rules = @(Get-Rules $acl)
        $base = @($rules | Where-Object { $_.IdentityReference.Value -in $baseSids })
        if ($base.Count -ne 3 -or @($base.IdentityReference.Value | Select-Object -Unique).Count -ne 3 -or
            @($base | Where-Object { $_.AccessControlType -ne 'Allow' -or $_.FileSystemRights -ne [Security.AccessControl.FileSystemRights]::FullControl }).Count) {
            throw 'Management rights were not preserved'
        }
        if ($item.FullName -eq $logPath) {
            Assert-BaseAcl $acl
            if (-not $acl.AreAccessRulesProtected -or @($rules | Where-Object IsInherited).Count) { throw 'Credential log no longer isolated' }
            continue
        }
        $serviceRules = @($rules | Where-Object { $_.IdentityReference.Value -eq $serviceSid.Value })
        $modify = $item.FullName -eq (Join-Path $root 'data') -or $item.FullName -eq (Join-Path $root 'logs') -or
            $item.FullName.StartsWith($root+'\data\',[StringComparison]::OrdinalIgnoreCase) -or
            $item.FullName.StartsWith($root+'\logs\',[StringComparison]::OrdinalIgnoreCase)
        $rights = if ($modify) { [Security.AccessControl.FileSystemRights]::Modify } else { [Security.AccessControl.FileSystemRights]::ReadAndExecute }
        $expectedRule = New-ServiceRule $serviceSid $rights $false
        if ($rules.Count -ne 4 -or $serviceRules.Count -ne 1 -or $serviceRules[0].AccessControlType -ne 'Allow' -or
            $serviceRules[0].FileSystemRights -ne $expectedRule.FileSystemRights) { throw 'Service rights mismatch or extra principal' }
        if ($acl.AreAccessRulesProtected -ne ($item.FullName -in @($parent,$root))) { throw 'Unexpected final inheritance protection' }
        if ($item.FullName -in @($parent,$root)) {
            if ($serviceRules[0].IsInherited -or $serviceRules[0].InheritanceFlags -ne 'None') { throw 'Parent/root grant must not propagate' }
        }
    }
    Assert-BaseAcl (Get-Acl -LiteralPath $backupRoot)
    Assert-BaseAcl (Get-Acl -LiteralPath $snapshotPath)
    if ((Old-InstanceFingerprint) -cne $oldBefore) { throw 'MySQL80 state changed; stop without changing it' }
    if ((Get-FileHash -LiteralPath (Join-Path $root 'conf\my.ini')).Hash -ne $runtimeHash) { throw 'Runtime config changed' }
    $null = Get-ServiceState
    $gitAfter = @(& git --no-optional-locks -c core.quotepath=false status --porcelain=v1 --untracked-files=all)
    if ($LASTEXITCODE -ne 0 -or ($gitBefore -join "`n") -cne ($gitAfter -join "`n")) { throw 'Git workspace changed unexpectedly' }
    & $pwshExe -NoProfile -File (Join-Path $PSScriptRoot 'preflight.ps1') -Mode Ready -Phase BeforeStart
    $readyExit = $LASTEXITCODE
    Write-Output "BEFORE_START_EXIT=$readyExit"
    if ($readyExit -ne 0) { throw 'Final identity preflight failed' }
    Write-Output 'ACL_PREPARATION_PASS: 523 objects verified; init log private; backup ungranted; MySQL80 unchanged.'
    Write-Output 'FIRST_START_PREREQUISITES_PASS: service remains STOPPED; first start still requires separate authorization.'
} catch {
    Write-Error -Message "STOP at stage [$stage]. Preserve partial state; no automatic restore/retry/start. No initialization log content was read." -ErrorAction Continue
    if ($backup) { Write-Output "PRESERVED_BACKUP=$backup" }
    exit 1
} finally {
    if ($locationPushed) { Pop-Location }
}
