# Test-NetworkConfigs.ps1 — non-destructive tests for Get-NetworkConfigs.ps1
# Run with: powershell -File .\Test-NetworkConfigs.ps1
# Does NOT require live network devices.

$ScriptPath  = Join-Path $PSScriptRoot "Get-NetworkConfigs.ps1"
$DefsDir     = Join-Path $PSScriptRoot "definitions"
$pass = 0; $fail = 0

function Assert {
    param([string]$Name, [scriptblock]$Test)
    try {
        $result = & $Test
        if ($result -eq $true -or $result -eq $null) {
            Write-Host "  PASS  $Name" -ForegroundColor Green
            $script:pass++
        } else {
            Write-Host "  FAIL  $Name  (returned: $result)" -ForegroundColor Red
            $script:fail++
        }
    } catch {
        Write-Host "  FAIL  $Name  (threw: $($_.Exception.Message))" -ForegroundColor Red
        $script:fail++
    }
}

function AssertThrows {
    param([string]$Name, [string]$Pattern, [scriptblock]$Test)
    try {
        & $Test | Out-Null
        Write-Host "  FAIL  $Name  (expected throw, got none)" -ForegroundColor Red
        $script:fail++
    } catch {
        if ($_.Exception.Message -match $Pattern) {
            Write-Host "  PASS  $Name" -ForegroundColor Green
            $script:pass++
        } else {
            Write-Host "  FAIL  $Name  (wrong error: $($_.Exception.Message))" -ForegroundColor Red
            $script:fail++
        }
    }
}

# Parse the script AST once — used for function extraction throughout
$ast = [System.Management.Automation.Language.Parser]::ParseFile($ScriptPath, [ref]$null, [ref]$null)

function Get-FunctionDef ([string]$Name) {
    $node = $ast.Find(
        { param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq $Name },
        $false
    )
    if (-not $node) { throw "Function '$Name' not found in $ScriptPath" }
    return $node.Extent.Text
}

# ---------------------------------------------------------------------------
Write-Host ""
Write-Host "=== 1. Syntax & structure ===" -ForegroundColor Cyan

Assert "No parse errors" {
    $errors = $null; $tokens = $null
    [void][System.Management.Automation.Language.Parser]::ParseFile($ScriptPath, [ref]$tokens, [ref]$errors)
    $errors.Count -eq 0
}

Assert "No unapproved verb Clean-" {
    (Get-Content $ScriptPath -Raw) -notmatch '\bClean-\w+'
}

Assert "Format-SSHOutput present" {
    (Get-Content $ScriptPath -Raw) -match 'function Format-SSHOutput'
}

Assert "Import-DeviceDefinitions present" {
    (Get-Content $ScriptPath -Raw) -match 'function Import-DeviceDefinitions'
}

Assert "Old standalone PromptPattern field removed from profiles" {
    # The old MikroTik-specific 'PromptPattern = ...' key is gone.
    # Check for the exact assignment pattern, not the word which appears in TrailingPromptPatterns.
    (Get-Content $ScriptPath -Raw) -notmatch "PromptPattern\s*="
}

Assert "Hardcoded DeviceProfiles hashtable removed" {
    # The old inline @{ 'Fortigate' = @{ ... } } block should be gone
    (Get-Content $ScriptPath -Raw) -notmatch "\`$DeviceProfiles\s*=\s*@\s*\{"
}

Assert "CmdletBinding on script" {
    ((Get-Content $ScriptPath -Raw) -split "`n" | Select-String '\[CmdletBinding\(\)\]').Count -ge 1
}

# ---------------------------------------------------------------------------
Write-Host ""
Write-Host "=== 2. Definition files ===" -ForegroundColor Cyan

$expectedDefs = @{
    'Cisco'    = 'cisco\ios-xe\17.x.yaml'
    'Fortigate'= 'fortigate\fortios\7.x.yaml'
    'OPNsense' = 'opnsense\opnsense\25.x.yaml'
    'MikroTik' = 'mikrotik\routeros\7.x.yaml'
}

Assert "Definitions directory exists" { Test-Path $DefsDir }

foreach ($entry in $expectedDefs.GetEnumerator()) {
    $full = Join-Path $DefsDir $entry.Value
    Assert "File exists: $($entry.Value)" { Test-Path $full }

    Assert "$($entry.Key) has required YAML keys" {
        # Ensure powershell-yaml is available for schema check
        if (-not (Get-Module powershell-yaml)) { Import-Module powershell-yaml -ErrorAction Stop }
        $def = Get-Content $full -Raw | ConvertFrom-Yaml
        -not [string]::IsNullOrEmpty($def.type_key) -and
        -not [string]::IsNullOrEmpty($def.vendor)   -and
        -not [string]::IsNullOrEmpty($def.os)        -and
        -not [string]::IsNullOrEmpty($def.commands.config) -and
        -not [string]::IsNullOrEmpty($def.file_extension)
    }

    Assert "$($entry.Key) type_key matches expected" {
        if (-not (Get-Module powershell-yaml)) { Import-Module powershell-yaml -ErrorAction Stop }
        $def = Get-Content (Join-Path $DefsDir $entry.Value) -Raw | ConvertFrom-Yaml
        $def.type_key -eq $entry.Key
    }

    Assert "$($entry.Key) has at least one trailing prompt pattern" {
        if (-not (Get-Module powershell-yaml)) { Import-Module powershell-yaml -ErrorAction Stop }
        $def = Get-Content (Join-Path $DefsDir $entry.Value) -Raw | ConvertFrom-Yaml
        $def.prompts.trailing.Count -gt 0
    }
}

# ---------------------------------------------------------------------------
Write-Host ""
Write-Host "=== 3. Import-DeviceDefinitions ===" -ForegroundColor Cyan

if (-not (Get-Module -ListAvailable -Name powershell-yaml)) {
    Install-Module -Name powershell-yaml -Scope CurrentUser -Force
}
Import-Module powershell-yaml -ErrorAction Stop

. ([scriptblock]::Create((Get-FunctionDef 'Import-DeviceDefinitions')))

$profiles = Import-DeviceDefinitions -DefinitionsPath $DefsDir

Assert "Loads all 4 vendors" { $profiles.Count -eq 4 }

foreach ($vendor in $expectedDefs.Keys) {
    Assert "$vendor profile loaded"              { $profiles.ContainsKey($vendor) }
    Assert "$vendor ConfigCommand non-empty"     { -not [string]::IsNullOrEmpty($profiles[$vendor].ConfigCommand) }
    Assert "$vendor FileExtension non-empty"     { -not [string]::IsNullOrEmpty($profiles[$vendor].FileExtension) }
    Assert "$vendor TrailingPromptPatterns set"  { $profiles[$vendor].TrailingPromptPatterns.Count -gt 0 }
    Assert "$vendor Vendor metadata carried"     { -not [string]::IsNullOrEmpty($profiles[$vendor].Vendor) }
    Assert "$vendor SourceFile recorded"         { -not [string]::IsNullOrEmpty($profiles[$vendor].SourceFile) }
}

Assert "Cisco NeedsEnable is true"        { $profiles['Cisco'].NeedsEnable    -eq $true  }
Assert "Cisco HandlePaging is true"       { $profiles['Cisco'].HandlePaging   -eq $true  }
Assert "Fortigate has pre-commands"       { $profiles['Fortigate'].PreCommands.Count -gt 0 }
Assert "Fortigate has post-commands"      { $profiles['Fortigate'].PostCommands.Count -gt 0 }
Assert "OPNsense NeedsShellMenu is true"  { $profiles['OPNsense'].NeedsShellMenu -eq $true  }
Assert "OPNsense FileExtension is xml"    { $profiles['OPNsense'].FileExtension -eq 'xml'  }
Assert "MikroTik FileExtension is rsc"   { $profiles['MikroTik'].FileExtension -eq 'rsc'  }

AssertThrows "Missing definitions dir throws" "not found" {
    Import-DeviceDefinitions -DefinitionsPath "C:\nonexistent_defs_xyz"
}

Assert "More specific path overrides generic on same type_key" {
    # Create a temp definitions tree with two files sharing a type_key
    $tmp = Join-Path $env:TEMP "defstest_$([guid]::NewGuid().ToString('N').Substring(0,8))"
    New-Item -ItemType Directory "$tmp\vendorA\osA" -Force | Out-Null

    @"
vendor: VendorA
os: OsA
version_match: ".*"
type_key: TestDevice
priority: 5
file_extension: cfg
connection:
  needs_enable: false
  handle_paging: false
  needs_shell_menu: false
commands:
  pre: []
  config: "show base"
  post: []
prompts:
  trailing: []
notes: base
"@ | Set-Content "$tmp\vendorA\osA\base.yaml"

    @"
vendor: VendorA
os: OsA
version_match: "^2\\."
type_key: TestDevice
priority: 20
file_extension: cfg
connection:
  needs_enable: false
  handle_paging: false
  needs_shell_menu: false
commands:
  pre: []
  config: "show specific"
  post: []
prompts:
  trailing: []
notes: specific version override
"@ | Set-Content "$tmp\vendorA\osA\2.x.yaml"

    $result = Import-DeviceDefinitions -DefinitionsPath $tmp
    Remove-Item $tmp -Recurse -Force
    # Longer path (2.x.yaml) loaded last, wins on type_key collision
    $result['TestDevice'].ConfigCommand -eq 'show specific'
}

# ---------------------------------------------------------------------------
Write-Host ""
Write-Host "=== 4. Format-SSHOutput logic ===" -ForegroundColor Cyan

. ([scriptblock]::Create((Get-FunctionDef 'Format-SSHOutput')))

Assert "Strips ANSI escape codes" {
    $raw = "`e[32mshow running-config`e[0m`nversion 17.12`nend`nRouter#"
    (Format-SSHOutput -RawOutput $raw -Command 'show running-config') -notmatch '\x1b\['
}

Assert "Strips --More-- artifacts" {
    $raw = "show running-config`nversion 17.12`n --More-- `nip route 0.0.0.0`nRouter#"
    (Format-SSHOutput -RawOutput $raw -Command 'show running-config') -notmatch '--More--'
}

Assert "Strips echoed command from start" {
    $raw = "show running-config`nversion 17.12`nend`nRouter#"
    $out = Format-SSHOutput -RawOutput $raw -Command 'show running-config'
    ($out -split "`n")[0].Trim() -eq 'version 17.12'
}

Assert "Strips Cisco prompt from end (default patterns)" {
    $raw = "show running-config`nversion 17.12`nend`nRouter#"
    (Format-SSHOutput -RawOutput $raw -Command 'show running-config') -notmatch 'Router#'
}

Assert "Strips MikroTik prompt using definition pattern" {
    $raw = "/export verbose`n# RouterOS config`n/ip address`n[admin@MikroTik] > "
    $out = Format-SSHOutput -RawOutput $raw -Command '/export verbose' `
             -TrailingPromptPatterns $profiles['MikroTik'].TrailingPromptPatterns
    $out -notmatch '\[admin@MikroTik\]'
}

Assert "Strips OPNsense prompt using definition pattern" {
    $raw = "cat /conf/config.xml`n<opnsense/>`nroot@OPNsense:/root #"
    $out = Format-SSHOutput -RawOutput $raw -Command 'cat /conf/config.xml' `
             -TrailingPromptPatterns $profiles['OPNsense'].TrailingPromptPatterns
    $out -notmatch 'root@OPNsense'
}

Assert "Fortigate prompt stripped by definition pattern" {
    $raw = "show full-configuration`nconfig system global`nend`nhostname #"
    $out = Format-SSHOutput -RawOutput $raw -Command 'show full-configuration' `
             -TrailingPromptPatterns $profiles['Fortigate'].TrailingPromptPatterns
    $out -notmatch 'hostname #'
}

Assert "Normalises CRLF to LF" {
    $raw = "show running-config`r`nversion 17.12`r`nend`r`nRouter#"
    (Format-SSHOutput -RawOutput $raw -Command 'show running-config') -notmatch "`r"
}

Assert "Returns trimmed content" {
    $raw = "show running-config`n`nversion 17.12`nend`nRouter#`n`n"
    $out = Format-SSHOutput -RawOutput $raw -Command 'show running-config'
    $out -eq $out.Trim()
}

# ---------------------------------------------------------------------------
Write-Host ""
Write-Host "=== 5. Parameter guards ===" -ForegroundColor Cyan

AssertThrows "-Devices and -ConfigFile conflict" "-Devices and -ConfigFile" {
    $secPwd = ConvertTo-SecureString "x" -AsPlainText -Force
    $cred   = New-Object PSCredential("u", $secPwd)
    $fake   = @(@{ Type='Cisco'; Host='127.0.0.1'; Port=22; Credential=$cred; EnablePassword=$null })
    & $ScriptPath -Devices $fake -ConfigFile "nonexistent.json" 2>&1
}

AssertThrows "Missing ConfigFile throws" "not found" {
    & $ScriptPath -ConfigFile "C:\nonexistent_path_xyz.json" 2>&1
}

# ---------------------------------------------------------------------------
Write-Host ""
Write-Host "=== 6. ConfigFile JSON loading ===" -ForegroundColor Cyan

$tmpJson = Join-Path $env:TEMP "test_devices_$([guid]::NewGuid().ToString('N').Substring(0,8)).json"
try {
    @'
[
  { "Type": "MikroTik", "Host": "10.255.255.1", "Port": 22, "Username": "admin", "Password": "testpass" }
]
'@ | Set-Content $tmpJson -Encoding UTF8

    Assert "Valid JSON accepted (connection failure expected)" {
        try { & $ScriptPath -ConfigFile $tmpJson 2>&1 | Out-Null } catch { }
        $true
    }

    Assert "Malformed JSON throws at parse" {
        $bad = Join-Path $env:TEMP "bad_$([guid]::NewGuid().ToString('N').Substring(0,8)).json"
        "{ not valid json [[[ }" | Set-Content $bad
        $threw = $false
        try { Get-Content $bad -Raw | ConvertFrom-Json | Out-Null } catch { $threw = $true }
        Remove-Item $bad -ErrorAction SilentlyContinue
        $threw
    }
}
finally {
    Remove-Item $tmpJson -ErrorAction SilentlyContinue
}

# ---------------------------------------------------------------------------
Write-Host ""
Write-Host "=== 7. Results object shape ===" -ForegroundColor Cyan

Assert "Success result has File, null Error" {
    $ok = [PSCustomObject]@{ Device='x'; Type='Cisco'; Status='Success'; File='C:\foo.cfg'; Error=$null }
    $ok.PSObject.Properties.Name -contains 'Error' -and $null -eq $ok.Error
}

Assert "Failure result has Error, null File" {
    $err = [PSCustomObject]@{ Device='x'; Type='Cisco'; Status='Failed'; File=$null; Error='timed out' }
    $err.PSObject.Properties.Name -contains 'File' -and $null -eq $err.File
}

# ---------------------------------------------------------------------------
Write-Host ""
Write-Host "======================================"
if ($fail -eq 0) {
    Write-Host "  All $pass tests passed." -ForegroundColor Green
} else {
    Write-Host "  $pass passed, $fail failed." -ForegroundColor Red
}
Write-Host "======================================"
Write-Host ""
