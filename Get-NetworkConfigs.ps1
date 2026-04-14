#Requires -Version 5.1
<#
.SYNOPSIS
    Pulls running configurations from network devices via SSH.
.DESCRIPTION
    Connects to Fortigate, Cisco, OPNsense, and MikroTik devices, retrieves
    their running configurations, and saves them as timestamped files.
    Requires Posh-SSH module (auto-installs on first run).
.NOTES
    Fortigate: FortiOS 7.2.13
    Cisco:     IOS-XE 17.12.4
    OPNsense:  25.x
    MikroTik:  RouterOS 7.x
#>
param(
    [Parameter(Mandatory=$false)]
    [hashtable[]]$Devices
)

# --- Module Bootstrap ---
if (-not (Get-Module -ListAvailable -Name Posh-SSH)) {
    Write-Host "Installing Posh-SSH (current user scope)..." -ForegroundColor Yellow
    Install-Module -Name Posh-SSH -Scope CurrentUser -Force
}
Import-Module Posh-SSH -ErrorAction Stop

# --- Configuration ---
$ScriptDir = if ($PSScriptRoot) { $PSScriptRoot } else { $PWD.Path }
$OutputDir = Join-Path $ScriptDir "configs"
$Timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$StreamReadTimeout = 120
$ReadInterval = 200       # read frequently to avoid buffer overflow on fast devices
$IdleThreshold = 15       # 15 * 200ms = 3s of idle before stopping

$DeviceProfiles = @{
    'Fortigate' = @{
        PreCommands   = @('config system console', 'set output standard', 'end')
        ConfigCommand = 'show full-configuration'
        PostCommands  = @('config system console', 'set output more', 'end')
        NeedsEnable   = $false
        FileExtension = 'cfg'
    }
    'Cisco' = @{
        PreCommands   = @()
        ConfigCommand = 'show running-config'
        PostCommands  = @()
        NeedsEnable   = $true
        HandlePaging  = $true  # send space to bypass --More-- instead of terminal length 0
        FileExtension = 'cfg'
    }
    'OPNsense' = @{
        PreCommands   = @()
        ConfigCommand = 'cat /conf/config.xml'
        PostCommands  = @('exit')  # exit shell back to menu
        NeedsEnable   = $false
        NeedsShellMenu = $true    # OPNsense console menu — send "8" to enter shell
        FileExtension = 'xml'
    }
    'MikroTik' = @{
        PreCommands   = @()
        ConfigCommand = '/export verbose'
        PostCommands  = @()
        NeedsEnable   = $false
        FileExtension = 'rsc'
        PromptPattern = '^\[.+\]\s*>\s*$'  # [admin@MikroTik] >
    }
}

# --- Helper Functions ---

function Clean-SSHOutput {
    param(
        [string]$RawOutput,
        [string]$Command
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

    # Remove trailing prompt lines — covers Cisco (#/>), Fortigate (#), OPNsense (root@host:#), MikroTik ([user@host] >)
    $endIndex = $lines.Count - 1
    while ($endIndex -gt $startIndex -and (
        $lines[$endIndex].Trim() -eq '' -or
        $lines[$endIndex] -match '^\S+[#>]\s*$' -or
        $lines[$endIndex] -match '^\[.+\]\s*>\s*$' -or
        $lines[$endIndex] -match '^root@\S+:.*[#$]\s*$'
    )) {
        $endIndex--
    }

    if ($startIndex -le $endIndex) {
        $lines = $lines[$startIndex..$endIndex]
    }

    return ($lines -join "`n").Trim()
}

function Get-DeviceConfig {
    param(
        [string]$DeviceType,
        [string]$HostAddress,
        [PSCredential]$Credential,
        [int]$Port = 22,
        [SecureString]$EnablePassword = $null
    )

    $profile = $DeviceProfiles[$DeviceType]
    if (-not $profile) {
        throw "Unknown device type: $DeviceType"
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

        # OPNsense console menu detection — send "8" to enter shell
        if ($profile.NeedsShellMenu) {
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

        # Thorough drain before config command — ensure nothing is left in the buffer
        Start-Sleep -Seconds 2
        while ($stream.DataAvailable) { $null = $stream.Read(); Start-Sleep -Milliseconds 300 }

        # Send the config command
        Write-Host "  Sending: $($profile.ConfigCommand)" -ForegroundColor Gray
        $stream.WriteLine($profile.ConfigCommand)

        # Read output with timeout
        # Two phases: wait for meaningful data to start, then wait for it to stop.
        $buffer = ''
        $idleCount = 0
        $elapsed = 0
        $configStarted = $false
        $minWait = 15000  # always wait at least 15s before giving up

        Write-Host "  Reading configuration (up to ${StreamReadTimeout}s)..." -ForegroundColor Cyan

        while ($elapsed -lt ($StreamReadTimeout * 1000)) {
            Start-Sleep -Milliseconds $ReadInterval
            $elapsed += $ReadInterval

            if ($stream.DataAvailable) {
                $chunk = $stream.Read()
                $buffer += $chunk
                $idleCount = 0

                # Handle --More-- paging (Cisco IOS-XE)
                if ($profile.HandlePaging -and $chunk -match '--More--') {
                    $stream.Write(' ')
                }

                $lineCount = ($buffer -split "`n").Count
                if ($lineCount -gt 5) {
                    $configStarted = $true
                }

                # Progress indicator every 100 lines
                if ($lineCount % 100 -lt 2) {
                    Write-Host "  ... $lineCount lines so far" -ForegroundColor DarkGray
                }
            } else {
                $idleCount++
                # Only stop if config data has actually started flowing and then stopped
                if ($configStarted -and $idleCount -ge $IdleThreshold) {
                    break
                }
                # Don't give up before minWait even if nothing has come
                if ($elapsed -lt $minWait) {
                    continue
                }
                # If we've waited past minWait and still only have preamble, keep waiting
                # but if absolutely nothing has come, bail
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

        # Debug: show first and last few lines
        $debugLines = ($buffer -split "`n")
        Write-Host "  First line: $($debugLines[0].Trim())" -ForegroundColor DarkGray
        if ($debugLines.Count -gt 1) {
            Write-Host "  Last line:  $($debugLines[-1].Trim())" -ForegroundColor DarkGray
        }

        # Send post-commands (e.g., revert paging settings)
        if ($profile.PostCommands) {
            foreach ($cmd in $profile.PostCommands) {
                Write-Host "  Sending post-command: $cmd" -ForegroundColor Gray
                $stream.WriteLine($cmd)
                Start-Sleep -Milliseconds 1000
                while ($stream.DataAvailable) { $null = $stream.Read(); Start-Sleep -Milliseconds 200 }
            }
        }

        $config = Clean-SSHOutput -RawOutput $buffer -Command $profile.ConfigCommand
        return $config
    }
    finally {
        if ($session) {
            Remove-SSHSession -SSHSession $session -ErrorAction SilentlyContinue | Out-Null
            Write-Host "  Session closed." -ForegroundColor Cyan
        }
    }
}

function Save-Config {
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

# If no devices passed as parameter, prompt interactively
if (-not $Devices) {
    $Devices = @()
    foreach ($deviceType in @('Fortigate', 'Cisco', 'OPNsense', 'MikroTik')) {
        Write-Host "--- $deviceType Configuration Backup ---" -ForegroundColor White
        $hostAddr = Read-Host "  Enter $deviceType hostname or IP address"

        if ([string]::IsNullOrWhiteSpace($hostAddr)) {
            Write-Host "  Skipping $deviceType (no host provided)." -ForegroundColor Yellow
            Write-Host ""
            continue
        }

        $portInput = Read-Host "  Enter SSH port (default 22)"
        $port = if ([string]::IsNullOrWhiteSpace($portInput)) { 22 } else { [int]$portInput }

        $username = Read-Host "  Enter username"
        $secPassword = Read-Host "  Enter password" -AsSecureString
        $credential = New-Object System.Management.Automation.PSCredential($username, $secPassword)

        $enablePwd = $null
        if ($DeviceProfiles[$deviceType].NeedsEnable) {
            $needsEnable = Read-Host "  Does this device need an enable password? (Y/N, default N)"
            if ($needsEnable -eq 'Y') {
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

$results = @()

foreach ($dev in $Devices) {
    Write-Host "--- $($dev.Type) Configuration Backup ---" -ForegroundColor White
    try {
        $config = Get-DeviceConfig -DeviceType $dev.Type -HostAddress $dev.Host -Credential $dev.Credential -Port $dev.Port -EnablePassword $dev.EnablePassword

        if ([string]::IsNullOrWhiteSpace($config)) {
            Write-Warning "  Received empty configuration from $($dev.Host). Saving anyway."
        }

        $ext = if ($DeviceProfiles[$dev.Type].FileExtension) { $DeviceProfiles[$dev.Type].FileExtension } else { 'cfg' }
        $filePath = Save-Config -Config $config -DeviceType $dev.Type -HostAddress $dev.Host -OutputDirectory $OutputDir -Timestamp $Timestamp -FileExtension $ext
        Write-Host "  Saved: $filePath" -ForegroundColor Green

        $results += [PSCustomObject]@{
            Device = $dev.Host
            Type   = $dev.Type
            Status = 'Success'
            File   = $filePath
        }
    }
    catch {
        Write-Host "  FAILED: $($_.Exception.Message)" -ForegroundColor Red
        $results += [PSCustomObject]@{
            Device = $dev.Host
            Type   = $dev.Type
            Status = 'Failed'
            File   = $_.Exception.Message
        }
    }
    Write-Host ""
}

# --- Summary ---
Write-Host "======================================" -ForegroundColor Green
Write-Host "  Backup Summary"                       -ForegroundColor Green
Write-Host "======================================" -ForegroundColor Green
$results | Format-Table -AutoSize -Property Device, Type, Status, File
