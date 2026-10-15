"""Static safety tests for the CI-only PowerShell toolchain updater.

These tests parse but never execute the installer/update commands. The actual
VS/SDK install remains an Actions-runner-only operation.
"""
from pathlib import Path
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
        for text in ("18.11.0.0", "14.50.0", "4.4.3", "10.0.28000.0", "2957"):
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
        self.assertIn("CMake 4.4.3 or newer is required", self.text)

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
        # Execute only the isolated, repository-owned string parser function.
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
foreach ($raw in @('4.4.3','4.4.3-msvc1','4.4.4-msvc12','4.4.2-msvc99')) {
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
        for expected in ("4.4.3=4.4.3", "4.4.3-msvc1=4.4.3", "4.4.4-msvc12=4.4.4",
                         "4.4.2-msvc99=4.4.2"):
            self.assertIn(expected, result.stdout.decode("utf-8", "replace"))

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
