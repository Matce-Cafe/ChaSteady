#include "native_launch_configuration.h"

#include <aclapi.h>
#include <sddl.h>
#include <shlobj.h>

#include <algorithm>
#include <cwctype>
#include <utility>

namespace chasteady {
namespace {

class Handle final {
 public:
  explicit Handle(HANDLE value = INVALID_HANDLE_VALUE) : value_(value) {}
  ~Handle() { if (value_ != INVALID_HANDLE_VALUE && value_ != nullptr) CloseHandle(value_); }
  Handle(const Handle&) = delete;
  Handle& operator=(const Handle&) = delete;
  Handle(Handle&& other) noexcept : value_(other.value_) { other.value_ = INVALID_HANDLE_VALUE; }
  HANDLE get() const { return value_; }
  explicit operator bool() const { return value_ != INVALID_HANDLE_VALUE && value_ != nullptr; }
 private:
  HANDLE value_;
};

bool EqualPath(const std::wstring& left, const std::wstring& right) {
  return CompareStringOrdinal(left.c_str(), static_cast<int>(left.size()),
      right.c_str(), static_cast<int>(right.size()), TRUE) == CSTR_EQUAL;
}

bool Disjoint(const std::wstring& left, const std::wstring& right) {
  const auto within = [](const std::wstring& parent, const std::wstring& child) {
    return child.size() > parent.size() &&
        EqualPath(parent, child.substr(0, parent.size())) &&
        (parent.back() == L'\\' || child[parent.size()] == L'\\');
  };
  return !left.empty() && !right.empty() && !EqualPath(left, right) &&
      !within(left, right) && !within(right, left);
}

bool ReservedComponent(const std::wstring& part) {
  std::wstring stem = part.substr(0, part.find(L'.'));
  while (!stem.empty() && stem.back() == L' ') stem.pop_back();
  std::transform(stem.begin(), stem.end(), stem.begin(), [](wchar_t ch) {
    return static_cast<wchar_t>(towupper(ch));
  });
  return stem == L"CON" || stem == L"PRN" || stem == L"AUX" || stem == L"NUL" ||
      stem == L"CONIN$" || stem == L"CONOUT$" ||
      (stem.size() == 4 && (stem.substr(0, 3) == L"COM" || stem.substr(0, 3) == L"LPT") &&
       ((stem[3] >= L'0' && stem[3] <= L'9') || stem[3] == L'¹' ||
        stem[3] == L'²' || stem[3] == L'³'));
}

bool StrictPath(std::wstring value, std::wstring* output) {
  if (output == nullptr || value.size() < 4 || value.size() >= 32700 ||
      !((value[0] >= L'A' && value[0] <= L'Z') || (value[0] >= L'a' && value[0] <= L'z')) ||
      value[1] != L':' || (value[2] != L'\\' && value[2] != L'/')) return false;
  std::replace(value.begin(), value.end(), L'/', L'\\');
  if (value.back() == L'\\') return false;
  size_t begin = 3;
  while (begin < value.size()) {
    const size_t end = value.find(L'\\', begin);
    const std::wstring part = value.substr(begin, end == std::wstring::npos ? end : end - begin);
    if (part.empty() || part == L"." || part == L".." || part.size() > 255 ||
        part.back() == L'.' || part.back() == L' ' || ReservedComponent(part)) return false;
    for (wchar_t ch : part) {
      if (ch < 32 || ch == L':' || ch == L'"' || ch == L'<' || ch == L'>' ||
          ch == L'|' || ch == L'?' || ch == L'*') return false;
    }
    if (end == std::wstring::npos) break;
    begin = end + 1;
  }
  if (WideCharToMultiByte(CP_UTF8, WC_ERR_INVALID_CHARS, value.data(),
                         static_cast<int>(value.size()), nullptr, 0, nullptr, nullptr) <= 0) return false;
  *output = std::move(value);
  return true;
}

std::wstring Parent(const std::wstring& path) {
  const size_t last = path.find_last_of(L'\\');
  return last == 2 ? path.substr(0, 3) : path.substr(0, last);
}

bool CurrentSid(std::wstring* text, std::vector<BYTE>* sid) {
  HANDLE raw = nullptr;
  if (!OpenProcessToken(GetCurrentProcess(), TOKEN_QUERY, &raw)) return false;
  Handle token(raw);
  DWORD bytes = 0;
  GetTokenInformation(token.get(), TokenUser, nullptr, 0, &bytes);
  if (bytes == 0 || bytes > 65536) return false;
  std::vector<BYTE> storage(bytes);
  if (!GetTokenInformation(token.get(), TokenUser, storage.data(), bytes, &bytes)) return false;
  const auto* user = reinterpret_cast<const TOKEN_USER*>(storage.data());
  if (!IsValidSid(user->User.Sid)) return false;
  LPWSTR value = nullptr;
  if (!ConvertSidToStringSidW(user->User.Sid, &value)) return false;
  *text = value;
  LocalFree(value);
  const DWORD length = GetLengthSid(user->User.Sid);
  sid->assign(static_cast<BYTE*>(user->User.Sid), static_cast<BYTE*>(user->User.Sid) + length);
  return true;
}

bool DirectoryHandle(HANDLE handle) {
  BY_HANDLE_FILE_INFORMATION info{};
  return GetFileInformationByHandle(handle, &info) &&
      (info.dwFileAttributes & (FILE_ATTRIBUTE_DIRECTORY | FILE_ATTRIBUTE_REPARSE_POINT)) ==
          FILE_ATTRIBUTE_DIRECTORY;
}

bool FinalPath(HANDLE handle, std::wstring* path, DWORD volume_name = VOLUME_NAME_DOS) {
  std::vector<wchar_t> storage(32768);
  const DWORD size = GetFinalPathNameByHandleW(handle, storage.data(),
      static_cast<DWORD>(storage.size()), FILE_NAME_NORMALIZED | volume_name);
  if (size == 0 || size >= storage.size()) return false;
  std::wstring result(storage.data(), size);
  if (volume_name == VOLUME_NAME_GUID) {
    if (result.rfind(L"\\\\?\\Volume{", 0) != 0) return false;
  } else {
    if (result.rfind(L"\\\\?\\", 0) != 0 || result.rfind(L"\\\\?\\UNC\\", 0) == 0) return false;
    result.erase(0, 4);
  }
  while (result.size() > 3 && result.back() == L'\\') result.pop_back();
  *path = std::move(result);
  return true;
}

// 每一级都以 OPEN_REPARSE_POINT 打开且不共享删除，阻止验收与启动之间被重命名置换。
bool PinExistingDirectories(const std::wstring& path, std::vector<Handle>* handles,
                            std::wstring* canonical, bool allow_missing_suffix = false,
                            DWORD volume_name = VOLUME_NAME_DOS) {
  std::wstring current = path.substr(0, 3);
  size_t position = 3;
  for (;;) {
    Handle directory(CreateFileW(current.c_str(), FILE_LIST_DIRECTORY | FILE_READ_ATTRIBUTES | READ_CONTROL,
        FILE_SHARE_READ | FILE_SHARE_WRITE, nullptr, OPEN_EXISTING,
        FILE_FLAG_BACKUP_SEMANTICS | FILE_FLAG_OPEN_REPARSE_POINT, nullptr));
    if (!directory) {
      const DWORD error = GetLastError();
      if (!allow_missing_suffix || (error != ERROR_FILE_NOT_FOUND && error != ERROR_PATH_NOT_FOUND) ||
          handles->empty()) return false;
      std::wstring parent;
      if (!FinalPath(handles->back().get(), &parent, volume_name)) return false;
      const std::wstring suffix = path.substr(current.find_last_of(L'\\') + 1);
      *canonical = parent + (parent.back() == L'\\' ? L"" : L"\\") + suffix;
      return true;
    }
    if (!DirectoryHandle(directory.get())) return false;
    handles->push_back(std::move(directory));
    if (position >= path.size()) return FinalPath(handles->back().get(), canonical, volume_name);
    const size_t end = path.find(L'\\', position);
    current = path.substr(0, end);
    position = end == std::wstring::npos ? path.size() : end + 1;
  }
}

bool PrivateAcl(HANDLE directory, PSID user) {
  PSID owner = nullptr;
  PACL dacl = nullptr;
  PSECURITY_DESCRIPTOR descriptor = nullptr;
  if (GetSecurityInfo(directory, SE_FILE_OBJECT, OWNER_SECURITY_INFORMATION | DACL_SECURITY_INFORMATION,
                      &owner, nullptr, &dacl, nullptr, &descriptor) != ERROR_SUCCESS) return false;
  SECURITY_DESCRIPTOR_CONTROL control = 0;
  DWORD revision = 0;
  BYTE system_buffer[SECURITY_MAX_SID_SIZE]{};
  DWORD system_size = sizeof(system_buffer);
  const bool system_valid = CreateWellKnownSid(WinLocalSystemSid, nullptr, system_buffer, &system_size) != FALSE;
  bool valid = owner != nullptr && dacl != nullptr && system_valid &&
      GetSecurityDescriptorControl(descriptor, &control, &revision) &&
      (control & SE_DACL_PROTECTED) != 0 && EqualSid(owner, user) && dacl->AceCount == 2;
  bool saw_user = false;
  bool saw_system = false;
  for (DWORD index = 0; valid && index < dacl->AceCount; ++index) {
    void* raw = nullptr;
    if (!GetAce(dacl, index, &raw)) { valid = false; break; }
    const auto* ace = static_cast<const ACCESS_ALLOWED_ACE*>(raw);
    if (ace->Header.AceType != ACCESS_ALLOWED_ACE_TYPE ||
        ace->Header.AceSize < sizeof(ACCESS_ALLOWED_ACE) || ace->Mask != FILE_ALL_ACCESS ||
        ace->Header.AceFlags != (OBJECT_INHERIT_ACE | CONTAINER_INHERIT_ACE)) {
      valid = false;
      break;
    }
    PSID sid = const_cast<DWORD*>(&ace->SidStart);
    if (!IsValidSid(sid)) { valid = false; break; }
    if (EqualSid(sid, user) && !saw_user) saw_user = true;
    else if (EqualSid(sid, system_buffer) && !saw_system) saw_system = true;
    else valid = false;
  }
  LocalFree(descriptor);
  return valid && saw_user && saw_system;
}

bool DefaultPath(const std::wstring& sid, std::wstring* result) {
  PWSTR local = nullptr;
  // 不使用环境变量，也不允许 KnownFolder 创建或默认 JobStore 触碰目录。
  const HRESULT hr = SHGetKnownFolderPath(FOLDERID_LocalAppData, KF_FLAG_DONT_VERIFY, nullptr, &local);
  if (FAILED(hr) || local == nullptr) return false;
  std::wstring path = local;
  CoTaskMemFree(local);
  return StrictPath(path + L"\\ChaSteady\\Users\\" + sid + L"\\DesktopData", result);
}

bool Error(std::wstring* error, const wchar_t* reason) {
  if (error != nullptr) *error = reason;
  return false;
}

}  // namespace

class NativeLaunchConfiguration::Impl final {
 public:
  std::wstring root;
  std::wstring resource;
  std::wstring root_comparison;
  std::wstring resource_comparison;
  std::wstring sid_text;
  std::vector<BYTE> sid;
  std::vector<Handle> pinned;
  BY_HANDLE_FILE_INFORMATION identity{};
};

NativeLaunchConfiguration::NativeLaunchConfiguration() : impl_(std::make_unique<Impl>()) {}
NativeLaunchConfiguration::~NativeLaunchConfiguration() = default;

bool NativeLaunchConfiguration::Prepare(const std::vector<std::wstring>& arguments,
    const std::wstring& resource_root, std::vector<std::wstring>* remaining_arguments,
    std::shared_ptr<const NativeLaunchConfiguration>* configuration, std::wstring* error) {
  if (remaining_arguments == nullptr || configuration == nullptr) return false;
  configuration->reset();
  remaining_arguments->clear();
  std::wstring requested;
  bool seen = false;
  for (size_t index = 0; index < arguments.size(); ++index) {
    const std::wstring& value = arguments[index];
    if (value == L"--new-profile-root") {
      if (seen || index + 1 >= arguments.size() || arguments[index + 1].rfind(L"--", 0) == 0)
        return Error(error, L"--new-profile-root requires one new absolute private directory.");
      seen = true;
      requested = arguments[++index];
    } else if (value.rfind(L"--new-profile-root", 0) == 0) {
      return Error(error, L"Use --new-profile-root followed by a separate absolute path.");
    } else {
      remaining_arguments->push_back(value);
    }
  }
  std::shared_ptr<NativeLaunchConfiguration> prepared(new NativeLaunchConfiguration());
  if (!seen) { *configuration = std::move(prepared); return true; }
  std::wstring root;
  std::wstring resource;
  std::wstring default_path;
  auto& state = *prepared->impl_;
  if (!StrictPath(requested, &root) || !StrictPath(resource_root, &resource) ||
      !CurrentSid(&state.sid_text, &state.sid) || !DefaultPath(state.sid_text, &default_path))
    return Error(error, L"The new profile path or current Windows identity is invalid.");
  std::vector<Handle> resource_handles;
  std::vector<Handle> default_handles;
  std::wstring canonical_default;
  std::wstring canonical_parent;
  if (!PinExistingDirectories(resource, &resource_handles, &state.resource) ||
      !PinExistingDirectories(default_path, &default_handles, &canonical_default, true, VOLUME_NAME_GUID) ||
      !PinExistingDirectories(Parent(root), &state.pinned, &canonical_parent))
    return Error(error, L"Profile, default-data and application paths must contain no reparse points.");
  state.root = canonical_parent + (canonical_parent.back() == L'\\' ? L"" : L"\\") +
      root.substr(root.find_last_of(L'\\') + 1);
  std::wstring parent_comparison;
  if (!FinalPath(state.pinned.back().get(), &parent_comparison, VOLUME_NAME_GUID) ||
      !FinalPath(resource_handles.back().get(), &state.resource_comparison, VOLUME_NAME_GUID))
    return Error(error, L"The physical volume identity of the isolation boundaries is unavailable.");
  // 卷 GUID 加规范化卷内路径用于比较，DOS drive / SUBST 别名不能假装与默认根不相交。
  state.root_comparison = parent_comparison + L"\\" + root.substr(root.find_last_of(L'\\') + 1);
  if (!Disjoint(state.root_comparison, canonical_default) ||
      !Disjoint(state.root_comparison, state.resource_comparison))
    return Error(error, L"The new profile must be disjoint from default data and the complete application bundle.");
  // CREATE_NEW 的目录等价操作：绝不接受已经存在的空目录，也不修补外部目录权限。
  const DWORD existing = GetFileAttributesW(state.root.c_str());
  const DWORD lookup_error = GetLastError();
  if (existing != INVALID_FILE_ATTRIBUTES || lookup_error != ERROR_FILE_NOT_FOUND)
    return Error(error, L"The new profile directory must not already exist; its parent must exist.");
  PSECURITY_DESCRIPTOR descriptor = nullptr;
  const std::wstring sddl = L"O:" + state.sid_text + L"D:P(A;OICI;FA;;;" +
      state.sid_text + L")(A;OICI;FA;;;SY)";
  if (!ConvertStringSecurityDescriptorToSecurityDescriptorW(sddl.c_str(), SDDL_REVISION_1,
                                                           &descriptor, nullptr))
    return Error(error, L"A private profile security descriptor could not be created.");
  SECURITY_ATTRIBUTES attributes{sizeof(SECURITY_ATTRIBUTES), descriptor, FALSE};
  const BOOL created = CreateDirectoryW(state.root.c_str(), &attributes);
  LocalFree(descriptor);
  if (!created) return Error(error, L"The new private profile directory could not be created exclusively.");
  Handle root_handle(CreateFileW(state.root.c_str(), FILE_LIST_DIRECTORY | FILE_READ_ATTRIBUTES | READ_CONTROL,
      FILE_SHARE_READ | FILE_SHARE_WRITE, nullptr, OPEN_EXISTING,
      FILE_FLAG_BACKUP_SEMANTICS | FILE_FLAG_OPEN_REPARSE_POINT, nullptr));
  if (!root_handle || !DirectoryHandle(root_handle.get()) ||
      !PrivateAcl(root_handle.get(), state.sid.data()) ||
      !GetFileInformationByHandle(root_handle.get(), &state.identity))
    return Error(error, L"The newly created profile failed its identity or private ACL validation.");
  state.pinned.push_back(std::move(root_handle));
  // bundle 的路径身份同样保持到监督器退出，避免路径别名或重命名改变隔离边界。
  for (auto& handle : resource_handles) state.pinned.push_back(std::move(handle));
  if (!prepared->Revalidate(resource_root))
    return Error(error, L"The new profile changed during startup validation. Default data will not be used.");
  *configuration = std::move(prepared);
  return true;
}

bool NativeLaunchConfiguration::has_new_profile() const { return !impl_->root.empty(); }
const std::wstring& NativeLaunchConfiguration::profile_root() const { return impl_->root; }

bool NativeLaunchConfiguration::Revalidate(const std::wstring& resource_root) const {
  if (!has_new_profile()) return true;
  std::wstring sid_text;
  std::vector<BYTE> sid;
  std::wstring resource;
  std::wstring default_path;
  if (!CurrentSid(&sid_text, &sid) || sid_text != impl_->sid_text ||
      !StrictPath(resource_root, &resource) || !DefaultPath(sid_text, &default_path)) return false;
  for (const auto& handle : impl_->pinned) if (!DirectoryHandle(handle.get())) return false;
  std::vector<Handle> root_handles;
  std::vector<Handle> resource_handles;
  std::vector<Handle> default_handles;
  std::wstring actual_root;
  std::wstring actual_resource;
  std::wstring actual_default;
  std::wstring root_comparison;
  std::wstring resource_comparison;
  if (!PinExistingDirectories(impl_->root, &root_handles, &actual_root) ||
      !PinExistingDirectories(resource, &resource_handles, &actual_resource) ||
      !PinExistingDirectories(default_path, &default_handles, &actual_default, true, VOLUME_NAME_GUID) ||
      !FinalPath(root_handles.back().get(), &root_comparison, VOLUME_NAME_GUID) ||
      !FinalPath(resource_handles.back().get(), &resource_comparison, VOLUME_NAME_GUID) ||
      !EqualPath(actual_root, impl_->root) || !EqualPath(actual_resource, impl_->resource) ||
      !EqualPath(root_comparison, impl_->root_comparison) ||
      !EqualPath(resource_comparison, impl_->resource_comparison) ||
      !Disjoint(root_comparison, resource_comparison) || !Disjoint(root_comparison, actual_default) ||
      !PrivateAcl(root_handles.back().get(), sid.data())) return false;
  BY_HANDLE_FILE_INFORMATION identity{};
  return GetFileInformationByHandle(root_handles.back().get(), &identity) &&
      identity.dwVolumeSerialNumber == impl_->identity.dwVolumeSerialNumber &&
      identity.nFileIndexHigh == impl_->identity.nFileIndexHigh &&
      identity.nFileIndexLow == impl_->identity.nFileIndexLow;
}

}  // namespace chasteady
