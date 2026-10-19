// 仅测试 CF_HDROP 数据层与 owned hidden child；不发送输入、不启动 Flutter/Worker。
#include "media_drop_target.h"

#include <ole2.h>
#include <shellapi.h>
#include <shlobj.h>
#include <wincrypt.h>
#include <array>

#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <limits>
#include <memory>
#include <string>
#include <vector>
#include <utility>

namespace {
int checks = 0;
int failures = 0;
int released_media = 0;
void Check(bool value, const char* name) {
  ++checks;
  if (!value) { ++failures; std::fprintf(stderr, "FAIL: %s (Win32 %lu)\n", name, GetLastError()); }
}

class MediumOwner final : public IUnknown {
 public:
  explicit MediumOwner(HGLOBAL memory) : memory_(memory) {}
  HRESULT STDMETHODCALLTYPE QueryInterface(REFIID iid, void** output) override {
    if (output == nullptr) return E_POINTER;
    *output = nullptr;
    if (iid != IID_IUnknown) return E_NOINTERFACE;
    *output = this; AddRef(); return S_OK;
  }
  ULONG STDMETHODCALLTYPE AddRef() override { return ++refs_; }
  ULONG STDMETHODCALLTYPE Release() override {
    const ULONG remaining = --refs_;
    if (remaining == 0) { GlobalFree(memory_); ++released_media; delete this; }
    return remaining;
  }
 private:
  ULONG refs_ = 1;
  HGLOBAL memory_;
};

class DataObject final : public IDataObject {
 public:
  explicit DataObject(std::vector<BYTE> bytes) : bytes_(std::move(bytes)) {}
  HRESULT STDMETHODCALLTYPE QueryInterface(REFIID iid, void** output) override {
    if (output == nullptr) return E_POINTER;
    *output = nullptr;
    if (iid != IID_IUnknown && iid != IID_IDataObject) return E_NOINTERFACE;
    *output = static_cast<IDataObject*>(this); AddRef(); return S_OK;
  }
  ULONG STDMETHODCALLTYPE AddRef() override { return ++refs_; }
  ULONG STDMETHODCALLTYPE Release() override { const ULONG remaining = --refs_; if (!remaining) delete this; return remaining; }
  HRESULT STDMETHODCALLTYPE GetData(FORMATETC* format, STGMEDIUM* medium) override {
    if (medium == nullptr || QueryGetData(format) != S_OK) return DV_E_FORMATETC;
    HGLOBAL memory = GlobalAlloc(GMEM_MOVEABLE | GMEM_ZEROINIT, bytes_.size());
    if (memory == nullptr) return E_OUTOFMEMORY;
    void* destination = GlobalLock(memory);
    if (destination == nullptr) { GlobalFree(memory); return E_OUTOFMEMORY; }
    memcpy(destination, bytes_.data(), bytes_.size());
    GlobalUnlock(memory);
    *medium = {};
    medium->tymed = TYMED_HGLOBAL;
    medium->hGlobal = memory;
    medium->pUnkForRelease = new MediumOwner(memory);
    return S_OK;
  }
  HRESULT STDMETHODCALLTYPE QueryGetData(FORMATETC* format) override {
    return format != nullptr && format->cfFormat == CF_HDROP && format->tymed == TYMED_HGLOBAL &&
        format->dwAspect == DVASPECT_CONTENT && format->lindex == -1 ? S_OK : DV_E_FORMATETC;
  }
  HRESULT STDMETHODCALLTYPE GetDataHere(FORMATETC*, STGMEDIUM*) override { return E_NOTIMPL; }
  HRESULT STDMETHODCALLTYPE GetCanonicalFormatEtc(FORMATETC*, FORMATETC*) override { return E_NOTIMPL; }
  HRESULT STDMETHODCALLTYPE SetData(FORMATETC*, STGMEDIUM*, BOOL) override { return E_NOTIMPL; }
  HRESULT STDMETHODCALLTYPE EnumFormatEtc(DWORD, IEnumFORMATETC**) override { return E_NOTIMPL; }
  HRESULT STDMETHODCALLTYPE DAdvise(FORMATETC*, DWORD, IAdviseSink*, DWORD*) override { return OLE_E_ADVISENOTSUPPORTED; }
  HRESULT STDMETHODCALLTYPE DUnadvise(DWORD) override { return OLE_E_ADVISENOTSUPPORTED; }
  HRESULT STDMETHODCALLTYPE EnumDAdvise(IEnumSTATDATA**) override { return OLE_E_ADVISENOTSUPPORTED; }
 private:
  ULONG refs_ = 1;
  std::vector<BYTE> bytes_;
};

std::vector<BYTE> DropBytes(const std::vector<std::wstring>& paths) {
  std::vector<wchar_t> names;
  for (const auto& path : paths) { names.insert(names.end(), path.begin(), path.end()); names.push_back(L'\0'); }
  names.push_back(L'\0');
  std::vector<BYTE> bytes(sizeof(DROPFILES) + names.size() * sizeof(wchar_t), 0);
  auto* header = reinterpret_cast<DROPFILES*>(bytes.data());
  header->pFiles = sizeof(DROPFILES);
  header->fWide = TRUE;
  memcpy(bytes.data() + sizeof(DROPFILES), names.data(), names.size() * sizeof(wchar_t));
  return bytes;
}

void File(const std::wstring& path, const char* content) {
  HANDLE handle = CreateFileW(path.c_str(), GENERIC_WRITE, 0, nullptr, CREATE_NEW, FILE_ATTRIBUTE_NORMAL, nullptr);
  Check(handle != INVALID_HANDLE_VALUE, "create only new owned synthetic file");
  if (handle == INVALID_HANDLE_VALUE) return;
  DWORD written = 0;
  Check(WriteFile(handle, content, static_cast<DWORD>(strlen(content)), &written, nullptr) &&
        written == strlen(content), "write bounded synthetic parser input");
  CloseHandle(handle);
}

bool Fingerprint(const std::wstring& path, std::array<BYTE, 32>* digest) {
  HANDLE file = CreateFileW(path.c_str(), GENERIC_READ, FILE_SHARE_READ | FILE_SHARE_WRITE,
                            nullptr, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, nullptr);
  if (file == INVALID_HANDLE_VALUE) return false;
  HCRYPTPROV provider = 0;
  HCRYPTHASH hash = 0;
  bool valid = CryptAcquireContextW(&provider, nullptr, nullptr, PROV_RSA_AES, CRYPT_VERIFYCONTEXT) &&
      CryptCreateHash(provider, CALG_SHA_256, 0, 0, &hash);
  BYTE bytes[1024]{};
  DWORD count = 0;
  while (valid) {
    if (!ReadFile(file, bytes, sizeof(bytes), &count, nullptr)) { valid = false; break; }
    if (count == 0) break;
    valid = CryptHashData(hash, bytes, count, 0) != FALSE;
  }
  DWORD length = static_cast<DWORD>(digest->size());
  if (valid) valid = CryptGetHashParam(hash, HP_HASHVAL, digest->data(), &length, 0) && length == digest->size();
  if (hash) CryptDestroyHash(hash);
  if (provider) CryptReleaseContext(provider, 0);
  CloseHandle(file);
  return valid;
}

void Expect(std::vector<BYTE> bytes, bool accepted, const char* name) {
  DataObject object(std::move(bytes));
  std::string path;
  const int before = released_media;
  Check(chasteady::MediaDropTarget::ReadSingleMediaFile(&object, &path) == accepted, name);
  Check(released_media == before + 1, "STGMEDIUM released exactly once including rejection");
  Check(accepted ? !path.empty() : path.empty(), "bounded single-path output or empty failure");
}
}  // namespace

int wmain(int argc, wchar_t** argv) {
  if (argc != 2 || FAILED(OleInitialize(nullptr))) return 2;
  const std::wstring base = argv[1];
  if (!CreateDirectoryW(base.c_str(), nullptr)) { OleUninitialize(); return 2; }
  const std::wstring video = base + L"\\中文 空格.mp4";
  const std::wstring another = base + L"\\another.mov";
  File(video, "synthetic data-layer input only; Worker must still inspect media");
  File(another, "synthetic data-layer input only");
  const std::wstring executable = base + L"\\program.exe";
  File(executable, "MZ synthetic executable header");
  const std::wstring disguised = base + L"\\disguised.mp4";
  File(disguised, "MZ synthetic executable header");
  const std::wstring shortcut = base + L"\\shortcut.lnk";
  File(shortcut, "synthetic shortcut");
  const std::wstring directory = base + L"\\directory.mp4";
  Check(CreateDirectoryW(directory.c_str(), nullptr) != FALSE, "create only own directory media-name fixture");
  Expect(DropBytes({video}), true, "accept one physical Unicode media candidate");
  Expect(DropBytes({video, another}), false, "reject multi-file CF_HDROP");
  Expect(DropBytes({directory}), false, "reject directory even with media suffix");
  Expect(DropBytes({shortcut}), false, "reject shortcut");
  Expect(DropBytes({executable}), false, "reject executable suffix");
  Expect(DropBytes({disguised}), false, "reject executable MZ renamed to media");
  Expect(DropBytes({video + L":stream.mp4"}), false, "reject ADS");
  Expect(DropBytes({L"\\\\.\\NUL.mp4"}), false, "reject device namespace");
  Expect(DropBytes({L"\\\\?\\" + video}), false, "reject extended device path");
  Expect(DropBytes({L"\\\\host\\share\\file.mp4"}), false, "reject UNC");
  Expect(DropBytes({L"relative.mp4"}), false, "reject relative path");
  Expect(DropBytes({base + L"\\..\\file.mp4"}), false, "reject parent component");
  Expect(DropBytes({base + L"\\NUL.mp4"}), false, "reject DOS device component");
  Expect(DropBytes({base + L"\\COM¹.mp4"}), false, "reject superscript DOS device before open");
  Expect(DropBytes({base + L"\\NUL .mp4"}), false, "reject spaced DOS device before open");
  Expect(DropBytes({base + L"\\missing.mp4"}), false, "reject absent media");
  Expect(DropBytes({std::wstring(300, L'a') + L".mp4"}), false, "reject overlength path");
  Expect(DropBytes({}), false, "reject empty list");
  auto malformed = DropBytes({video});
  reinterpret_cast<DROPFILES*>(malformed.data())->pFiles = 0xfffffff0;
  Expect(malformed, false, "reject invalid CF_HDROP offset");
  malformed = DropBytes({video});
  reinterpret_cast<DROPFILES*>(malformed.data())->fWide = FALSE;
  Expect(malformed, false, "reject ANSI/unbounded conversion input");
  malformed = DropBytes({video});
  malformed[malformed.size() - 2] = 'x';
  Expect(malformed, false, "reject missing double terminator");
  malformed = DropBytes({video});
  reinterpret_cast<DROPFILES*>(malformed.data())->pFiles += 1;
  Expect(malformed, false, "reject unaligned CF_HDROP offset");
  const std::wstring hardlink = base + L"\\hardlink.mp4";
  std::array<BYTE, 32> before_hash{};
  std::array<BYTE, 32> after_hash{};
  Check(Fingerprint(video, &before_hash), "hash owned source before read-only hardlink acceptance");
  chasteady::MediaDropTarget::FileIdentity before_identity;
  chasteady::MediaDropTarget::FileIdentity alias_identity;
  chasteady::MediaDropTarget::FileIdentity after_identity;
  std::string selected;
  DataObject original_before(DropBytes({video}));
  Check(chasteady::MediaDropTarget::ReadSingleMediaFile(&original_before, &selected, &before_identity),
        "record original file ID size and modification time");
  Check(CreateHardLinkW(hardlink.c_str(), video.c_str(), nullptr) != FALSE, "create owned read-only hardlink source");
  Expect(DropBytes({hardlink}), true, "accept read-only hardlink media source");
  Expect(DropBytes({video}), true, "accept original media with multiple hardlinks");
  DataObject alias(DropBytes({hardlink}));
  Check(chasteady::MediaDropTarget::ReadSingleMediaFile(&alias, &selected, &alias_identity) &&
        alias_identity == before_identity, "hardlink has same physical file identity");
  DataObject original_after(DropBytes({video}));
  Check(chasteady::MediaDropTarget::ReadSingleMediaFile(&original_after, &selected, &after_identity) &&
        after_identity == before_identity, "read-only source ID size mtime unchanged");
  Check(Fingerprint(video, &after_hash) && before_hash == after_hash, "source SHA256 unchanged after drop validation");
  std::printf("READONLY_SOURCE volume=%lu fileID=%08lx%08lx size=%08lx%08lx mtime=%08lx%08lx sha256=",
      before_identity.volume, before_identity.index_high, before_identity.index_low,
      before_identity.size_high, before_identity.size_low,
      before_identity.last_write.dwHighDateTime, before_identity.last_write.dwLowDateTime);
  for (BYTE byte : before_hash) std::printf("%02x", byte);
  std::printf("\n");
  Check(DeleteFileW(hardlink.c_str()) != FALSE, "remove only owned hardlink");
  Expect(DropBytes({video}), true, "physical file accepted after link removal");
  std::string path;
  Check(!chasteady::MediaDropTarget::ReadSingleMediaFile(nullptr, &path), "reject missing IDataObject");

  chasteady::MediaDropTarget::Configuration geometry;
  geometry.target_id = "source";
  geometry.generation = 1;
  geometry.left = 10; geometry.top = 10; geometry.right = 100; geometry.bottom = 100; geometry.client_width = 640;
  Check(chasteady::MediaDropTarget::IsValidConfiguration(geometry), "finite source geometry schema");
  auto bad = geometry; bad.generation = 0;
  Check(!chasteady::MediaDropTarget::IsValidConfiguration(bad), "reject zero generation");
  bad = geometry; bad.left = std::numeric_limits<double>::quiet_NaN();
  Check(!chasteady::MediaDropTarget::IsValidConfiguration(bad), "reject nonfinite geometry");
  bad = geometry; bad.target_id = "source/command";
  Check(!chasteady::MediaDropTarget::IsValidConfiguration(bad), "reject arbitrary target syntax");
  bad = geometry; bad.right = 1000;
  Check(!chasteady::MediaDropTarget::IsValidConfiguration(bad), "reject out-of-width geometry");
  HWND owner = CreateWindowExW(0, L"STATIC", L"ChaSteady hidden OLE fixture", WS_OVERLAPPEDWINDOW,
      0, 0, 640, 480, nullptr, nullptr, GetModuleHandleW(nullptr), nullptr);
  Check(owner != nullptr, "create only owned hidden top-level fixture");
  HWND child = CreateWindowExW(0, L"STATIC", L"", WS_CHILD | WS_VISIBLE | SS_NOTIFY,
      0, 0, 640, 480, owner, nullptr, GetModuleHandleW(nullptr), nullptr);
  Check(child != nullptr && !IsWindowVisible(owner), "owned child remains hidden through parent");
  int callbacks = 0;
  auto drop = std::make_unique<chasteady::MediaDropTarget>(owner, child, [] { return true; },
      [&](const std::string&, int64_t, const std::string&) { ++callbacks; });
  std::string error;
  Check(!drop->Configure(true, geometry, &error) && error == "media_drop_unavailable", "hidden target cannot enable");
  Check(drop->Configure(false, {}, &error), "disable always succeeds");
  IDropTarget* target = drop->RetainTargetForTesting();
  Check(target != nullptr, "retain only owned IDropTarget for injection-layer test");
  const HRESULT duplicate_registration = RegisterDragDrop(child, target);
  Check(duplicate_registration == DRAGDROP_E_ALREADYREGISTERED,
        "documented OLE registration already owns the hidden child");
  if (duplicate_registration == S_OK) RevokeDragDrop(child);
  DataObject object(DropBytes({video}));
  DWORD effect = DROPEFFECT_COPY | DROPEFFECT_MOVE;
  Check(target->DragEnter(&object, MK_LBUTTON, {20, 20}, &effect) == S_OK && effect == DROPEFFECT_NONE,
        "hidden OLE DragEnter refuses COPY and MOVE");
  effect = DROPEFFECT_COPY;
  Check(target->Drop(&object, 0, {20, 20}, &effect) == S_OK && effect == DROPEFFECT_NONE && callbacks == 0,
        "hidden OLE Drop cannot emit callback");
  drop.reset();
  const HRESULT registration_after_teardown = RegisterDragDrop(child, target);
  Check(registration_after_teardown == S_OK, "teardown revoked the original owned child registration");
  if (registration_after_teardown == S_OK)
    Check(RevokeDragDrop(child) == S_OK, "balance the fixture-only OLE re-registration");
  effect = DROPEFFECT_COPY;
  Check(target->DragOver(0, {20, 20}, &effect) == S_OK && effect == DROPEFFECT_NONE,
        "retained receiver is inert after RevokeDragDrop/teardown");
  target->Release();
  // 仅 fixture 析构操作，生产窗口命令不调用 DestroyWindow。
  Check(DestroyWindow(owner) != FALSE, "destroy only owned hidden fixture at teardown");
  OleUninitialize();
  std::printf("%s: OLE data/hidden injection fixture %d checks, %d failures; no real input or Worker.\n",
              failures == 0 ? "PASS" : "FAIL", checks, failures);
  return failures == 0 ? EXIT_SUCCESS : EXIT_FAILURE;
}
