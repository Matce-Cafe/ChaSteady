[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$OutputPath,
    [Parameter(Mandatory = $true)]
    [ValidateSet('windows-2025-vs2026')]
    [string]$RunnerLabel,
    [switch]$UpdateStableVisualStudio,
    [switch]$InstallLatestWindowsSdk
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$targetVisualStudio = [Version]'18.11.0.0'
$targetMsvc = [Version]'14.50.0'
$targetCmake = [Version]'4.4.3'
$targetSdkInclude = [Version]'10.0.28000.0'
$minimumSdkServicingRevision = 2957
$installerRoot = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio\Installer'
$vswhere = Join-Path $installerRoot 'vswhere.exe'
$setup = Join-Path $installerRoot 'setup.exe'

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

function Get-FlutterStableVisualStudioInstance {
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
    $responseLines = @(& $curl @curlArgs)
    $curlExit = $LASTEXITCODE
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

    # The official Windows SDK 10.0.28000 product line is published as a Burn
    # installer with silent /q mode. Do not specify unverified optional feature IDs.
    $process = Start-Process -FilePath $installer -ArgumentList '/q /norestart' `
        -WorkingDirectory $env:RUNNER_TEMP -Wait -PassThru -NoNewWindow
    if ($process.ExitCode -ne 0) {
        throw "Official Windows SDK quiet install returned exit code $($process.ExitCode)."
    }
    $installedVersion = Get-InstalledTargetSdkVersion
    if (-not $installedVersion) {
        throw 'Windows SDK installation did not register a verified 28000.2957-or-newer servicing version.'
    }
    $includeRoot = Join-Path ${env:ProgramFiles(x86)} 'Windows Kits\10\Include'
    $includePath = Join-Path $includeRoot '10.0.28000.0'
    if (-not (Test-Path -LiteralPath $includePath -PathType Container)) {
        throw 'Windows SDK servicing installer did not install the required 10.0.28000.0 include tree.'
    }
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

if ($UpdateStableVisualStudio) {
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
    $process = Start-Process -FilePath $setup -ArgumentList $arguments -WorkingDirectory $workingDirectory -Wait -PassThru -NoNewWindow
    if ($process.ExitCode -ne 0) {
        throw "Official Visual Studio stable product update returned exit code $($process.ExitCode)."
    }
}

$sdkInstall = $null
if ($InstallLatestWindowsSdk) {
    $sdkInstall = Install-OfficialWindowsSdk
} else {
    throw 'CI requires the official Windows SDK installer audit and update step; use -InstallLatestWindowsSdk.'
}

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
$msvcToolset = Get-ChildItem -LiteralPath $msvcRoot -Directory | Where-Object {
    $_.Name -match '^\d+\.\d+(\.\d+){0,2}$' -and ([Version]$_.Name -ge $targetMsvc)
} | Sort-Object { [Version]$_.Name } -Descending | Select-Object -First 1
if (-not $msvcToolset) {
    $found = (Get-ChildItem -LiteralPath $msvcRoot -Directory | ForEach-Object Name) -join ', '
    throw "MSVC 14.50 or newer is required; found: $found. Compatibility components below 14.50 are not accepted."
}
$msvcCompiler = Join-Path $msvcToolset.FullName 'bin\Hostx64\x64\cl.exe'
Assert-MicrosoftSignature $msvcCompiler

# This is Flutter 3.47.7's actual cmakePath, not an unrelated executable on PATH.
$cmakePath = Join-Path $visualStudioPath 'Common7\IDE\CommonExtensions\Microsoft\CMake\CMake\bin\cmake.exe'
if (-not (Test-Path -LiteralPath $cmakePath -PathType Leaf)) {
    throw 'The Flutter-selected Visual Studio instance has no bundled CMake executable.'
}
$cmakePath = [IO.Path]::GetFullPath($cmakePath)
$cmakeOutput = & $cmakePath --version
if ($LASTEXITCODE -ne 0 -or -not $cmakeOutput) {
    throw 'The VS-bundled CMake executable used by Flutter could not report its version.'
}
$cmakeMatch = [regex]::Match(($cmakeOutput -join "`n"), '(?im)^cmake version (\d+\.\d+\.\d+)\s*$')
if (-not $cmakeMatch.Success) {
    throw 'CMake reported an unrecognized version format.'
}
$cmakeVersion = [Version]$cmakeMatch.Groups[1].Value
if ($cmakeVersion -lt $targetCmake) {
    throw "CMake 4.4.3 or newer is required; found $cmakeVersion."
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
    cmake_version = [string]$cmakeVersion
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
