[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$OutputPath,
    [Parameter(Mandatory = $true)]
    [ValidateSet('windows-2025-vs2026')]
    [string]$RunnerLabel,
    [switch]$UpdateStableVisualStudio,
    [switch]$InstallLatestWindowsSdk,
    [switch]$FixtureProbeOnly
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# Reject this combination before discovery, downloads, or installer execution.
if ($FixtureProbeOnly -and ($UpdateStableVisualStudio -or $InstallLatestWindowsSdk)) {
    throw 'CI_FIXTURE_PROBE_CONFLICTS_WITH_INSTALLERS'
}

$targetVisualStudio = [Version]'18.11.0.0'
$targetMsvc = [Version]'14.50.0'
# Baseline of stable VS 18.11's official bundle (4.3.1-msvc1 observed in CI),
# not a claim about the newest standalone upstream Kitware CMake release.
$targetCmake = [Version]'4.3.1'
$targetSdkInclude = [Version]'10.0.28000.0'
$minimumSdkServicingRevision = 2957
$installerRoot = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio\Installer'
$vswhere = Join-Path $installerRoot 'vswhere.exe'
$setup = Join-Path $installerRoot 'setup.exe'
$preflightTimer = [Diagnostics.Stopwatch]::StartNew()

function ConvertFrom-StableCmakeVersion([string]$RawVersion) {
    # Microsoft's VS-bundled stable CMake adds only the official -msvcN suffix.
    # Do not accept rc/alpha/beta/dev or arbitrary suffixes as stable releases.
    $match = [regex]::Match($RawVersion, '^(\d+\.\d+\.\d+)(?:-msvc[0-9]+)?$')
    if (-not $match.Success) {
        throw "CMake version is not an approved stable/plain or Microsoft -msvcN version: $RawVersion"
    }
    return [Version]$match.Groups[1].Value
}

function Assert-MicrosoftSignature([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw 'A required official Microsoft toolchain executable is missing.'
    }
    $signature = Get-AuthenticodeSignature -LiteralPath $Path
    $subject = if ($signature.SignerCertificate) { [string]$signature.SignerCertificate.Subject } else { '' }
    if ($signature.Status.ToString() -ne 'Valid' -or
        ($subject -notmatch 'CN=Microsoft Corporation' -and $subject -notmatch 'O=Microsoft Corporation')) {
        throw 'A required Microsoft toolchain executable failed the default Authenticode trust check.'
    }
}

function Get-FlutterStableVisualStudioInstance([switch]$FixtureVs2026Only) {
    # Flutter 3.47.7 first queries a stable NativeDesktop IDE, then stable VCTools,
    # with these exact component requirements. It does not pick from PATH or
    # independently sort every installed product. Preview fallback is not allowed
    # by this CI contract, so fail closed if neither stable query succeeds.
    Assert-MicrosoftSignature $vswhere
    foreach ($workload in @('Microsoft.VisualStudio.Workload.NativeDesktop', 'Microsoft.VisualStudio.Workload.VCTools')) {
        $arguments = @(
            '-format', 'json', '-products', '*', '-utf8', '-latest', '-version', '16',
            '-requires', $workload,
            'Microsoft.VisualStudio.Component.VC.Tools.x86.x64',
            'Microsoft.VisualStudio.Component.VC.CMake.Project'
        )
        if ($FixtureVs2026Only) {
            $versionIndex = [Array]::IndexOf($arguments, '-version')
            $arguments[$versionIndex + 1] = '[18.0,19.0)'
        }
        $json = & $vswhere @arguments
        if ($LASTEXITCODE -ne 0) { throw 'Flutter-compatible official Visual Studio discovery failed.' }
        $matches = @($json | ConvertFrom-Json)
        if ($matches.Count -gt 0) { return $matches[0] }
    }
    throw 'No stable Visual Studio instance meets the actual Flutter Windows workload/component queries.'
}

function Test-TargetSdkServicingVersion([Version]$Version) {
    return ($Version.Major -eq 10 -and $Version.Build -eq 28000 -and
        $Version.Revision -ge $minimumSdkServicingRevision)
}

function Get-InstalledTargetSdkVersion {
    $uninstallPaths = @(
        'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*',
        'HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*'
    )
    $candidates = @()
    foreach ($registryPath in $uninstallPaths) {
        if (-not (Test-Path -LiteralPath ($registryPath -replace '\\\*$', ''))) { continue }
        $items = Get-ItemProperty -Path $registryPath -ErrorAction SilentlyContinue
        foreach ($item in $items) {
            $nameProperty = $item.PSObject.Properties['DisplayName']
            $versionProperty = $item.PSObject.Properties['DisplayVersion']
            if (-not $nameProperty -or -not $versionProperty) { continue }
            $displayName = [string]$nameProperty.Value
            $displayVersion = [string]$versionProperty.Value
            if ($displayName -notmatch '(?i)Windows.*(SDK|Software Development Kit)' -or
                $displayVersion -notmatch '^\d+\.\d+\.\d+\.\d+$') { continue }
            $parsed = [Version]$displayVersion
            if (Test-TargetSdkServicingVersion $parsed) { $candidates += $parsed }
        }
    }
    if ($candidates.Count -eq 0) { return $null }
    return ($candidates | Sort-Object -Descending | Select-Object -First 1)
}

function Install-OfficialWindowsSdk {
    if (-not $env:RUNNER_TEMP) {
        throw 'The Windows SDK installer is permitted only on a hosted Actions runner.'
    }
    $sdkUrl = 'https://go.microsoft.com/fwlink/?linkid=2382519'
    $downloadRoot = Join-Path $env:RUNNER_TEMP ('cha-steady-windows-sdk-' + [Guid]::NewGuid().ToString('N'))
    if (Test-Path -LiteralPath $downloadRoot) { throw 'Windows SDK download UUID directory already exists.' }
    [void][IO.Directory]::CreateDirectory($downloadRoot)
    if ([IO.Directory]::GetFileSystemEntries($downloadRoot).Count -ne 0) {
        throw 'New Windows SDK download directory was not empty.'
    }
    $curl = Join-Path $env:SystemRoot 'System32\curl.exe'
    Assert-MicrosoftSignature $curl
    $installer = Join-Path $downloadRoot 'winsdksetup.exe'
    $headers = Join-Path $downloadRoot 'http-headers.txt'
    $writeOut = "%{http_code}`n%{url_effective}"
    $curlArgs = @(
        '--silent', '--show-error', '--fail', '--location',
        '--proto', '=https', '--proto-redir', '=https', '--max-redirs', '5',
        '--max-filesize', '1073741824', '--dump-header', $headers,
        '--output', $installer, '--write-out', $writeOut, $sdkUrl
    )
    Write-Host ("[{0:o}] Windows SDK download starting from the official Microsoft entry." -f [DateTime]::UtcNow)
    $downloadTimer = [Diagnostics.Stopwatch]::StartNew()
    $responseLines = @(& $curl @curlArgs)
    $curlExit = $LASTEXITCODE
    Write-Host ("Windows SDK download exit={0}; elapsed={1:N2}s." -f $curlExit, $downloadTimer.Elapsed.TotalSeconds)
    $sdkAuditTimer = [Diagnostics.Stopwatch]::StartNew()
    if ($curlExit -ne 0 -or $responseLines.Count -lt 2) {
        throw "Official Windows SDK download failed (curl exit $curlExit)."
    }
    $status = [string]$responseLines[0]
    $effectiveUrl = [string]$responseLines[1]
    $effectiveUri = $null
    if ($status.Trim() -ne '200' -or
        -not ([Uri]::TryCreate($effectiveUrl.Trim(), [UriKind]::Absolute, [ref]$effectiveUri)) -or
        $effectiveUri.Scheme -cne 'https' -or
        $effectiveUri.Host -cne 'download.microsoft.com') {
        throw 'Windows SDK fwlink did not resolve over HTTPS to the approved official download host.'
    }
    $redirectLocations = @([IO.File]::ReadAllLines($headers) | Where-Object { $_ -match '^(?i)Location:\s*' })
    foreach ($line in $redirectLocations) {
        $location = ($line -replace '^(?i)Location:\s*', '').Trim()
        $locationUri = $null
        if (-not ([Uri]::TryCreate($location, [UriKind]::Absolute, [ref]$locationUri)) -or
            $locationUri.Scheme -cne 'https' -or
            $locationUri.Host -notin @('go.microsoft.com', 'download.microsoft.com')) {
            throw 'Windows SDK download chain contains an unapproved redirect target.'
        }
    }
    $installerInfo = Get-Item -LiteralPath $installer
    if (-not $installerInfo.Length -or $installerInfo.Length -gt 1073741824) {
        throw 'Windows SDK installer size is outside the configured bound.'
    }
    $installerHash = (Get-FileHash -LiteralPath $installer -Algorithm SHA256).Hash.ToLowerInvariant()
    $signature = Get-AuthenticodeSignature -LiteralPath $installer
    $subject = if ($signature.SignerCertificate) { [string]$signature.SignerCertificate.Subject } else { '' }
    if ($signature.Status.ToString() -ne 'Valid' -or
        ($subject -notmatch 'CN=Microsoft Corporation' -and $subject -notmatch 'O=Microsoft Corporation')) {
        throw 'Downloaded Windows SDK installer failed the default Microsoft Authenticode trust check.'
    }
    $fileVersion = [string]$installerInfo.VersionInfo.FileVersion
    $fileVersionMatch = [regex]::Match($fileVersion, '(\d+\.\d+\.\d+\.\d+)')
    if (-not $fileVersionMatch.Success) {
        throw 'Signed Windows SDK installer did not expose a four-part servicing version.'
    }
    $parsedFileVersion = [Version]$fileVersionMatch.Groups[1].Value
    if (-not (Test-TargetSdkServicingVersion $parsedFileVersion)) {
        throw 'Signed Windows SDK installer version is older than the required 28000.2957 servicing level.'
    }

    Write-Host ("Windows SDK installer version={0}; SHA256={1}; signature={2}; audit elapsed={3:N2}s." -f
        $fileVersion, $installerHash, $signature.Status, $sdkAuditTimer.Elapsed.TotalSeconds)
    # The official Windows SDK 10.0.28000 product line is published as a Burn
    # installer with silent /q mode. Do not specify unverified optional feature IDs.
    Write-Host ("[{0:o}] Windows SDK install starting with /q /norestart (default feature selection)." -f [DateTime]::UtcNow)
    $sdkInstallTimer = [Diagnostics.Stopwatch]::StartNew()
    $process = Start-Process -FilePath $installer -ArgumentList '/q /norestart' `
        -WorkingDirectory $env:RUNNER_TEMP -Wait -PassThru -NoNewWindow
    Write-Host ("Windows SDK install exit={0}; elapsed={1:N2}s." -f $process.ExitCode, $sdkInstallTimer.Elapsed.TotalSeconds)
    if ($process.ExitCode -ne 0) {
        throw "Official Windows SDK quiet install returned exit code $($process.ExitCode)."
    }
    $sdkVerifyTimer = [Diagnostics.Stopwatch]::StartNew()
    $installedVersion = Get-InstalledTargetSdkVersion
    if (-not $installedVersion) {
        throw 'Windows SDK installation did not register a verified 28000.2957-or-newer servicing version.'
    }
    $includeRoot = Join-Path ${env:ProgramFiles(x86)} 'Windows Kits\10\Include'
    $includePath = Join-Path $includeRoot '10.0.28000.0'
    if (-not (Test-Path -LiteralPath $includePath -PathType Container)) {
        throw 'Windows SDK servicing installer did not install the required 10.0.28000.0 include tree.'
    }
    $kitsRoot = Join-Path ${env:ProgramFiles(x86)} 'Windows Kits\10'
    $requiredDesktopFiles = @(
        'Include\10.0.28000.0\um\Windows.h',
        'Include\10.0.28000.0\shared\sdkddkver.h',
        'Include\10.0.28000.0\ucrt\stdio.h',
        'Lib\10.0.28000.0\um\x64\kernel32.lib',
        'Lib\10.0.28000.0\um\x64\user32.lib',
        'Lib\10.0.28000.0\ucrt\x64\ucrt.lib',
        'bin\10.0.28000.0\x64\rc.exe',
        'bin\10.0.28000.0\x64\mt.exe'
    )
    foreach ($relative in $requiredDesktopFiles) {
        if (-not (Test-Path -LiteralPath (Join-Path $kitsRoot $relative) -PathType Leaf)) {
            throw "Installed Windows SDK is missing a required x64 desktop header/library/tool: $relative"
        }
    }
    Write-Host ("Windows SDK installed product={0}; include=10.0.28000.0; x64 desktop headers/libraries/tools verified; validation elapsed={1:N2}s." -f
        $installedVersion, $sdkVerifyTimer.Elapsed.TotalSeconds)
    return [ordered]@{
        source_id = 'microsoft-official-windows-sdk-fwlink-2382519'
        download_host = $effectiveUri.Host
        bytes = [long]$installerInfo.Length
        sha256 = $installerHash
        authenticode_status = $signature.Status.ToString()
        signer_subject = $subject
        installer_file_version = $fileVersion
        installer_arguments = '/q /norestart'
        install_exit_code = $process.ExitCode
        installed_product_version = [string]$installedVersion
        include_version = '10.0.28000.0'
    }
}

function Test-FixturePathWithin([string]$Path, [string]$Root) {
    $full = [IO.Path]::GetFullPath($Path).TrimEnd('\')
    $base = [IO.Path]::GetFullPath($Root).TrimEnd('\')
    return ($full.Equals($base, [StringComparison]::OrdinalIgnoreCase) -or
        $full.StartsWith($base + '\', [StringComparison]::OrdinalIgnoreCase))
}

function Get-FixtureCanonicalPath([string]$Path, [ValidateSet('File', 'Directory')][string]$Kind) {
    if (-not [IO.Path]::IsPathRooted($Path) -or $Path.IndexOfAny([char[]]@('"', "`r", "`n", [char]0)) -ge 0) {
        throw 'CI_FIXTURE_PATH_INVALID'
    }
    $full = [IO.Path]::GetFullPath($Path)
    $anchor = [IO.Path]::GetPathRoot($full)
    if ($anchor -cnotmatch '^[A-Za-z]:\\$') { throw 'CI_FIXTURE_PATH_INVALID' }
    $cursor = $anchor
    $parts = @($full.Substring($anchor.Length).Split('\', [StringSplitOptions]::RemoveEmptyEntries))
    $all = @($anchor)
    foreach ($part in $parts) { $cursor = Join-Path $cursor $part; $all += $cursor }
    foreach ($component in $all) {
        try { $item = Get-Item -LiteralPath $component -Force -ErrorAction Stop }
        catch { throw 'CI_FIXTURE_PATH_MISSING' }
        if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw 'CI_FIXTURE_REPARSE_REJECTED'
        }
        if ($component -ne $full -and (-not $item.PSIsContainer -or $item -isnot [IO.DirectoryInfo])) {
            throw 'CI_FIXTURE_PATH_INVALID'
        }
    }
    if (($Kind -eq 'Directory' -and (-not $item.PSIsContainer -or $item -isnot [IO.DirectoryInfo])) -or
        ($Kind -eq 'File' -and ($item.PSIsContainer -or $item -isnot [IO.FileInfo]))) {
        throw 'CI_FIXTURE_PATH_KIND'
    }
    return [IO.Path]::GetFullPath($item.FullName)
}

function Assert-FixtureMicrosoftTool([string]$Path) {
    [void](Get-FixtureCanonicalPath $Path 'File')
    try { Assert-MicrosoftSignature $Path }
    catch { throw 'CI_FIXTURE_TOOL_SIGNATURE' }
}

function Select-FixtureSdkVersion([object[]]$Candidates) {
    # Pure data selection: a numeric name alone never certifies completeness.
    $eligible = @()
    foreach ($candidate in $Candidates) {
        $version = $null
        if ($candidate.Version -cmatch '^10\.0\.\d+\.\d+$' -and
            [Version]::TryParse([string]$candidate.Version, [ref]$version) -and
            $candidate.Complete -is [bool] -and $candidate.Complete) {
            $eligible += $candidate
        }
    }
    $selected = @($eligible | Sort-Object { [Version]$_.Version } -Descending | Select-Object -First 1)
    if ($selected.Count -ne 1) { throw 'CI_FIXTURE_COMPLETE_SDK_MISSING' }
    return [string]$selected[0].Version
}

function Get-FixtureInstalledSdk {
    $kitsRoot = Get-FixtureCanonicalPath (Join-Path ${env:ProgramFiles(x86)} 'Windows Kits\10') 'Directory'
    $includeRoot = Get-FixtureCanonicalPath (Join-Path $kitsRoot 'Include') 'Directory'
    $candidates = @()
    foreach ($entry in Get-ChildItem -LiteralPath $includeRoot -Directory) {
        if ($entry.Name -cnotmatch '^10\.0\.\d+\.\d+$') { continue }
        $version = $entry.Name
        $required = @(
            "Include\$version\um\Windows.h", "Include\$version\shared\sdkddkver.h",
            "Include\$version\ucrt\stdio.h", "Lib\$version\um\x64\kernel32.lib",
            "Lib\$version\um\x64\user32.lib", "Lib\$version\ucrt\x64\ucrt.lib",
            "bin\$version\x64\rc.exe", "bin\$version\x64\mt.exe"
        )
        $complete = $true
        foreach ($relative in $required) {
            try { [void](Get-FixtureCanonicalPath (Join-Path $kitsRoot $relative) 'File') }
            catch { $complete = $false; break }
        }
        $candidates += [pscustomobject]@{ Version = $version; Complete = $complete }
    }
    $version = Select-FixtureSdkVersion $candidates
    $rc = Get-FixtureCanonicalPath (Join-Path $kitsRoot "bin\$version\x64\rc.exe") 'File'
    $mt = Get-FixtureCanonicalPath (Join-Path $kitsRoot "bin\$version\x64\mt.exe") 'File'
    Assert-FixtureMicrosoftTool $rc
    Assert-FixtureMicrosoftTool $mt
    return [pscustomobject]@{ Root = $kitsRoot; Version = $version; Rc = $rc; Mt = $mt }
}

function Get-FixtureProbeToolchain {
    [void](Get-FixtureCanonicalPath $vswhere 'File')
    $instance = Get-FlutterStableVisualStudioInstance -FixtureVs2026Only
    foreach ($property in @('installationPath', 'installationVersion', 'isPrerelease', 'isComplete', 'isLaunchable')) {
        if (-not $instance.PSObject.Properties[$property]) { throw 'CI_FIXTURE_VS_DESCRIPTOR_INVALID' }
    }
    $vsVersion = $null
    if ($instance.isPrerelease -ne $false -or $instance.isComplete -ne $true -or
        $instance.isLaunchable -ne $true -or
        -not [Version]::TryParse([string]$instance.installationVersion, [ref]$vsVersion) -or
        $vsVersion.Major -ne 18) {
        throw 'CI_FIXTURE_STABLE_VS2026_MISSING'
    }
    $vsPath = Get-FixtureCanonicalPath ([string]$instance.installationPath) 'Directory'
    $defaultFile = Get-FixtureCanonicalPath (Join-Path $vsPath 'VC\Auxiliary\Build\Microsoft.VCToolsVersion.default.txt') 'File'
    if ((Get-Item -LiteralPath $defaultFile).Length -gt 128) { throw 'CI_FIXTURE_MSVC_DEFAULT_INVALID' }
    $defaultVersion = [IO.File]::ReadAllText($defaultFile).Trim()
    $parsedMsvc = $null
    if ($defaultVersion -cnotmatch '^\d+\.\d+\.\d+(\.\d+)?$' -or
        -not [Version]::TryParse($defaultVersion, [ref]$parsedMsvc) -or $parsedMsvc.Major -ne 14) {
        throw 'CI_FIXTURE_MSVC_DEFAULT_INVALID'
    }
    $msvcPath = Get-FixtureCanonicalPath (Join-Path $vsPath "VC\Tools\MSVC\$defaultVersion") 'Directory'
    $cl = Get-FixtureCanonicalPath (Join-Path $msvcPath 'bin\Hostx64\x64\cl.exe') 'File'
    Assert-FixtureMicrosoftTool $cl
    # As in the full preflight, query this VS instance's bundled CMake, not PATH.
    $cmake = Get-FixtureCanonicalPath (Join-Path $vsPath 'Common7\IDE\CommonExtensions\Microsoft\CMake\CMake\bin\cmake.exe') 'File'
    $versionOutput = @(& $cmake --version 2>&1)
    $versionExit = $LASTEXITCODE
    $versionText = ($versionOutput | ForEach-Object { [string]$_ }) -join "`n"
    $matches = [regex]::Matches($versionText, '(?m)^cmake version ([^\r\n]+)\r?$')
    if ($versionExit -ne 0 -or $matches.Count -ne 1) { throw 'CI_FIXTURE_CMAKE_VERSION_INVALID' }
    $rawCmakeVersion = $matches[0].Groups[1].Value.Trim()
    try { [void](ConvertFrom-StableCmakeVersion $rawCmakeVersion) }
    catch { throw 'CI_FIXTURE_CMAKE_VERSION_INVALID' }
    $helpOutput = @(& $cmake --help 2>&1)
    $helpExit = $LASTEXITCODE
    $helpText = ($helpOutput | ForEach-Object { [string]$_ }) -join "`n"
    if ($helpExit -ne 0 -or $helpText -cnotmatch '(?m)^[ \t]*(?:\*[ \t]*)?Visual Studio 18 2026[ \t]*=') {
        throw 'CI_FIXTURE_CMAKE_VS2026_GENERATOR_MISSING'
    }
    $sdk = Get-FixtureInstalledSdk
    return [ordered]@{
        schema_version = 1
        scope = 'supplementary_diagnostics_only_preinstalled_toolchain'
        production_toolchain_validated = $false
        downloads_or_updates_executed = $false
        runner_label = $RunnerLabel
        architecture = 'x64'
        visual_studio_path = $vsPath
        visual_studio_version = [string]$instance.installationVersion
        msvc_toolset_path = $msvcPath
        msvc_toolset_version = $defaultVersion
        cmake_path = $cmake
        cmake_version = $rawCmakeVersion
        windows_sdk_root = $sdk.Root
        windows_sdk_version = $sdk.Version
        rc_path = $sdk.Rc
        mt_path = $sdk.Mt
    }
}

if ($FixtureProbeOnly) {
    # Supplementary descriptor only: return before every production floor/update.
    $fixtureOutput = [IO.Path]::GetFullPath($OutputPath)
    if ($fixtureOutput -cnotmatch '^[A-Za-z]:\\' -or $fixtureOutput.Contains('"')) {
        throw 'CI_FIXTURE_OUTPUT_INVALID'
    }
    if (Test-Path -LiteralPath $fixtureOutput) { throw 'Toolchain preflight result must be a new file.' }
    $sourceRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
    if (Test-FixturePathWithin $fixtureOutput $sourceRoot) { throw 'CI_FIXTURE_OUTPUT_OVERLAPS_SOURCE' }
    $fixtureRecord = Get-FixtureProbeToolchain
    foreach ($toolRoot in @($fixtureRecord.visual_studio_path, $fixtureRecord.windows_sdk_root)) {
        if (Test-FixturePathWithin $fixtureOutput $toolRoot) { throw 'CI_FIXTURE_OUTPUT_OVERLAPS_TOOLCHAIN' }
    }
    $outputParent = [IO.Path]::GetDirectoryName($fixtureOutput)
    $existingParent = $outputParent
    while (-not [IO.Directory]::Exists($existingParent)) {
        $existingParent = [IO.Path]::GetDirectoryName($existingParent)
        if (-not $existingParent) { throw 'CI_FIXTURE_OUTPUT_INVALID' }
    }
    [void](Get-FixtureCanonicalPath $existingParent 'Directory')
    [void][IO.Directory]::CreateDirectory($outputParent)
    [void](Get-FixtureCanonicalPath $outputParent 'Directory')
    $fixtureJson = ConvertTo-Json -InputObject $fixtureRecord -Depth 4
    $bytes = [Text.UTF8Encoding]::new($false).GetBytes($fixtureJson + "`n")
    $stream = [IO.File]::Open($fixtureOutput, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
    try { $stream.Write($bytes, 0, $bytes.Length) } finally { $stream.Dispose() }
    Write-Output 'Supplementary fixture descriptor only; production toolchain validation was not performed.'
    return
}

if ($UpdateStableVisualStudio) {
    $vsUpdateTimer = [Diagnostics.Stopwatch]::StartNew()
    $updateTarget = Get-FlutterStableVisualStudioInstance
    if (-not $updateTarget.installationPath -or [bool]$updateTarget.isPrerelease -or
        ([Version]$updateTarget.installationVersion -lt [Version]'18.0.0.0') -or
        ([Version]$updateTarget.installationVersion -ge [Version]'19.0.0.0')) {
        throw 'The Visual Studio instance selected by Flutter must be a stable VS 2026 product before update.'
    }
    Assert-MicrosoftSignature $setup
    $installPath = [IO.Path]::GetFullPath([string]$updateTarget.installationPath)
    if ($installPath.Contains('"') -or -not (Test-Path -LiteralPath $installPath -PathType Container)) {
        throw 'The discovered Visual Studio product instance path is not safe to update.'
    }
    # Microsoft documents setup.exe update as the product update operation.
    # Start-Process -Wait provides synchronous completion; setup.exe is not given --wait.
    $arguments = 'update --quiet --norestart --installPath "{0}" --channelUri https://aka.ms/vs/stable/channel' -f $installPath
    $workingDirectory = if ($env:RUNNER_TEMP) { $env:RUNNER_TEMP } else { [IO.Path]::GetTempPath() }
    Write-Host ("[{0:o}] Visual Studio product update starting: version={1}; instance={2}." -f
        [DateTime]::UtcNow, $updateTarget.installationVersion, $installPath)
    $process = Start-Process -FilePath $setup -ArgumentList $arguments -WorkingDirectory $workingDirectory -Wait -PassThru -NoNewWindow
    Write-Host ("Visual Studio product update exit={0}; elapsed={1:N2}s." -f $process.ExitCode, $vsUpdateTimer.Elapsed.TotalSeconds)
    if ($process.ExitCode -ne 0) {
        throw "Official Visual Studio stable product update returned exit code $($process.ExitCode)."
    }
    $updatedInstance = Get-FlutterStableVisualStudioInstance
    Write-Host ("Visual Studio product version after update: {0}." -f $updatedInstance.installationVersion)
}

$toolchainVerifyTimer = [Diagnostics.Stopwatch]::StartNew()
$visualStudio = Get-FlutterStableVisualStudioInstance
if (-not $visualStudio.installationPath -or [bool]$visualStudio.isPrerelease -or
    ([Version]$visualStudio.installationVersion -lt $targetVisualStudio) -or
    ([Version]$visualStudio.installationVersion -ge [Version]'19.0.0.0')) {
    throw 'Flutter-selected stable Visual Studio must be VS 2026 18.11.0 or newer; no older or preview instance is accepted.'
}
$visualStudioPath = [IO.Path]::GetFullPath([string]$visualStudio.installationPath)
$msvcRoot = Join-Path $visualStudioPath 'VC\Tools\MSVC'
if (-not (Test-Path -LiteralPath $msvcRoot -PathType Container)) {
    throw 'The selected Visual Studio instance has no MSVC toolset directory.'
}
# Flutter supplies no -T override: audit the installed product's default
# toolset rather than selecting an unrelated highest/preview directory.
$msvcDefaultFile = Join-Path $visualStudioPath 'VC\Auxiliary\Build\Microsoft.VCToolsVersion.default.txt'
if (-not (Test-Path -LiteralPath $msvcDefaultFile -PathType Leaf)) {
    throw 'The Flutter-selected Visual Studio instance has no official default MSVC version file.'
}
$msvcDefaultVersion = [IO.File]::ReadAllText($msvcDefaultFile).Trim()
Write-Host ("Visual Studio default MSVC toolset file={0}; raw version={1}." -f $msvcDefaultFile, $msvcDefaultVersion)
if ($msvcDefaultVersion -cnotmatch '^\d+\.\d+\.\d+(\.\d+)?$' -or
    ([Version]$msvcDefaultVersion -lt $targetMsvc)) {
    throw "MSVC 14.50 or newer is required; product default is $msvcDefaultVersion. No preview or compatibility toolset is substituted."
}
$msvcDefaultPath = Join-Path $msvcRoot $msvcDefaultVersion
if (-not (Test-Path -LiteralPath $msvcDefaultPath -PathType Container)) {
    throw 'The official default MSVC version file points to a missing toolset directory.'
}
$msvcToolset = Get-Item -LiteralPath $msvcDefaultPath
$msvcCompiler = Join-Path $msvcToolset.FullName 'bin\Hostx64\x64\cl.exe'
Assert-MicrosoftSignature $msvcCompiler

# This is Flutter 3.47.7's actual cmakePath, not an unrelated executable on PATH.
$cmakePath = Join-Path $visualStudioPath 'Common7\IDE\CommonExtensions\Microsoft\CMake\CMake\bin\cmake.exe'
if (-not (Test-Path -LiteralPath $cmakePath -PathType Leaf)) {
    throw 'The Flutter-selected Visual Studio instance has no bundled CMake executable.'
}
$cmakePath = [IO.Path]::GetFullPath($cmakePath)
Write-Host ("Actual Flutter-selected VS version={0}; MSVC toolset={1}; CMake executable={2}" -f
    $visualStudio.installationVersion, $msvcToolset.Name, $cmakePath)
$cmakeOutput = @(& $cmakePath --version 2>&1)
$cmakeExit = $LASTEXITCODE
$cmakeOutputText = ($cmakeOutput | ForEach-Object { [string]$_ }) -join "`n"
Write-Host 'Actual CMake --version output follows (before parsing):'
Write-Host $cmakeOutputText
$cmakeHelpOutput = @(& $cmakePath --help 2>&1)
$cmakeHelpExit = $LASTEXITCODE
$cmakeHelpText = ($cmakeHelpOutput | ForEach-Object { [string]$_ }) -join "`n"
$cmakeGeneratorLines = @($cmakeHelpText -split "`n" | Where-Object {
    $_ -cmatch '^[ \t]*(?:\*[ \t]*)?Visual Studio 18 2026[ \t]*='
})
$cmakeSupportsVs2026 = $cmakeHelpExit -eq 0 -and $cmakeGeneratorLines.Count -gt 0
Write-Host ("CMake --help supports Visual Studio 18 2026 generator={0}; exit={1}." -f $cmakeSupportsVs2026, $cmakeHelpExit)
foreach ($line in $cmakeGeneratorLines) { Write-Host $line }
Write-Host ("Toolchain version probe elapsed={0:N2}s; preflight elapsed so far={1:N2}s." -f
    $toolchainVerifyTimer.Elapsed.TotalSeconds, $preflightTimer.Elapsed.TotalSeconds)
if ($cmakeExit -ne 0 -or -not $cmakeOutputText) {
    throw "The VS-bundled CMake executable used by Flutter could not report its version (exit $cmakeExit)."
}
$cmakeMatches = [regex]::Matches($cmakeOutputText, '(?m)^cmake version ([^\r\n]+)\r?$')
if ($cmakeMatches.Count -ne 1) {
    throw 'CMake output did not contain exactly one recognizable version line; raw output was printed above.'
}
$cmakeRawVersion = $cmakeMatches[0].Groups[1].Value.Trim()
$cmakeVersion = ConvertFrom-StableCmakeVersion $cmakeRawVersion
if ($cmakeVersion -lt $targetCmake) {
    throw "VS-bundled CMake 4.3.1 or newer is required; found raw=$cmakeRawVersion, numeric=$cmakeVersion."
}
if (-not $cmakeSupportsVs2026) {
    throw 'The actual VS-bundled CMake did not advertise the required Visual Studio 18 2026 generator.'
}
$toolchainVerifyTimer.Stop()
Write-Host ("Fast VS/MSVC/CMake checks passed in {0:N2}s; only now entering the SDK phase." -f $toolchainVerifyTimer.Elapsed.TotalSeconds)

$sdkInstall = $null
if ($InstallLatestWindowsSdk) {
    $sdkInstall = Install-OfficialWindowsSdk
} else {
    throw 'CI requires the official Windows SDK installer audit and update step; use -InstallLatestWindowsSdk.'
}

$windowsKitsInclude = Join-Path ${env:ProgramFiles(x86)} 'Windows Kits\10\Include'
if (-not (Test-Path -LiteralPath $windowsKitsInclude -PathType Container)) {
    throw 'The official Windows 10/11 SDK include directory is unavailable.'
}
$windowsSdk = Get-ChildItem -LiteralPath $windowsKitsInclude -Directory | Where-Object {
    $_.Name -match '^\d+\.\d+\.\d+\.\d+$' -and ([Version]$_.Name -ge $targetSdkInclude)
} | Sort-Object { [Version]$_.Name } -Descending | Select-Object -First 1
if (-not $windowsSdk -or $windowsSdk.Name -ne '10.0.28000.0') {
    $found = (Get-ChildItem -LiteralPath $windowsKitsInclude -Directory | ForEach-Object Name) -join ', '
    throw "Windows SDK 10.0.28000.0 is required; found: $found. No older 10.0.26100 SDK is accepted."
}
$installedSdkVersion = Get-InstalledTargetSdkVersion
if (-not $installedSdkVersion) {
    throw 'Installed Windows SDK servicing version is below 28000.2957 or cannot be verified.'
}

$output = [IO.Path]::GetFullPath($OutputPath)
if (Test-Path -LiteralPath $output) {
    throw 'Toolchain preflight result must be a new file.'
}
[IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($output)) | Out-Null
$record = [ordered]@{
    schema_version = 1
    runner_label = $RunnerLabel
    visual_studio_version = [string]$visualStudio.installationVersion
    visual_studio_path = $visualStudioPath
    visual_studio_prerelease = $false
    msvc_toolset_version = [string]$msvcToolset.Name
    msvc_toolset_path = [IO.Path]::GetFullPath($msvcToolset.FullName)
    cmake_version = $cmakeRawVersion
    cmake_version_output = $cmakeOutputText
    cmake_path = $cmakePath
    windows_sdk_version = [string]$windowsSdk.Name
    windows_sdk_product_version = [string]$installedSdkVersion
    sdk_installer = $sdkInstall
}
$json = ConvertTo-Json -InputObject $record -Depth 6
[IO.File]::WriteAllText($output, $json + "`n", [Text.UTF8Encoding]::new($false))
Write-Output ("Verified stable VS {0}, MSVC {1}, CMake {2}, Windows SDK {3} servicing {4}." -f
    $record.visual_studio_version, $record.msvc_toolset_version, $record.cmake_version,
    $record.windows_sdk_version, $record.windows_sdk_product_version)
Write-Host ("Toolchain version validation elapsed={0:N2}s; complete preflight elapsed={1:N2}s." -f
    $toolchainVerifyTimer.Elapsed.TotalSeconds, $preflightTimer.Elapsed.TotalSeconds)
