# CI VM only. Block outbound networking for the two exact extracted application executables.
param([Parameter(Mandatory=$true)][string]$Bundle,[Parameter(Mandatory=$true)][string]$Fixture,[Parameter(Mandatory=$true)][string]$Evidence)
$ErrorActionPreference = 'Stop'
if ($env:GITHUB_ACTIONS -ne 'true') { throw 'This script is for the disposable developer runner only' }
$fullBundle = [IO.Path]::GetFullPath($Bundle)
if (-not $fullBundle.StartsWith([IO.Path]::GetFullPath($env:RUNNER_TEMP),[StringComparison]::OrdinalIgnoreCase)) { throw 'Unexpected build location' }
$exe = Join-Path $fullBundle 'LocalScribeNPU.exe'
$worker = Join-Path $fullBundle 'worker\WhisperWorker.exe'
if (-not (Test-Path -LiteralPath $exe) -or -not (Test-Path -LiteralPath $worker)) { throw 'Both bundled executables are required' }
$rules = @()
$originalProfiles = @(Get-NetFirewallProfile | Select-Object Name,Enabled)
try {
    if ((Get-Service MpsSvc).Status -ne 'Running') { throw 'Windows Firewall service is not running' }
    foreach ($profile in $originalProfiles) {
        if ([string]$profile.Enabled -ne 'True') { Set-NetFirewallProfile -Name $profile.Name -Enabled True }
    }
    foreach ($program in @($exe,$worker)) {
        $name = 'LocalScribe-CI-' + [Guid]::NewGuid().ToString('N')
        New-NetFirewallRule -Name $name -DisplayName $name -Program $program -Direction Outbound -Action Block -Enabled True -Profile Any | Out-Null
        $rules += $name
        $actual = Get-NetFirewallRule -Name $name -PolicyStore ActiveStore
        if ($actual.Enabled -ne 'True' -or $actual.Action -ne 'Block' -or $actual.Direction -ne 'Outbound') { throw 'Outbound block is not effective in ActiveStore' }
        $filter = $actual | Get-NetFirewallApplicationFilter
        if ($filter.Program -ne $program) { throw 'Rule program does not match the extracted EXE' }
    }
    $activeProfiles = @(Get-NetFirewallProfile -PolicyStore ActiveStore)
    if (@($activeProfiles | Where-Object { [string]$_.Enabled -ne 'True' }).Count -ne 0) { throw 'An effective firewall profile is disabled' }
    $profileEvidence = @($activeProfiles | ForEach-Object { [ordered]@{name=[string]$_.Name;enabled=[string]$_.Enabled} })
    [ordered]@{scope='outbound_block_for_exact_two_executables';profiles=$profileEvidence;rule_count=$rules.Count} | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $Evidence 'network_policy.json') -Encoding UTF8
    for ($index=0; $index -lt 2; $index++) {
        $private = Join-Path $env:RUNNER_TEMP ('LocalScribe gated output ' + $index)
        New-Item -ItemType Directory -Path $private | Out-Null
        $owned = $null
        try {
            # GUI programs can return control before exit through PowerShell's call operator.
            # Own the specific process and read its exit code only after bounded completion.
            $info = New-Object System.Diagnostics.ProcessStartInfo
            $info.FileName = $exe
            $info.WorkingDirectory = $fullBundle
            $info.UseShellExecute = $false
            $info.Arguments = '--exercise "' + $Fixture + '" "' + $private + '"'
            $owned = [System.Diagnostics.Process]::Start($info)
            if (-not $owned.WaitForExit(420000)) { throw 'Developer GUI test exceeded seven minutes' }
            if ($owned.ExitCode -ne 0) { throw ('Packaged GUI process failed: ' + $owned.ExitCode) }
        } finally {
            if ($null -ne $owned) {
                if (-not $owned.HasExited) { $owned.Kill(); $null=$owned.WaitForExit(5000) }
                $owned.Dispose()
            }
            $report = Join-Path $private 'native-gui.json'
            if (Test-Path -LiteralPath $report) {
                Copy-Item -LiteralPath $report -Destination (Join-Path $Evidence ('gui_' + $index + '.json'))
                Write-Output ('GUI_REPORT: ' + [IO.File]::ReadAllText($report))
            }
        }
        $result = Get-Content -LiteralPath (Join-Path $private 'native-gui.json') -Raw -Encoding UTF8 | ConvertFrom-Json
        if ($result.outcome -ne 'passed') { throw 'Native GUI result was not passed' }
    }
    $network = [ordered]@{outcome='passed';scope='outbound_block_rules_for_exact_host_and_worker';profiles=$profileEvidence;rule_count=$rules.Count;packet_capture=$false;fixture_uploaded=$false}
    $network | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $Evidence 'network.json') -Encoding UTF8
} catch {
    $_ | Out-String | Set-Content -LiteralPath (Join-Path $Evidence 'offline_failure.txt') -Encoding UTF8
    throw
} finally {
    # Remove only the app-specific rules created here. No protection is disabled.
    foreach ($name in $rules) { Remove-NetFirewallRule -Name $name -ErrorAction SilentlyContinue }
}
