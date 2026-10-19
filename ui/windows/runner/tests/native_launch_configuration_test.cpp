// 本 fixture 不创建窗口、不启动 Flutter/Worker，只在全新证据子目录写测试数据。
#include "native_launch_configuration.h"

#include <aclapi.h>
#include <sddl.h>
#include <shlobj.h>
#include <winioctl.h>

#include <cstdio>
#include <cstring>
#include <cstdlib>
#include <memory>
#include <string>
#include <vector>

namespace {
int checks = 0;
int failures = 0;
void Check(bool condition, const char* description) {
  ++checks;
  if (!condition) { ++failures; std::fprintf(stderr, "FAIL: %s (Win32 %lu)\n", description, GetLastError()); }
}

bool Junction(const std::wstring& link, const std::wstring& destination) {
  if (!CreateDirectoryW(link.c_str(), nullptr)) return false;
  HANDLE handle = CreateFileW(link.c_str(), GENERIC_WRITE, 0, nullptr, OPEN_EXISTING,
      FILE_FLAG_BACKUP_SEMANTICS | FILE_FLAG_OPEN_REPARSE_POINT, nullptr);
  if (handle == INVALID_HANDLE_VALUE) return false;
  const std::wstring substitute = L"\\??\\" + destination;
  const size_t path_bytes = (substitute.size() + 1) * sizeof(wchar_t);
  std::vector<BYTE> storage(16 + path_bytes + sizeof(wchar_t), 0);
  auto* tag = reinterpret_cast<DWORD*>(storage.data());
  *tag = IO_REPARSE_TAG_MOUNT_POINT;
  auto* words = reinterpret_cast<WORD*>(storage.data() + 4);
  words[0] = static_cast<WORD>(storage.size() - 8);
  words[2] = 0;
  words[3] = static_cast<WORD>(substitute.size() * sizeof(wchar_t));
  words[4] = static_cast<WORD>(path_bytes);
  words[5] = 0;
  memcpy(storage.data() + 16, substitute.data(), substitute.size() * sizeof(wchar_t));
  DWORD returned = 0;
  const BOOL result = DeviceIoControl(handle, FSCTL_SET_REPARSE_POINT, storage.data(),
      static_cast<DWORD>(storage.size()), nullptr, 0, &returned, nullptr);
  CloseHandle(handle);
  return result != FALSE;
}

bool SetAcl(const std::wstring& path, const std::wstring& sddl) {
  PSECURITY_DESCRIPTOR descriptor = nullptr;
  if (!ConvertStringSecurityDescriptorToSecurityDescriptorW(sddl.c_str(), SDDL_REVISION_1,
                                                           &descriptor, nullptr)) return false;
  PACL dacl = nullptr;
  BOOL present = FALSE;
  BOOL defaulted = FALSE;
  const bool result = GetSecurityDescriptorDacl(descriptor, &present, &dacl, &defaulted) && present &&
      SetNamedSecurityInfoW(const_cast<wchar_t*>(path.c_str()), SE_FILE_OBJECT,
          DACL_SECURITY_INFORMATION | PROTECTED_DACL_SECURITY_INFORMATION,
          nullptr, nullptr, dacl, nullptr) == ERROR_SUCCESS;
  LocalFree(descriptor);
  return result;
}
}  // namespace

int wmain(int argc, wchar_t** argv) {
  if (argc != 2) { std::fprintf(stderr, "One new absolute evidence directory is required.\n"); return 2; }
  const std::wstring base = argv[1];
  if (!CreateDirectoryW(base.c_str(), nullptr)) return 2;
  const std::wstring bundle = base + L"\\bundle";
  if (!CreateDirectoryW(bundle.c_str(), nullptr)) return 2;
  using Configuration = chasteady::NativeLaunchConfiguration;
  std::vector<std::wstring> remaining;
  std::shared_ptr<const Configuration> configuration;
  std::wstring error;
  auto prepare = [&](const std::vector<std::wstring>& arguments) {
    return Configuration::Prepare(arguments, bundle, &remaining, &configuration, &error);
  };
  Check(prepare({L"--dart-test", L"value"}) && !configuration->has_new_profile() &&
        remaining == std::vector<std::wstring>({L"--dart-test", L"value"}), "default arguments unchanged");
  Check(prepare({}) && configuration->Revalidate(L"unused") && configuration->profile_root().empty(),
        "default configuration does not resolve data paths");
  const std::vector<std::wstring> invalid = {
      L"relative\\profile", L"C:relative", L"\\\\server\\share\\profile", L"\\\\?\\C:\\profile",
      L"\\\\.\\NUL", base + L"\\..\\escape", base + L"\\a:b", base + L"\\NUL",
      base + L"\\trailing.", base + L"\\trailing ", base + L"\\double\\\\leaf",
      base + L"\\missing-parent\\leaf", bundle, bundle + L"\\inside", base,
      base + L"\\wild*card", base + L"\\leaf\\", std::wstring(33000, L'a')};
  for (const auto& path : invalid)
    Check(!prepare({L"--new-profile-root", path}) && !configuration, "reject invalid/existing/overlapping profile");
  Check(!prepare({L"--new-profile-root"}) && !configuration, "reject missing profile argument");
  Check(!prepare({L"--new-profile-root", L"--another"}) && !configuration, "reject next switch as path");
  Check(!prepare({L"--new-profile-root=" + base + L"\\bad"}) && !configuration, "reject equals spelling");
  Check(!prepare({L"--new-profile-root-typo", base + L"\\bad"}) && !configuration,
        "reserved profile-switch spelling cannot silently launch production data");
  Check(!prepare({L"--new-profile-root", base + L"\\first", L"--new-profile-root", base + L"\\second"}) &&
        !configuration, "reject duplicate without creating first root");
  Check(GetFileAttributesW((base + L"\\first").c_str()) == INVALID_FILE_ATTRIBUTES,
        "parse errors do not create a profile");

  PWSTR local = nullptr;
  Check(SUCCEEDED(SHGetKnownFolderPath(FOLDERID_LocalAppData, KF_FLAG_DONT_VERIFY, nullptr, &local)),
        "read-only default KnownFolder identity");
  if (local != nullptr) {
    HANDLE token = nullptr;
    Check(OpenProcessToken(GetCurrentProcess(), TOKEN_QUERY, &token) != FALSE, "read current SID token");
    DWORD bytes = 0;
    GetTokenInformation(token, TokenUser, nullptr, 0, &bytes);
    std::vector<BYTE> storage(bytes);
    Check(GetTokenInformation(token, TokenUser, storage.data(), bytes, &bytes) != FALSE, "read token SID");
    CloseHandle(token);
    LPWSTR sid = nullptr;
    Check(ConvertSidToStringSidW(reinterpret_cast<TOKEN_USER*>(storage.data())->User.Sid, &sid) != FALSE,
          "format token SID");
    if (sid != nullptr) {
      const std::wstring default_root = std::wstring(local) + L"\\ChaSteady\\Users\\" + sid + L"\\DesktopData";
      Check(!prepare({L"--new-profile-root", default_root}) && !configuration, "reject exact default root");
      Check(!prepare({L"--new-profile-root", default_root + L"\\nested"}) && !configuration,
            "reject default descendant without creating it");
      const std::wstring profile = base + L"\\新建 profile";
      Check(prepare({L"--dart-before", L"--new-profile-root", profile, L"--dart-after"}),
            "create new Unicode private profile");
      if (configuration) {
        Check(configuration->has_new_profile() && !configuration->profile_root().empty(), "immutable root selected");
        Check(remaining == std::vector<std::wstring>({L"--dart-before", L"--dart-after"}),
              "native option not forwarded to Dart");
        Check(configuration->Revalidate(bundle), "new profile SID identity ACL and disjoint validation");
        Check(!MoveFileExW(profile.c_str(), (base + L"\\moved").c_str(), 0), "pinned profile cannot be renamed");
        Check(!MoveFileExW(bundle.c_str(), (base + L"\\bundle-moved").c_str(), 0), "pinned bundle cannot be renamed");
        Check(!configuration->Revalidate(base), "resource-root identity cannot be replaced by an ancestor");
        Check(SetAcl(profile, L"D:P(A;OICI;FA;;;WD)"), "fixture can mutate own synthetic root ACL");
        Check(!configuration->Revalidate(bundle), "ACL tampering fails closed");
        Check(SetAcl(profile, L"D:P(A;OICI;FA;;;" + std::wstring(sid) + L")(A;OICI;FA;;;SY)"),
              "restore fixture private ACL");
        Check(configuration->Revalidate(bundle), "restored exact protected ACL accepted");
        configuration.reset();
        Check(!prepare({L"--new-profile-root", profile}) && !configuration,
              "existing private empty profile is never reused");
      }
      LocalFree(sid);
    }
    CoTaskMemFree(local);
  }
  const std::wstring target = base + L"\\junction-target";
  Check(CreateDirectoryW(target.c_str(), nullptr) != FALSE, "create owned junction target");
  const std::wstring link = base + L"\\junction";
  const bool junction = Junction(link, target);
  Check(junction, "create owned local junction for reparse rejection");
  if (junction) {
    Check(!prepare({L"--new-profile-root", link + L"\\profile"}) && !configuration, "reject reparse ancestor");
    Check(GetFileAttributesW((target + L"\\profile").c_str()) == INVALID_FILE_ATTRIBUTES,
          "reparse rejection does not create target profile");
  }
  Check(RemoveDirectoryW(link.c_str()) != FALSE, "remove only owned fixture junction");
  std::printf("%s: native profile fixture %d checks, %d failures; no Worker/Flutter/window.\n",
              failures == 0 ? "PASS" : "FAIL", checks, failures);
  return failures == 0 ? EXIT_SUCCESS : EXIT_FAILURE;
}
