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
