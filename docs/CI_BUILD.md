# Manual Windows CI build

The GitHub Actions workflow is **manual only** (`workflow_dispatch`) and builds a Windows x64 application bundle. It does not create a release, publish a repository package, sign binaries, or certify legal/runtime acceptance.

## Runner and toolchain

The job uses the official `windows-2025-vs2026` hosted runner label. On that ephemeral VM it:

- Verifies and updates the installed stable Visual Studio 2026 product through the official Visual Studio Installer, then requires VS 18.11.0 or newer and its official default MSVC toolset 14.50 or newer, as identified by `Microsoft.VCToolsVersion.default.txt`.
- Mirrors Flutter 3.47.7's stable `vswhere` workload/component queries and audits that selected Visual Studio instance's **bundled CMake**, never a substitute PATH executable. The bundled-CMake numeric baseline is **4.3.1**, matching the observed official VS 18.11 bundle `4.3.1-msvc1`; this is **not** a claim that standalone upstream Kitware CMake's latest release is 4.3.1. Plain stable versions and Microsoft's `-msvcN` suffix are accepted at or above that baseline; rc/alpha/beta/dev versions remain rejected. CI preserves the full raw version output and requires the real executable to advertise the Visual Studio 18 2026 generator.
- Only after the quick VS/MSVC/CMake checks pass, downloads the Windows SDK from Microsoft's `go.microsoft.com/fwlink/?linkid=2382519` source into a fresh UUID directory. The CI helper requires HTTPS redirects to remain on the approved Microsoft download host, validates the downloaded SHA-256 and Microsoft's Authenticode signature before execution, installs silently with the Windows SDK 10.0.28000 product-line `/q /norestart` mode, and then requires both SDK include version `10.0.28000.0` and servicing version 28000.2957 or newer, plus the required x64 headers, libraries and tools. It does not assume unverified optional feature IDs.
- The project selects the audited SDK from a CI-only environment value before `project()` initializes the toolchain, then records actual post-project `CHASTEADY_*` cache evidence. CI checks the real CMake executable/version, Visual Studio 18 2026 x64 generator, selected default MSVC compiler, and Windows SDK target against the preflight evidence.

Observed run `38771603533` on 2026-10-15 spent **2,270.74 seconds (37 minutes 50.74 seconds)** in the Visual Studio product update, which reached VS `18.11.12306.390` with default MSVC `14.51.36231`. The subsequent quick probe reported bundled CMake `4.3.1-msvc1` and confirmed Visual Studio 18 2026 generator support. That run stopped at the earlier incorrect 4.4.3 bundled-CMake floor, **before SDK downloading or native compilation began**; its elapsed time must not be described as SDK-install or compilation time. The corrected baseline retains the official vendor-supplied toolchain combination rather than patching the SDK or substituting another CMake executable.

All toolchain updates happen only on the disposable hosted runner. The workflow does not alter this workstation's PATH, trust store, proxy, security settings, or Visual Studio installation.

## Build and validation scope

`tools/ci_provision_flutter.py` downloads Flutter 3.47.7 stable only from Google's official Flutter release bucket. It rejects redirects, verifies the pinned archive byte count and SHA-256 before ZIP inspection, audits bounded safe members, and extracts to a separate new UUID directory. The font helper fetches the Noto Sans SC variable font by its pinned Google Fonts Git blob through the official GitHub API, verifies Git blob SHA-1/SHA-256/size and TrueType structure, and puts it only in an ephemeral build directory. The TTF binary is intentionally not part of the public source checkout; its SIL Open Font License and provenance text remain available.

The UI pipeline runs only:

1. `flutter pub get --enforce-lockfile`
2. `flutter gen-l10n`
3. `flutter build windows --release`
4. `flutter build web --release --no-web-resources-cdn --pwa-strategy=none`

It does not run UI analysis, UI tests, a browser, GUI acceptance, or video export. Flutter/Dart state and the audited `$git` shim are child-process scoped; Git and pub caches live under the runner's temporary build tree.

For the Worker, CI provisions the current pinned isolated CPython runtime from the repository root, reruns all discovered backend tests, builds a fresh PyInstaller one-folder Worker from source, and runs the existing bounded stdio/loopback HTTP smoke and file-inventory checks. It never uses a prebuilt local Worker.

The private V9 math golden inputs stay local and are **not** uploaded, embedded, or rerun in CI. CI requires exactly one approved, unsigned local summary in `docs/` named `worker_math_golden_summary_20261015_<uuid>.json`. The sidecar is strictly checked against the current worker/math source inventory, CPython archive digest, exact latest-verified wheel identities, canonical error thresholds, three anonymous passing cases, and explicit local-only/no-input-path flags. A source, runtime, pin, schema, or measured-result mismatch stops the job. The manifest states `private_goldens_rerun_in_ci: false`; the local evidence is not represented as a CI golden rerun or cryptographic attestation.

## Artifact and claims

On success, the workflow uploads only:

- `ChaSteady-Windows-x64.zip`
- `ChaSteady-Windows-x64.zip.sha256`
- `ChaSteady-Windows-x64.manifest.json`

The app bundle contains the real `ChaSteady.exe`, Flutter Windows engine/data, freshly built one-folder Worker, offline web assets, README, `BUILD_STATUS.json`, original `LICENSE`, third-party notices, and selected license text files. License JSON manifests, non-license model files, caches, profiles, private build state, logs, credentials, and source media are excluded. The artifact expires after seven days.

`BUILD_STATUS.json` and the manifest explicitly keep `runtime_acceptance_verified`, `public_distribution_cleared`, signing, and legal certification false. **MIT applies only to original ChaSteady code**; bundled third-party terms remain applicable. A successful CI build is not a release or an end-user runtime acceptance test.

## Sources pinned or checked by CI

- Flutter stable archive: `https://storage.googleapis.com/flutter_infra_release/releases/stable/windows/flutter_windows_3.47.7-stable.zip`
- Visual Studio command-line product update documentation: `https://learn.microsoft.com/en-us/visualstudio/install/command-line-parameter-examples?view=visualstudio`
- Windows SDK installer link: `https://go.microsoft.com/fwlink/?linkid=2382519`
- Noto Sans SC source repository: `https://github.com/google/fonts`, commit `a85815a42757630ce188fdad368c2dfc444d4773`, path `ofl/notosanssc/NotoSansSC[wght].ttf`, Git blob `fb0637bafbcd804fe32152370a1225990745b4bc`
