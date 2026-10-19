#include "media_drop_target.h"

#include <commctrl.h>
#include <ole2.h>
#include <shellapi.h>
#include <shlobj.h>

#include <algorithm>
#include <atomic>
#include <cmath>
#include <cwctype>
#include <memory>
#include <iterator>
#include <utility>
#include <vector>

namespace chasteady {
namespace {

constexpr UINT_PTR kDropSubclassId = 0x43484450;
constexpr size_t kMaximumDropBytes = 65536;
constexpr size_t kMaximumMediaPath = MAX_PATH - 1;

bool OwnedUiWindow(HWND window) {
  DWORD process = 0;
  const DWORD thread = GetWindowThreadProcessId(window, &process);
  return IsWindow(window) && process == GetCurrentProcessId() && thread == GetCurrentThreadId();
}

bool ValidPath(const std::wstring& path) {
  if (path.size() < 4 || path.size() > kMaximumMediaPath || path[1] != L':' || path[2] != L'\\' ||
      !((path[0] >= L'A' && path[0] <= L'Z') || (path[0] >= L'a' && path[0] <= L'z')) ||
      path.back() == L'\\') return false;
  for (size_t index = 3; index < path.size(); ++index) {
    const wchar_t ch = path[index];
    if (ch < 32 || ch == L':' || ch == L'/' || ch == L'"' || ch == L'<' ||
        ch == L'>' || ch == L'|' || ch == L'?' || ch == L'*') return false;
  }
  size_t position = 3;
  while (position < path.size()) {
    const size_t end = path.find(L'\\', position);
    const std::wstring part = path.substr(position, end == std::wstring::npos ? end : end - position);
    if (part.empty() || part == L"." || part == L".." || part.back() == L' ' || part.back() == L'.') return false;
    std::wstring stem = part.substr(0, part.find(L'.'));
    while (!stem.empty() && stem.back() == L' ') stem.pop_back();
    std::transform(stem.begin(), stem.end(), stem.begin(), [](wchar_t ch) {
      return static_cast<wchar_t>(towupper(ch));
    });
    if (stem == L"CON" || stem == L"PRN" || stem == L"AUX" || stem == L"NUL" ||
        stem == L"CONIN$" || stem == L"CONOUT$" ||
        (stem.size() == 4 && (stem.substr(0, 3) == L"COM" || stem.substr(0, 3) == L"LPT") &&
         ((stem[3] >= L'0' && stem[3] <= L'9') || stem[3] == L'¹' ||
          stem[3] == L'²' || stem[3] == L'³'))) return false;
    if (end == std::wstring::npos) break;
    position = end + 1;
  }
  const size_t extension_start = path.find_last_of(L'.');
  if (extension_start == std::wstring::npos) return false;
  std::wstring extension = path.substr(extension_start);
  std::transform(extension.begin(), extension.end(), extension.begin(), [](wchar_t ch) {
    return static_cast<wchar_t>(towlower(ch));
  });
  static const wchar_t* const extensions[] = {
      L".mp4", L".mov", L".m4v", L".mkv", L".avi", L".webm", L".mts", L".m2ts", L".mpg", L".mpeg"};
  return std::any_of(std::begin(extensions), std::end(extensions), [&](const wchar_t* candidate) {
    return extension == candidate;
  });
}

struct FileHandles final {
  std::vector<HANDLE> values;
  ~FileHandles() { for (HANDLE value : values) CloseHandle(value); }
};

bool ValidateEntity(const std::wstring& path, std::string* output, MediaDropTarget::FileIdentity* identity) {
  if (output == nullptr || !ValidPath(path)) return false;
  if (GetDriveTypeW(path.substr(0, 3).c_str()) == DRIVE_REMOTE) return false;
  FileHandles handles;
  std::wstring current = path.substr(0, 3);
  size_t position = 3;
  for (;;) {
    const bool leaf = current.size() == path.size();
    const HANDLE handle = CreateFileW(current.c_str(), leaf ? GENERIC_READ : FILE_READ_ATTRIBUTES,
        FILE_SHARE_READ | FILE_SHARE_WRITE, nullptr, OPEN_EXISTING,
        FILE_FLAG_BACKUP_SEMANTICS | FILE_FLAG_OPEN_REPARSE_POINT, nullptr);
    if (handle == INVALID_HANDLE_VALUE) return false;
    handles.values.push_back(handle);
    BY_HANDLE_FILE_INFORMATION info{};
    if (GetFileType(handle) != FILE_TYPE_DISK || !GetFileInformationByHandle(handle, &info) ||
        (info.dwFileAttributes & (FILE_ATTRIBUTE_REPARSE_POINT | FILE_ATTRIBUTE_DEVICE)) != 0 ||
        (!leaf && (info.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY) == 0)) return false;
    if (leaf) {
      if ((info.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY) != 0 ||
          (info.nFileSizeHigh == 0 && info.nFileSizeLow == 0)) return false;
      BYTE prefix[2]{};
      DWORD bytes = 0;
      if (!ReadFile(handle, prefix, sizeof(prefix), &bytes, nullptr) ||
          (bytes == 2 && prefix[0] == 'M' && prefix[1] == 'Z')) return false;
      wchar_t canonical[32768]{};
      const DWORD length = GetFinalPathNameByHandleW(handle, canonical,
          static_cast<DWORD>(std::size(canonical)), FILE_NAME_NORMALIZED | VOLUME_NAME_DOS);
      if (length <= 4 || length >= std::size(canonical)) return false;
      const std::wstring normalized(canonical, length);
      if (normalized.rfind(L"\\\\?\\", 0) != 0) return false;
      const std::wstring local = normalized.substr(4);
      if (!ValidPath(local)) return false;
      const int count = WideCharToMultiByte(CP_UTF8, WC_ERR_INVALID_CHARS, local.data(),
          static_cast<int>(local.size()), nullptr, 0, nullptr, nullptr);
      if (count <= 0) return false;
      std::string utf8(static_cast<size_t>(count), '\0');
      if (WideCharToMultiByte(CP_UTF8, WC_ERR_INVALID_CHARS, local.data(), static_cast<int>(local.size()),
                             utf8.data(), count, nullptr, nullptr) != count) return false;
      if (identity != nullptr) {
        identity->volume = info.dwVolumeSerialNumber;
        identity->index_high = info.nFileIndexHigh;
        identity->index_low = info.nFileIndexLow;
        identity->size_high = info.nFileSizeHigh;
        identity->size_low = info.nFileSizeLow;
        identity->last_write = info.ftLastWriteTime;
      }
      *output = std::move(utf8);
      return true;
    }
    const size_t end = path.find(L'\\', position);
    current = path.substr(0, end);
    position = end == std::wstring::npos ? path.size() : end + 1;
  }
}

class Medium final {
 public:
  STGMEDIUM value{};
  bool acquired = false;
  ~Medium() { if (acquired) ReleaseStgMedium(&value); }
};

bool Fail(std::string* error, const char* code) {
  if (error != nullptr) *error = code;
  return false;
}

}  // namespace

bool MediaDropTarget::FileIdentity::operator==(const FileIdentity& other) const {
  return volume == other.volume && index_high == other.index_high && index_low == other.index_low &&
      size_high == other.size_high && size_low == other.size_low &&
      last_write.dwHighDateTime == other.last_write.dwHighDateTime &&
      last_write.dwLowDateTime == other.last_write.dwLowDateTime;
}

bool MediaDropTarget::ReadSingleMediaFile(IDataObject* object, std::string* path, FileIdentity* identity) {
  if (path == nullptr) return false;
  path->clear();
  if (identity != nullptr) *identity = {};
  if (object == nullptr) return false;
  FORMATETC format{CF_HDROP, nullptr, DVASPECT_CONTENT, -1, TYMED_HGLOBAL};
  if (object->QueryGetData(&format) != S_OK) return false;
  Medium medium;
  if (FAILED(object->GetData(&format, &medium.value))) return false;
  medium.acquired = true;
  if (medium.value.tymed != TYMED_HGLOBAL || medium.value.hGlobal == nullptr) return false;
  const SIZE_T bytes = GlobalSize(medium.value.hGlobal);
  if (bytes < sizeof(DROPFILES) + 2 * sizeof(wchar_t) || bytes > kMaximumDropBytes) return false;
  const auto* memory = static_cast<const BYTE*>(GlobalLock(medium.value.hGlobal));
  if (memory == nullptr) return false;
  const auto* header = reinterpret_cast<const DROPFILES*>(memory);
  std::wstring selected;
  bool valid = header->fWide && header->pFiles >= sizeof(DROPFILES) &&
      header->pFiles % alignof(wchar_t) == 0 && header->pFiles <= bytes - 2 * sizeof(wchar_t) &&
      (bytes - header->pFiles) % sizeof(wchar_t) == 0;
  if (valid) {
    const auto* list = reinterpret_cast<const wchar_t*>(memory + header->pFiles);
    const size_t count = (bytes - header->pFiles) / sizeof(wchar_t);
    size_t length = 0;
    while (length < count && list[length] != L'\0') ++length;
    valid = length > 0 && length <= kMaximumMediaPath && length + 1 < count &&
        list[length + 1] == L'\0';
    if (valid) selected.assign(list, length);
  }
  GlobalUnlock(medium.value.hGlobal);
  // CF_HDROP 来自 IDataObject，不属于 WM_DROPFILES；唯一释放者是 ReleaseStgMedium。
  return valid && ValidateEntity(selected, path, identity);
}

bool MediaDropTarget::IsValidConfiguration(const Configuration& value) {
  if (value.target_id.empty() || value.target_id.size() > 64 || value.generation <= 0) return false;
  for (const char ch : value.target_id) {
    if (!((ch >= 'a' && ch <= 'z') || (ch >= 'A' && ch <= 'Z') ||
          (ch >= '0' && ch <= '9') || ch == '_' || ch == '-')) return false;
  }
  const double values[] = {value.left, value.top, value.right, value.bottom, value.client_width};
  for (double number : values) if (!std::isfinite(number)) return false;
  return value.client_width > 0.0 && value.client_width <= 65536.0 && value.left >= 0.0 &&
      value.top >= 0.0 && value.right > value.left && value.bottom > value.top &&
      value.right <= value.client_width + 0.001 && value.bottom <= 65536.0;
}

class MediaDropTarget::Impl final : public IDropTarget {
 public:
  Impl(HWND owner, HWND child, Available available, Dropped dropped)
      : owner_(owner), child_(child), available_(std::move(available)), dropped_(std::move(dropped)) {
    if (Owned() && SetWindowSubclass(child_, ChildProc, kDropSubclassId, reinterpret_cast<DWORD_PTR>(this))) {
      subclassed_ = true;
      registered_ = SUCCEEDED(RegisterDragDrop(child_, this));
      if (!registered_) {
        RemoveWindowSubclass(child_, ChildProc, kDropSubclassId);
        subclassed_ = false;
      }
    }
  }

  void Detach() {
    Disable();
    available_ = nullptr;
    dropped_ = nullptr;
    if (registered_) { RevokeDragDrop(child_); registered_ = false; }
    if (subclassed_) {
      // 保持一个惰性引用直到 NCDESTROY，避免极端注销失败留下悬挂回调。
      if (!RemoveWindowSubclass(child_, ChildProc, kDropSubclassId) && IsWindow(child_)) {
        AddRef();
        inert_subclass_reference_ = true;
      }
      subclassed_ = false;
    }
  }

  bool Owned() const {
    return OwnedUiWindow(owner_) && OwnedUiWindow(child_) && GetParent(child_) == owner_ &&
        GetAncestor(child_, GA_ROOT) == owner_ && GetAncestor(owner_, GA_ROOT) == owner_;
  }

  bool AvailableNow() const {
    return registered_ && Owned() && IsWindowVisible(owner_) && IsWindowVisible(child_) &&
        IsWindowEnabled(owner_) && IsWindowEnabled(child_) && !IsIconic(owner_) &&
        available_ && available_();
  }

  bool Fresh() const {
    RECT actual{};
    return enabled_ && AvailableNow() && GetClientRect(child_, &actual) &&
        actual.right == width_ && actual.bottom == height_ && GetDpiForWindow(child_) == dpi_;
  }

  bool Contains(POINTL point) const {
    if (!Fresh()) return false;
    POINT client{point.x, point.y};
    if (!ScreenToClient(child_, &client)) return false;
    const double scale = (dpi_ == 0 ? 96.0 : static_cast<double>(dpi_)) / 96.0;
    const double x = client.x / scale;
    const double y = client.y / scale;
    return x >= configuration_.left && x < configuration_.right &&
        y >= configuration_.top && y < configuration_.bottom;
  }

  bool Configure(bool enabled, const Configuration& configuration, std::string* error) {
    if (error != nullptr) error->clear();
    Disable();
    if (!enabled) return true;
    if (!IsValidConfiguration(configuration) || configuration.generation <= high_water_)
      return Fail(error, "media_drop_invalid_config");
    if (!AvailableNow()) return Fail(error, "media_drop_unavailable");
    RECT actual{};
    if (!GetClientRect(child_, &actual)) return Fail(error, "media_drop_unavailable");
    const UINT dpi = GetDpiForWindow(child_);
    const double scale = (dpi == 0 ? 96.0 : static_cast<double>(dpi)) / 96.0;
    if (actual.right <= 0 || actual.bottom <= 0 ||
        std::abs(actual.right / scale - configuration.client_width) > 1.0 / scale ||
        configuration.bottom > actual.bottom / scale + 0.001)
      return Fail(error, "media_drop_invalid_config");
    configuration_ = configuration;
    width_ = actual.right;
    height_ = actual.bottom;
    dpi_ = dpi;
    high_water_ = configuration.generation;
    enabled_ = true;
    return true;
  }

  void Disable() {
    enabled_ = false;
    configuration_ = {};
    ClearDrag();
  }

  void ClearDrag() { drag_path_.clear(); drag_generation_ = 0; drag_target_.clear(); }

  void Observe(UINT message, WPARAM wparam) {
    if (message == WM_SIZE || message == WM_DPICHANGED || message == WM_DPICHANGED_AFTERPARENT ||
        message == WM_DESTROY || (message == WM_SHOWWINDOW && wparam == FALSE) ||
        (message == WM_ENABLE && wparam == FALSE)) Disable();
  }

  HRESULT STDMETHODCALLTYPE QueryInterface(REFIID iid, void** output) override {
    if (output == nullptr) return E_POINTER;
    *output = nullptr;
    if (iid != IID_IUnknown && iid != IID_IDropTarget) return E_NOINTERFACE;
    *output = static_cast<IDropTarget*>(this);
    AddRef();
    return S_OK;
  }
  ULONG STDMETHODCALLTYPE AddRef() override { return ++references_; }
  ULONG STDMETHODCALLTYPE Release() override {
    const ULONG count = --references_;
    if (count == 0) delete this;
    return count;
  }

  HRESULT STDMETHODCALLTYPE DragEnter(IDataObject* object, DWORD, POINTL point, DWORD* effect) override {
    if (effect == nullptr) return E_POINTER;
    const DWORD allowed = *effect;
    *effect = DROPEFFECT_NONE;
    ClearDrag();
    try {
      if ((allowed & DROPEFFECT_COPY) != 0 && Fresh() && ReadSingleMediaFile(object, &drag_path_, &drag_identity_)) {
        drag_generation_ = configuration_.generation;
        drag_target_ = configuration_.target_id;
        if (Contains(point)) *effect = DROPEFFECT_COPY;
      }
    } catch (...) { ClearDrag(); }
    return S_OK;
  }
  HRESULT STDMETHODCALLTYPE DragOver(DWORD, POINTL point, DWORD* effect) override {
    if (effect == nullptr) return E_POINTER;
    const DWORD allowed = *effect;
    *effect = DROPEFFECT_NONE;
    if ((allowed & DROPEFFECT_COPY) != 0 && !drag_path_.empty() &&
        drag_generation_ == configuration_.generation && drag_target_ == configuration_.target_id &&
        Contains(point)) *effect = DROPEFFECT_COPY;
    return S_OK;
  }
  HRESULT STDMETHODCALLTYPE DragLeave() override { ClearDrag(); return S_OK; }
  HRESULT STDMETHODCALLTYPE Drop(IDataObject* object, DWORD, POINTL point, DWORD* effect) override {
    if (effect == nullptr) return E_POINTER;
    const DWORD allowed = *effect;
    *effect = DROPEFFECT_NONE;
    try {
      std::string path;
      FileIdentity identity;
      if ((allowed & DROPEFFECT_COPY) != 0 && !drag_path_.empty() && Contains(point) &&
          drag_generation_ == configuration_.generation && drag_target_ == configuration_.target_id &&
          ReadSingleMediaFile(object, &path, &identity) && path == drag_path_ &&
          identity == drag_identity_ && Fresh()) {
        const std::string target = drag_target_;
        const int64_t generation = drag_generation_;
        ClearDrag();
        if (dropped_) {
          dropped_(target, generation, path);
          *effect = DROPEFFECT_COPY;
        }
      }
    } catch (...) {}
    ClearDrag();
    return S_OK;
  }

 private:
  ~Impl() = default;
  static LRESULT CALLBACK ChildProc(HWND window, UINT message, WPARAM wparam, LPARAM lparam,
                                   UINT_PTR id, DWORD_PTR data) {
    auto* self = reinterpret_cast<Impl*>(data);
    if (message == WM_NCDESTROY) {
      self->Disable();
      if (self->registered_) { RevokeDragDrop(window); self->registered_ = false; }
      RemoveWindowSubclass(window, ChildProc, id);
      self->subclassed_ = false;
      self->child_ = nullptr;
      const bool release = self->inert_subclass_reference_;
      self->inert_subclass_reference_ = false;
      if (release) self->Release();
      return DefSubclassProc(window, message, wparam, lparam);
    }
    self->Observe(message, wparam);
    return DefSubclassProc(window, message, wparam, lparam);
  }

  std::atomic<ULONG> references_{1};
  HWND owner_;
  HWND child_;
  Available available_;
  Dropped dropped_;
  bool registered_ = false;
  bool subclassed_ = false;
  bool inert_subclass_reference_ = false;
  bool enabled_ = false;
  Configuration configuration_;
  int64_t high_water_ = 0;
  LONG width_ = 0;
  LONG height_ = 0;
  UINT dpi_ = 0;
  std::string drag_path_;
  std::string drag_target_;
  int64_t drag_generation_ = 0;
  FileIdentity drag_identity_;
};

MediaDropTarget::MediaDropTarget(HWND owner, HWND flutter_child, Available available, Dropped dropped)
    : impl_(new Impl(owner, flutter_child, std::move(available), std::move(dropped))) {}
MediaDropTarget::~MediaDropTarget() { if (impl_) { impl_->Detach(); impl_->Release(); } }
bool MediaDropTarget::Configure(bool enabled, const Configuration& configuration, std::string* error) {
  return impl_ && impl_->Configure(enabled, configuration, error);
}
void MediaDropTarget::HandleWindowMessage(UINT message, WPARAM wparam, LPARAM) {
  if (impl_) impl_->Observe(message, wparam);
}
void MediaDropTarget::Disable() { if (impl_) impl_->Disable(); }
#ifdef CHASTEADY_NATIVE_TESTING
IDropTarget* MediaDropTarget::RetainTargetForTesting() {
  if (impl_) impl_->AddRef();
  return impl_;
}
#endif

}  // namespace chasteady
