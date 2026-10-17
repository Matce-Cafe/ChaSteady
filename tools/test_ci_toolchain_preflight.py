"""Static safety tests for the CI-only PowerShell toolchain updater.

These tests parse but never execute the installer/update commands. The actual
VS/SDK install remains an Actions-runner-only operation.
"""
from pathlib import Path
import re
import shutil
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "ci_toolchain_preflight.ps1"


class ToolchainPreflightScriptTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = SCRIPT.read_text(encoding="utf-8")

    def test_source_uses_only_official_stable_version_floors(self):
        for text in ("18.11.0.0", "14.50.0", "4.3.1", "10.0.28000.0", "2957"):
            with self.subTest(text=text):
                self.assertIn(text, self.text)
        self.assertIn("windows-2025-vs2026", self.text)
        self.assertIn("https://aka.ms/vs/stable/channel", self.text)
        self.assertIn("https://go.microsoft.com/fwlink/?linkid=2382519", self.text)

    def test_update_and_install_require_signatures_hashes_and_actual_postchecks(self):
        self.assertIn("Assert-MicrosoftSignature $setup", self.text)
        self.assertIn("Get-AuthenticodeSignature -LiteralPath $Path", self.text)
        self.assertIn("Get-AuthenticodeSignature -LiteralPath $installer", self.text)
        self.assertLess(self.text.index("Get-FileHash -LiteralPath $installer"),
                        self.text.index("Start-Process -FilePath $installer"))
        self.assertIn("Get-InstalledTargetSdkVersion", self.text)
        self.assertIn("10.0.28000.0", self.text)
        self.assertIn("MSVC 14.50 or newer is required", self.text)
        self.assertIn("VS-bundled CMake 4.3.1 or newer is required", self.text)
        self.assertIn("not a claim about the newest standalone upstream Kitware CMake release", self.text)

    def test_cmake_audit_uses_flutter_selected_visual_studio_bundle_not_path(self):
        self.assertIn("function Get-FlutterStableVisualStudioInstance", self.text)
        self.assertIn("'Microsoft.VisualStudio.Workload.NativeDesktop', 'Microsoft.VisualStudio.Workload.VCTools'", self.text)
        self.assertIn("'-format', 'json', '-products', '*', '-utf8', '-latest', '-version', '16'", self.text)
        self.assertIn("'Microsoft.VisualStudio.Component.VC.Tools.x86.x64'", self.text)
        self.assertIn("'Microsoft.VisualStudio.Component.VC.CMake.Project'", self.text)
        self.assertIn("$visualStudio = Get-FlutterStableVisualStudioInstance", self.text)
        self.assertIn("Common7\\IDE\\CommonExtensions\\Microsoft\\CMake\\CMake\\bin\\cmake.exe", self.text)
        self.assertNotIn("Get-Command -Name 'cmake.exe'", self.text)

    def test_sdk_silent_install_uses_only_documented_base_mode(self):
        self.assertIn("-ArgumentList '/q /norestart'", self.text)
        self.assertNotIn("OptionId.", self.text)
        self.assertNotIn("--insecure", self.text)
        self.assertNotIn("-k", self.text)
        self.assertNotIn("Set-ExecutionPolicy", self.text)
        self.assertNotIn("Import-Certificate", self.text)

    def test_diagnostics_print_raw_cmake_before_parsing_and_time_install_phases(self):
        self.assertLess(self.text.index("Write-Host $cmakeOutputText"),
                        self.text.index("$cmakeVersion = ConvertFrom-StableCmakeVersion $cmakeRawVersion"))
        for message in ("CMake executable={2}", "Visual Studio product update exit=",
                        "Windows SDK download exit=", "Windows SDK install exit=",
                        "validation elapsed=", "preflight elapsed"):
            with self.subTest(message=message):
                self.assertIn(message, self.text)
        for required in (r"Lib\10.0.28000.0\um\x64\kernel32.lib",
                         r"Lib\10.0.28000.0\ucrt\x64\ucrt.lib",
                         r"bin\10.0.28000.0\x64\rc.exe", r"bin\10.0.28000.0\x64\mt.exe"):
            self.assertIn(required, self.text)

    def test_fast_default_msvc_and_cmake_checks_precede_sdk_install(self):
        sdk_call = self.text.index("$sdkInstall = Install-OfficialWindowsSdk")
        for probe in ("$msvcDefaultVersion = [IO.File]::ReadAllText($msvcDefaultFile).Trim()",
                      "$cmakeOutput = @(& $cmakePath --version 2>&1)",
                      "$cmakeHelpOutput = @(& $cmakePath --help 2>&1)",
                      "CMake --help supports Visual Studio 18 2026 generator=",
                      "if ($cmakeVersion -lt $targetCmake)",
                      "if (-not $cmakeSupportsVs2026)", "$toolchainVerifyTimer.Stop()"):
            with self.subTest(probe=probe):
                self.assertLess(self.text.index(probe), sdk_call)
        self.assertIn(r"VC\Auxiliary\Build\Microsoft.VCToolsVersion.default.txt", self.text)
        self.assertIn("$msvcDefaultPath = Join-Path $msvcRoot $msvcDefaultVersion", self.text)
        self.assertNotIn("$msvcToolset = Get-ChildItem", self.text)
        self.assertLess(self.text.index("CMake --help supports Visual Studio 18 2026 generator="),
                        self.text.index("if ($cmakeVersion -lt $targetCmake)"))

    def test_powershell_cmake_parser_accepts_plain_and_msvc_but_rejects_previews(self):
        powershell = shutil.which("powershell.exe") or shutil.which("pwsh")
        if not powershell:
            self.skipTest("No PowerShell parser is installed in this test environment")
        # Execute only the isolated string parser and its numeric policy assignment.
        # The preflight script body and all installer commands are never invoked.
        command = r"""
$tokens=$null; $parseErrors=$null
$ast=[System.Management.Automation.Language.Parser]::ParseFile('__SCRIPT__',[ref]$tokens,[ref]$parseErrors)
if ($parseErrors.Count -gt 0) { throw 'Preflight source has parse errors' }
$parserFunction=$ast.FindAll({ param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
    $node.Name -eq 'ConvertFrom-StableCmakeVersion'
}, $true) | Select-Object -First 1
if (-not $parserFunction) { throw 'CMake parser function is missing' }
Invoke-Expression $parserFunction.Extent.Text
$baselineAssignment=$ast.FindAll({ param($node)
    $node -is [System.Management.Automation.Language.AssignmentStatementAst] -and
    $node.Left.Extent.Text -eq '$targetCmake'
}, $true) | Select-Object -First 1
if (-not $baselineAssignment) { throw 'Bundled CMake baseline assignment is missing' }
Invoke-Expression $baselineAssignment.Extent.Text
if ($targetCmake -ne [Version]'4.3.1') { throw 'Wrong VS-bundled CMake baseline' }
foreach ($raw in @('4.3.1-msvc1','4.4.3','4.4.3-msvc1')) {
    if ((ConvertFrom-StableCmakeVersion $raw) -lt $targetCmake) { throw ('Stable bundled version rejected: ' + $raw) }
}
if ((ConvertFrom-StableCmakeVersion '4.3.0-msvc99') -ge $targetCmake) {
    throw 'Older CMake vendor build bypassed the numeric baseline'
}
foreach ($raw in @('4.3.1','4.3.1-msvc1','4.4.3','4.4.3-msvc1','4.4.4-msvc12','4.3.0-msvc99')) {
    $numeric=ConvertFrom-StableCmakeVersion $raw
    Write-Output ($raw + '=' + $numeric.ToString())
}
foreach ($raw in @('4.4.3-rc1','4.5.0-alpha1','4.5.0-beta1','4.5.0-dev','4.5.0-msvc1-rc1','4.4.3-msvc','4.4.3-local','4.4.3.1')) {
    $accepted=$true
    try { [void](ConvertFrom-StableCmakeVersion $raw) } catch { $accepted=$false }
    if ($accepted) { throw ('Preview or unsupported CMake version was accepted: ' + $raw) }
}
""".replace("__SCRIPT__", str(SCRIPT).replace("'", "''"))
        result = subprocess.run([powershell, "-NoLogo", "-NoProfile", "-Command", command],
                                check=False, capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", "replace"))
        for expected in ("4.3.1=4.3.1", "4.3.1-msvc1=4.3.1", "4.4.3=4.4.3",
                         "4.4.3-msvc1=4.4.3", "4.4.4-msvc12=4.4.4", "4.3.0-msvc99=4.3.0"):
            self.assertIn(expected, result.stdout.decode("utf-8", "replace"))

    def test_fixture_conflict_guard_is_before_discovery_network_and_installers(self):
        guard = "if ($FixtureProbeOnly -and ($UpdateStableVisualStudio -or $InstallLatestWindowsSdk))"
        self.assertIn("[switch]$FixtureProbeOnly", self.text)
        start = self.text.index(guard)
        self.assertLess(start, self.text.index("$targetVisualStudio ="))
        for later in ("Assert-MicrosoftSignature $vswhere", "$json = & $vswhere", "$responseLines = @(& $curl", "Start-Process"):
            self.assertLess(start, self.text.index(later))
        block = self.text[start:self.text.index("$targetVisualStudio =")]
        self.assertIn("throw 'CI_FIXTURE_PROBE_CONFLICTS_WITH_INSTALLERS'", block)
        self.assertNotIn("Start-Process", block)

    def test_fixture_report_has_exact_diagnostic_schema_and_returns_before_production(self):
        body = self.text.split("function Get-FixtureProbeToolchain {", 1)[1].split("\nif ($FixtureProbeOnly) {", 1)[0]
        record = body.split("return [ordered]@{", 1)[1]
        keys = set(re.findall(r"^\s+([a-z_]+)\s*=", record, re.MULTILINE))
        self.assertEqual(keys, {
            "schema_version", "scope", "production_toolchain_validated", "downloads_or_updates_executed",
            "runner_label", "architecture", "visual_studio_path", "visual_studio_version",
            "msvc_toolset_path", "msvc_toolset_version", "cmake_path", "cmake_version",
            "windows_sdk_root", "windows_sdk_version", "rc_path", "mt_path",
        })
        self.assertIn("scope = 'supplementary_diagnostics_only_preinstalled_toolchain'", record)
        self.assertIn("production_toolchain_validated = $false", record)
        self.assertIn("downloads_or_updates_executed = $false", record)
        self.assertIn("architecture = 'x64'", record)
        branch = self.text.split("\nif ($FixtureProbeOnly) {", 1)[1].split("\nif ($UpdateStableVisualStudio) {", 1)[0]
        self.assertIn("$fixtureRecord = Get-FixtureProbeToolchain", branch)
        self.assertRegex(branch, r"\n\s+return\s*\n\}")
        for forbidden in ("Install-OfficialWindowsSdk", "Start-Process", "$targetVisualStudio", "$targetMsvc", "$targetCmake", "$targetSdkInclude"):
            self.assertNotIn(forbidden, branch + body)
        production = self.text.split("\nif ($UpdateStableVisualStudio) {", 1)[1]
        self.assertIn("$sdkInstall = Install-OfficialWindowsSdk", production)
        self.assertIn("use -InstallLatestWindowsSdk.", production)
        self.assertIn("if ($cmakeVersion -lt $targetCmake)", production)
        self.assertIn("-lt $targetVisualStudio", production)
        self.assertIn("-lt $targetMsvc", production)
        production_record = production.split("$record = [ordered]@{", 1)[1]
        self.assertNotIn("supplementary_diagnostics_only", production_record)
        self.assertNotIn("production_toolchain_validated", production_record)

    def test_fixture_selection_uses_same_instance_default_tools_and_complete_official_sdk(self):
        body = self.text.split("function Get-FixtureProbeToolchain {", 1)[1].split("\nif ($FixtureProbeOnly) {", 1)[0]
        self.assertIn("Get-FlutterStableVisualStudioInstance -FixtureVs2026Only", body)
        self.assertIn("'[18.0,19.0)'", self.text)
        self.assertIn("$vsVersion.Major -ne 18", body)
        for flag in ("$instance.isPrerelease -ne $false", "$instance.isComplete -ne $true", "$instance.isLaunchable -ne $true"):
            self.assertIn(flag, body)
        self.assertIn(r"VC\Auxiliary\Build\Microsoft.VCToolsVersion.default.txt", body)
        self.assertIn(r'VC\Tools\MSVC\$defaultVersion', body)
        self.assertIn(r"bin\Hostx64\x64\cl.exe", body)
        self.assertIn("Assert-FixtureMicrosoftTool $cl", body)
        self.assertNotRegex(body, r"&\s+\$cl\b|Start-Process[^\n]*\$cl\b")
        self.assertIn("ConvertFrom-StableCmakeVersion $rawCmakeVersion", body)
        self.assertIn("Visual Studio 18 2026", body)
        self.assertIn("$cmake --version", body)
        self.assertIn("$cmake --help", body)
        sdk = self.text.split("function Get-FixtureInstalledSdk {", 1)[1].split("function Get-FixtureProbeToolchain", 1)[0]
        self.assertIn("'Windows Kits\\10'", sdk)
        for required in (r"Include\$version\um\Windows.h", r"Include\$version\shared\sdkddkver.h", r"Include\$version\ucrt\stdio.h",
                         r"Lib\$version\um\x64\kernel32.lib", r"Lib\$version\um\x64\user32.lib", r"Lib\$version\ucrt\x64\ucrt.lib",
                         r"bin\$version\x64\rc.exe", r"bin\$version\x64\mt.exe"):
            self.assertIn(required, sdk)
        self.assertIn("Get-FixtureCanonicalPath", sdk)
        self.assertIn("Select-FixtureSdkVersion $candidates", sdk)
        self.assertIn("Assert-FixtureMicrosoftTool $rc", sdk)
        self.assertIn("Assert-FixtureMicrosoftTool $mt", sdk)
        self.assertNotIn("$targetSdkInclude", sdk)

    def test_fixture_paths_are_regular_no_reparse_and_new_output_is_isolated(self):
        helper = self.text.split("function Get-FixtureCanonicalPath", 1)[1].split("function Assert-FixtureMicrosoftTool", 1)[0]
        self.assertIn("foreach ($component in $all)", helper)
        self.assertIn("[IO.FileAttributes]::ReparsePoint", helper)
        self.assertIn("$item -isnot [IO.FileInfo]", helper)
        self.assertIn("$item -isnot [IO.DirectoryInfo]", helper)
        self.assertIn("[IO.Path]::GetFullPath", helper)
        branch = self.text.split("\nif ($FixtureProbeOnly) {", 1)[1].split("\nif ($UpdateStableVisualStudio) {", 1)[0]
        self.assertIn("Test-FixturePathWithin $fixtureOutput $sourceRoot", branch)
        self.assertIn("Test-FixturePathWithin $fixtureOutput $toolRoot", branch)
        self.assertIn("Get-FixtureCanonicalPath $existingParent 'Directory'", branch)
        self.assertIn("Get-FixtureCanonicalPath $outputParent 'Directory'", branch)
        self.assertIn("[IO.FileMode]::CreateNew", branch)
        self.assertIn("Toolchain preflight result must be a new file.", branch)
        self.assertNotIn("Set-ItemProperty", branch)
        self.assertNotIn("$env:PATH =", branch)

    def test_fixture_sdk_selector_and_conflict_guard_are_data_only(self):
        powershell = shutil.which("powershell.exe") or shutil.which("pwsh")
        if not powershell:
            self.skipTest("No PowerShell parser is installed in this test environment")
        command = r"""
$tokens=$null; $errors=$null
$ast=[System.Management.Automation.Language.Parser]::ParseFile('__SCRIPT__',[ref]$tokens,[ref]$errors)
if ($errors.Count) { throw 'Parse failure' }
$names=@('Select-FixtureSdkVersion','Test-FixturePathWithin')
foreach ($name in $names) {
    $f=$ast.FindAll({ param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq $name },$true) | Select-Object -First 1
    if (-not $f) { throw 'Missing pure helper' }
    Invoke-Expression $f.Extent.Text
}
$candidates=@(
    [pscustomobject]@{Version='10.0.26100.0';Complete=$true},
    [pscustomobject]@{Version='10.0.28000.0';Complete=$false},
    [pscustomobject]@{Version='10.0.29000.0-preview';Complete=$true},
    [pscustomobject]@{Version='..\outside';Complete=$true},
    [pscustomobject]@{Version='10.0.9999999999999999.0';Complete=$true}
)
if ((Select-FixtureSdkVersion $candidates) -ne '10.0.26100.0') { throw 'Incomplete or preview SDK selected' }
$candidates[1].Complete=$true
if ((Select-FixtureSdkVersion $candidates) -ne '10.0.28000.0') { throw 'Highest complete SDK was not selected' }
$accepted=$true
try { [void](Select-FixtureSdkVersion @([pscustomobject]@{Version='10.0.26100.0';Complete='true'})) } catch { $accepted=$false }
if ($accepted) { throw 'Non-boolean completeness accepted' }
if (-not (Test-FixturePathWithin 'C:\src\tools\report.json' 'C:\src')) { throw 'Nested output not detected' }
if (Test-FixturePathWithin 'C:\src-copy\report.json' 'C:\src') { throw 'Sibling output falsely matches' }
$guard=$ast.FindAll({ param($n) $n -is [System.Management.Automation.Language.IfStatementAst] -and $n.Clauses[0].Item1.Extent.Text -like '*$FixtureProbeOnly*UpdateStableVisualStudio*InstallLatestWindowsSdk*' },$true) | Select-Object -First 1
if (-not $guard) { throw 'Missing early switch guard' }
foreach ($fixture in @($false,$true)) {
    foreach ($update in @($false,$true)) {
        foreach ($install in @($false,$true)) {
            $FixtureProbeOnly=$fixture; $UpdateStableVisualStudio=$update; $InstallLatestWindowsSdk=$install
            $rejected=$false
            try { Invoke-Expression $guard.Extent.Text } catch {
                if ($_.Exception.Message -ne 'CI_FIXTURE_PROBE_CONFLICTS_WITH_INSTALLERS') { throw }
                $rejected=$true
            }
            if ($rejected -ne ($fixture -and ($update -or $install))) { throw 'Wrong installer-switch policy' }
        }
    }
}
Write-Output 'data-only fixture policy checks passed; no toolchain/runtime executed'
""".replace("__SCRIPT__", str(SCRIPT).replace("'", "''"))
        result = subprocess.run([powershell, "-NoLogo", "-NoProfile", "-Command", command],
                                check=False, capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", "replace"))
        self.assertIn("data-only fixture policy checks passed", result.stdout.decode("utf-8", "replace"))

    def test_script_has_no_powershell_parse_errors_when_parser_is_available(self):
        powershell = shutil.which("powershell.exe") or shutil.which("pwsh")
        if not powershell:
            self.skipTest("No PowerShell parser is installed in this test environment")
        path = str(SCRIPT).replace("'", "''")
        command = (
            "$tokens=$null; $parseErrors=$null; "
            "[void][System.Management.Automation.Language.Parser]::ParseFile('{}',[ref]$tokens,[ref]$parseErrors); "
            "if ($parseErrors.Count -gt 0) {{ "
            "$parseErrors | ForEach-Object {{ [Console]::Error.WriteLine($_.Message) }}; exit 1 "
            "}}"
        ).format(path)
        result = subprocess.run([powershell, "-NoLogo", "-NoProfile", "-Command", command],
                                check=False, capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", "replace"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
