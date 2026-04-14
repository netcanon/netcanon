#Requires -Version 5.1
<#
.SYNOPSIS
    Pulls running configurations from network devices via SSH.
.DESCRIPTION
    Connects to network devices, retrieves running configurations, and saves
    them as timestamped files. Device behaviour is driven by YAML definition
    files under ./definitions/<vendor>/<os>/<version>.yaml — add a new file
    there to support a new vendor, OS, or model without touching this script.

    Requires Posh-SSH and powershell-yaml modules (auto-installed on first run).

    Devices can be supplied via -Devices (hashtable array), -ConfigFile (JSON),
    or interactively when neither is provided.
.PARAMETER Devices
    Array of device hashtables. Each requires: Type, Host, Credential.
    Optional: Port (default 22), EnablePassword.
.PARAMETER ConfigFile
    Path to a JSON file defining devices. Credentials are prompted per device
    unless Username/Password fields are present in the file.
.PARAMETER LogFile
    Path to write a transcript log. Defaults to configs\backup_<timestamp>.log.
.PARAMETER Parallel
    Back up all devices concurrently. Requires PowerShell 7+.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory=$false)]
    [hashtable[]]$Devices,

    [Parameter(Mandatory=$false)]
    [string]$ConfigFile,

    [Parameter(Mandatory=$false)]
    [string]$LogFile,

    [Parameter(Mandatory=$false)]
    [switch]$Parallel
)

# --- Module Bootstrap ---
foreach ($mod in @('Posh-SSH', 'powershell-yaml')) {
    if (-not (Get-Module -ListAvailable -Name $mod)) {
        Write-Host "Installing $mod (current user scope)..." -ForegroundColor Yellow
        Install-Module -Name $mod -Scope CurrentUser -Force
    }
    Import-Module $mod -ErrorAction Stop
}

# --- Configuration ---
$ScriptDir      = if ($PSScriptRoot) { $PSScriptRoot } else { $PWD.Path }
$OutputDir      = Join-Path $ScriptDir "configs"
$DefinitionsDir = Join-Path $ScriptDir "definitions"
$Timestamp      = Get-Date -Format "yyyyMMdd_HHmmss"
$StreamReadTimeout = 120
$ReadInterval   = 200     # ms — read frequently to avoid buffer overflow on fast devices
$IdleThreshold  = 15      # 15 * 200ms = 3s idle before stopping

# --- Helper Functions ---

function Import-DeviceDefinitions {
    <#
    .SYNOPSIS
        Loads all *.yaml definition files from the definitions tree and returns
        a hashtable keyed by type_key. When multiple files share a type_key the
        one with the highest 'priority' field wins, enabling a base → specific
        override pattern: add a high-priority file for a quirky model without
        touching the base definition for that OS.
    #>
    [CmdletBinding()]
    param([string]$DefinitionsPath)

    if (-not (Test-Path $DefinitionsPath)) {
        throw "Definitions directory not found: $DefinitionsPath"
    }

    $files = Get-ChildItem -Path $DefinitionsPath -Recurse -Filter '*.yaml'

    if ($files.Count -eq 0) {
        throw "No definition files (*.yaml) found in: $DefinitionsPath"
    }

    # Pass 1 — parse all files and capture priority so we can sort before applying
    $pending = @()
    foreach ($file in $files) {
        try {
            $def      = Get-Content $file.FullName -Raw | ConvertFrom-Yaml
            $priority = if ($def.priority) { [int]$def.priority } else { 0 }
            $pending += [PSCustomObject]@{ Def = $def; File = $file; Priority = $priority }
        }
        catch {
            Write-Warning "Failed to parse $($file.FullName): $($_.Exception.Message)"
        }
    }

    # Pass 2 — apply in ascending priority order so higher-priority files win
    $profiles = @{}
    foreach ($item in ($pending | Sort-Object Priority)) {
        $def  = $item.Def
        $file = $item.File
        try {
            if ([string]::IsNullOrWhiteSpace($def.type_key)) {
                Write-Warning "Skipping $($file.Name): missing or empty 'type_key'"
                continue
            }

            # Coerce YAML sequences — ConvertFrom-Yaml may return null for empty lists
            $preCmd   = if ($def.commands.pre)     { [string[]]@($def.commands.pre)     } else { [string[]]@() }
            $postCmd  = if ($def.commands.post)    { [string[]]@($def.commands.post)    } else { [string[]]@() }
            $trailing = if ($def.prompts.trailing) { [string[]]@($def.prompts.trailing) } else { [string[]]@() }

            $profiles[$def.type_key] = @{
                # Operational — used by Get-DeviceConfig / Format-SSHOutput
                PreCommands            = $preCmd
                ConfigCommand          = [string]$def.commands.config
                PostCommands           = $postCmd
                NeedsEnable            = [bool]$def.connection.needs_enable
                CiscoMorePaging        = [bool]$def.connection.cisco_more_paging
                OpnsenseShellMenu      = [bool]$def.connection.opnsense_shell_menu
                FileExtension          = [string]$def.file_extension
                TrailingPromptPatterns = $trailing
                # Metadata — informational, for diagnostics and future use
                Vendor                 = [string]$def.vendor
                OS                     = [string]$def.os
                VersionMatch           = [string]$def.version_match
                Notes                  = [string]$def.notes
                SourceFile             = $file.FullName
            }

            Write-Verbose "  Loaded: $($def.type_key) (priority $($item.Priority)) <- $($file.Name)"
        }
        catch {
            Write-Warning "Failed to load $($file.FullName): $($_.Exception.Message)"
        }
    }

    if ($profiles.Count -eq 0) {
        throw "No valid definitions loaded from: $DefinitionsPath"
    }

    Write-Host "  Loaded $($profiles.Count) device definition(s) from definitions/" -ForegroundColor DarkGray
    return $profiles
}

function Format-SSHOutput {
    [CmdletBinding()]
    param(
        [string]$RawOutput,
        [string]$Command,
        # Default covers all current vendor prompt styles; overridden per-definition when
        # called from Get-DeviceConfig so only the relevant vendor's pattern is applied.
        [string[]]$TrailingPromptPatterns = @('^\S+[#>]\s*$', '^\[.+\]\s*>\s*$', '^root@\S+:.*[#$]\s*$')
    )

    $cleaned = $RawOutput -replace '\x1b\[[0-9;]*[a-zA-Z]', ''
    $cleaned = $cleaned -replace '\x1b\]0;[^\x07]*\x07', ''
    $cleaned = $cleaned -replace ' --More-- \s*', ''
    $cleaned = $cleaned -replace '--More--', ''
    $cleaned = $cleaned -replace "`r`n", "`n"
    $cleaned = $cleaned -replace "`r", "`n"

    $lines = $cleaned -split "`n"

    $startIndex = 0
    for ($i = 0; $i -lt $lines.Count; $i++) {
        if ($lines[$i] -match [regex]::Escape($Command)) {
            $startIndex = $i + 1
            break
        }
    }

    $endIndex = $lines.Count - 1
    while ($endIndex -gt $startIndex -and (
        $lines[$endIndex].Trim() -eq '' -or
        ($TrailingPromptPatterns | Where-Object { $lines[$endIndex] -match $_ }).Count -gt 0
    )) {
        $endIndex--
    }

    if ($startIndex -le $endIndex) {
        $lines = $lines[$startIndex..$endIndex]
    }

    return ($lines -join "`n").Trim()
}

function Get-DeviceConfig {
    [CmdletBinding()]
    param(
        [string]$DeviceType,
        [string]$HostAddress,
        [PSCredential]$Credential,
        [int]$Port = 22,
        [SecureString]$EnablePassword = $null
    )

    $profile = $DeviceProfiles[$DeviceType]
    if (-not $profile) {
        throw "No definition loaded for device type '$DeviceType'. Available: $($DeviceProfiles.Keys -join ', ')"
    }

    Write-Host "  Connecting to $HostAddress`:$Port..." -ForegroundColor Cyan

    $session = New-SSHSession -ComputerName $HostAddress -Credential $Credential -Port $Port -AcceptKey -Force -ConnectionTimeout 30 -ErrorAction Stop
    Write-Host "  Connected. Opening shell stream..." -ForegroundColor Cyan

    try {
        $stream = New-SSHShellStream -SSHSession $session -BufferSize 1048576 -ErrorAction Stop

        Start-Sleep -Seconds 2
        $initialOutput = ''
        while ($stream.DataAvailable) {
            $initialOutput += $stream.Read()
            Start-Sleep -Milliseconds 200
        }

        # OPNsense console menu detection
        if ($profile.OpnsenseShellMenu) {
            if ($initialOutput -match '8\)\s*Shell' -or $initialOutput -match 'Enter an option:') {
                Write-Host "  Detected OPNsense console menu, entering shell..." -ForegroundColor Yellow
                $stream.WriteLine('8')
                Start-Sleep -Seconds 3
                while ($stream.DataAvailable) { $null = $stream.Read(); Start-Sleep -Milliseconds 300 }
            }
        }

        # Cisco enable detection
        if ($profile.NeedsEnable -and $initialOutput -match '>\s*$') {
            Write-Host "  Detected user exec mode, sending enable..." -ForegroundColor Yellow
            $stream.WriteLine('enable')
            Start-Sleep -Milliseconds 1000

            $enableOutput = ''
            while ($stream.DataAvailable) {
                $enableOutput += $stream.Read()
                Start-Sleep -Milliseconds 200
            }

            if ($enableOutput -match '[Pp]assword') {
                if ($null -eq $EnablePassword) {
                    throw "Device requires enable password but none was provided."
                }
                $enablePwd = [System.Runtime.InteropServices.Marshal]::PtrToStringAuto(
                    [System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($EnablePassword)
                )
                $stream.WriteLine($enablePwd)
                Start-Sleep -Milliseconds 1000
                while ($stream.DataAvailable) { $null = $stream.Read(); Start-Sleep -Milliseconds 200 }
            }
        }

        # Send pre-commands
        foreach ($cmd in $profile.PreCommands) {
            Write-Host "  Sending: $cmd" -ForegroundColor Gray
            $stream.WriteLine($cmd)
            Start-Sleep -Milliseconds 2000
            while ($stream.DataAvailable) { $null = $stream.Read(); Start-Sleep -Milliseconds 300 }
        }

        # Drain before config command
        Start-Sleep -Seconds 2
        while ($stream.DataAvailable) { $null = $stream.Read(); Start-Sleep -Milliseconds 300 }

        Write-Host "  Sending: $($profile.ConfigCommand)" -ForegroundColor Gray
        $stream.WriteLine($profile.ConfigCommand)

        $buffer       = ''
        $idleCount    = 0
        $elapsed      = 0
        $configStarted = $false
        $minWait      = 15000

        Write-Host "  Reading configuration (up to ${StreamReadTimeout}s)..." -ForegroundColor Cyan

        while ($elapsed -lt ($StreamReadTimeout * 1000)) {
            Start-Sleep -Milliseconds $ReadInterval
            $elapsed += $ReadInterval

            if ($stream.DataAvailable) {
                $chunk = $stream.Read()
                $buffer += $chunk
                $idleCount = 0

                if ($profile.CiscoMorePaging -and $chunk -match '--More--') {
                    $stream.Write(' ')
                }

                $lineCount = ($buffer -split "`n").Count
                if ($lineCount -gt 5) { $configStarted = $true }

                if ($lineCount % 100 -lt 2) {
                    Write-Host "  ... $lineCount lines so far" -ForegroundColor DarkGray
                }
            }
            else {
                $idleCount++
                if ($configStarted -and $idleCount -ge $IdleThreshold) { break }
                if ($elapsed -lt $minWait) { continue }
                if (-not $configStarted -and $buffer.Length -gt 0 -and $idleCount -ge 20) {
                    Write-Host "  WARNING: Only received preamble, no config data after $([int]($elapsed/1000))s" -ForegroundColor Yellow
                    break
                }
            }
        }

        if ($buffer.Length -eq 0) {
            throw "Timed out waiting for configuration output from $HostAddress"
        }

        $lineCount = ($buffer -split "`n").Count
        Write-Host "  Received $lineCount lines of output." -ForegroundColor Cyan
        Write-Verbose "  First line: $(($buffer -split "`n")[0].Trim())"
        Write-Verbose "  Last line:  $(($buffer -split "`n")[-1].Trim())"

        foreach ($cmd in $profile.PostCommands) {
            Write-Host "  Sending post-command: $cmd" -ForegroundColor Gray
            $stream.WriteLine($cmd)
            Start-Sleep -Milliseconds 1000
            while ($stream.DataAvailable) { $null = $stream.Read(); Start-Sleep -Milliseconds 200 }
        }

        return Format-SSHOutput -RawOutput $buffer -Command $profile.ConfigCommand `
                                -TrailingPromptPatterns $profile.TrailingPromptPatterns
    }
    finally {
        if ($session) {
            Remove-SSHSession -SSHSession $session -ErrorAction SilentlyContinue | Out-Null
            Write-Host "  Session closed." -ForegroundColor Cyan
        }
    }
}

function Save-Config {
    [CmdletBinding()]
    param(
        [string]$Config,
        [string]$DeviceType,
        [string]$HostAddress,
        [string]$OutputDirectory,
        [string]$Timestamp,
        [string]$FileExtension = 'cfg'
    )

    if (-not (Test-Path $OutputDirectory)) {
        New-Item -ItemType Directory -Path $OutputDirectory -Force | Out-Null
    }

    $safeHost = $HostAddress -replace '[\.\:]', '-'
    $fileName = "${DeviceType}_${safeHost}_${Timestamp}.${FileExtension}"
    $filePath = Join-Path $OutputDirectory $fileName

    [System.IO.File]::WriteAllText($filePath, $Config, [System.Text.UTF8Encoding]::new($false))

    return $filePath
}

# --- Main ---
Write-Host ""
Write-Host "======================================" -ForegroundColor Green
Write-Host "  Network Device Config Backup Tool"    -ForegroundColor Green
Write-Host "======================================" -ForegroundColor Green
Write-Host ""

if ($Devices -and $ConfigFile) {
    throw "-Devices and -ConfigFile cannot be used together."
}

if ($Parallel -and $PSVersionTable.PSVersion.Major -lt 7) {
    Write-Warning "-Parallel requires PowerShell 7 or later. Running sequentially."
    $Parallel = $false
}

# --- Start logging ---
if (-not (Test-Path $OutputDir)) {
    New-Item -ItemType Directory -Path $OutputDir -Force | Out-Null
}
if (-not $LogFile) {
    $LogFile = Join-Path $OutputDir "backup_${Timestamp}.log"
}
Start-Transcript -Path $LogFile -Append | Out-Null
Write-Host "Logging to: $LogFile" -ForegroundColor DarkGray
Write-Host ""

try {

# --- Load definitions ---
$DeviceProfiles = Import-DeviceDefinitions -DefinitionsPath $DefinitionsDir

# --- Load devices from ConfigFile ---
if ($ConfigFile) {
    if (-not (Test-Path $ConfigFile)) {
        throw "Config file not found: $ConfigFile"
    }
    $jsonDevices = Get-Content $ConfigFile -Raw | ConvertFrom-Json
    $Devices = @()
    foreach ($d in $jsonDevices) {
        $pwd = if (-not [string]::IsNullOrEmpty($d.Password)) {
            ConvertTo-SecureString $d.Password -AsPlainText -Force
        } else {
            Read-Host "  Enter password for $($d.Type) @ $($d.Host)" -AsSecureString
        }
        $cred = New-Object System.Management.Automation.PSCredential($d.Username, $pwd)

        $enablePwd = $null
        if ($DeviceProfiles[$d.Type].NeedsEnable) {
            if (-not [string]::IsNullOrEmpty($d.EnablePassword)) {
                $enablePwd = ConvertTo-SecureString $d.EnablePassword -AsPlainText -Force
            } else {
                $needsEnable = Read-Host "  Does $($d.Type) @ $($d.Host) need an enable password? (Y/N, default N)"
                if ($needsEnable -match '^[Yy]$') {
                    $enablePwd = Read-Host "  Enter enable password" -AsSecureString
                }
            }
        }

        $Devices += @{
            Type           = $d.Type
            Host           = $d.Host
            Port           = if ($d.Port) { [int]$d.Port } else { 22 }
            Credential     = $cred
            EnablePassword = $enablePwd
        }
    }
}

# --- Interactive prompt if no devices provided ---
if (-not $Devices) {
    $Devices = @()
    foreach ($deviceType in ($DeviceProfiles.Keys | Sort-Object)) {
        $def = $DeviceProfiles[$deviceType]
        Write-Host "--- $deviceType ($($def.Vendor) $($def.OS)) ---" -ForegroundColor White
        $hostAddr = Read-Host "  Enter hostname or IP address (leave blank to skip)"

        if ([string]::IsNullOrWhiteSpace($hostAddr)) {
            Write-Host "  Skipping $deviceType." -ForegroundColor Yellow
            Write-Host ""
            continue
        }

        $portInput = Read-Host "  Enter SSH port (default 22)"
        $port = if ([string]::IsNullOrWhiteSpace($portInput)) { 22 } else { [int]$portInput }

        $username    = Read-Host "  Enter username"
        $secPassword = Read-Host "  Enter password" -AsSecureString
        $credential  = New-Object System.Management.Automation.PSCredential($username, $secPassword)

        $enablePwd = $null
        if ($def.NeedsEnable) {
            $needsEnable = Read-Host "  Does this device need an enable password? (Y/N, default N)"
            if ($needsEnable -match '^[Yy]$') {
                $enablePwd = Read-Host "  Enter enable password" -AsSecureString
            }
        }

        $Devices += @{
            Type           = $deviceType
            Host           = $hostAddr
            Port           = $port
            Credential     = $credential
            EnablePassword = $enablePwd
        }
        Write-Host ""
    }
}

# --- Run backups ---
$results = @()

if ($Parallel) {
    $formatFnDef    = ${function:Format-SSHOutput}.ToString()
    $getConfigFnDef = ${function:Get-DeviceConfig}.ToString()
    $saveFnDef      = ${function:Save-Config}.ToString()

    $results = $Devices | ForEach-Object -Parallel {
        $global:DeviceProfiles    = $using:DeviceProfiles
        $global:StreamReadTimeout = $using:StreamReadTimeout
        $global:ReadInterval      = $using:ReadInterval
        $global:IdleThreshold     = $using:IdleThreshold

        New-Item -Path Function:Format-SSHOutput -Value ([scriptblock]::Create($using:formatFnDef))    | Out-Null
        New-Item -Path Function:Get-DeviceConfig -Value ([scriptblock]::Create($using:getConfigFnDef)) | Out-Null
        New-Item -Path Function:Save-Config      -Value ([scriptblock]::Create($using:saveFnDef))      | Out-Null

        Import-Module Posh-SSH -ErrorAction Stop

        $dev       = $_
        $OutputDir = $using:OutputDir
        $Timestamp = $using:Timestamp

        Write-Host "--- $($dev.Type) ---" -ForegroundColor White
        try {
            $config = Get-DeviceConfig -DeviceType $dev.Type -HostAddress $dev.Host `
                        -Credential $dev.Credential -Port $dev.Port -EnablePassword $dev.EnablePassword

            if ([string]::IsNullOrWhiteSpace($config)) {
                Write-Warning "  Received empty configuration from $($dev.Host). Saving anyway."
            }

            $ext = $global:DeviceProfiles[$dev.Type].FileExtension
            if (-not $ext) { $ext = 'cfg' }

            $filePath = Save-Config -Config $config -DeviceType $dev.Type -HostAddress $dev.Host `
                          -OutputDirectory $OutputDir -Timestamp $Timestamp -FileExtension $ext
            Write-Host "  Saved: $filePath" -ForegroundColor Green
            Write-Host ""

            [PSCustomObject]@{ Device=$dev.Host; Type=$dev.Type; Status='Success'; File=$filePath; Error=$null }
        }
        catch {
            Write-Host "  FAILED: $($_.Exception.Message)" -ForegroundColor Red
            Write-Host ""
            [PSCustomObject]@{ Device=$dev.Host; Type=$dev.Type; Status='Failed'; File=$null; Error=$_.Exception.Message }
        }
    } -ThrottleLimit 10
}
else {
    foreach ($dev in $Devices) {
        Write-Host "--- $($dev.Type) ---" -ForegroundColor White
        try {
            $config = Get-DeviceConfig -DeviceType $dev.Type -HostAddress $dev.Host `
                        -Credential $dev.Credential -Port $dev.Port -EnablePassword $dev.EnablePassword

            if ([string]::IsNullOrWhiteSpace($config)) {
                Write-Warning "  Received empty configuration from $($dev.Host). Saving anyway."
            }

            $ext = $DeviceProfiles[$dev.Type].FileExtension
            if (-not $ext) { $ext = 'cfg' }

            $filePath = Save-Config -Config $config -DeviceType $dev.Type -HostAddress $dev.Host `
                          -OutputDirectory $OutputDir -Timestamp $Timestamp -FileExtension $ext
            Write-Host "  Saved: $filePath" -ForegroundColor Green

            $results += [PSCustomObject]@{ Device=$dev.Host; Type=$dev.Type; Status='Success'; File=$filePath; Error=$null }
        }
        catch {
            Write-Host "  FAILED: $($_.Exception.Message)" -ForegroundColor Red
            $results += [PSCustomObject]@{ Device=$dev.Host; Type=$dev.Type; Status='Failed'; File=$null; Error=$_.Exception.Message }
        }
        Write-Host ""
    }
}

# --- Summary ---
Write-Host "======================================" -ForegroundColor Green
Write-Host "  Backup Summary"                       -ForegroundColor Green
Write-Host "======================================" -ForegroundColor Green
$results | Format-Table -AutoSize -Property Device, Type, Status, File, Error

}
finally {
    Stop-Transcript | Out-Null
}
