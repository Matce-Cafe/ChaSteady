#define NOMINMAX
#include "native_media.h"

#include <d3d11.h>
#include <dxgi.h>
#include <mfapi.h>
#include <mferror.h>
#include <mfmediaengine.h>
#include <objidl.h>
#include <oleauto.h>
#include <wrl.h>
#include <wrl/implements.h>

#include <algorithm>
#include <atomic>
#include <chrono>
#include <cmath>
#include <condition_variable>
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <deque>
#include <future>
#include <limits>
#include <memory>
#include <mutex>
#include <new>
#include <optional>
#include <string>
#include <thread>
#include <unordered_map>
#include <utility>
#include <vector>

namespace chasteady {
namespace {

using Microsoft::WRL::ComPtr;
using Microsoft::WRL::Make;
using Microsoft::WRL::RuntimeClass;
using Microsoft::WRL::RuntimeClassFlags;
using Microsoft::WRL::ClassicCom;

constexpr int kMaximumDimension = 8192;
constexpr uint64_t kMaximumFrameBytes = 128ull * 1024ull * 1024ull;
// Poll slightly faster than 50 fps to avoid starving ~50 Hz sources; the
// Media Engine PTS remains the frame cadence, so this does not synthesize frames.
constexpr auto kFrameInterval = std::chrono::milliseconds(16);
constexpr auto kStateInterval = std::chrono::milliseconds(250);

struct OperationResult {
  bool ok = false;
  std::string error_code;
};

NativeMediaCreateResult CreateFailure(std::string error_code) {
  NativeMediaCreateResult result;
  result.error_code = std::move(error_code);
  return result;
}

bool IsUsableHandle(HANDLE handle) {
  return handle != nullptr && handle != INVALID_HANDLE_VALUE;
}

class ScopedHandle final {
 public:
  explicit ScopedHandle(HANDLE handle = INVALID_HANDLE_VALUE) : handle_(handle) {}
  ~ScopedHandle() {
    if (IsUsableHandle(handle_)) {
      CloseHandle(handle_);
    }
  }

  ScopedHandle(const ScopedHandle&) = delete;
  ScopedHandle& operator=(const ScopedHandle&) = delete;

  HANDLE get() const { return handle_; }
  HANDLE release() {
    HANDLE result = handle_;
    handle_ = INVALID_HANDLE_VALUE;
    return result;
  }

 private:
  HANDLE handle_;
};

bool ValidateReadHandle(HANDLE handle, uint64_t* file_size) {
  if (!IsUsableHandle(handle) || file_size == nullptr ||
      GetFileType(handle) != FILE_TYPE_DISK) {
    return false;
  }

  FILE_ATTRIBUTE_TAG_INFO tag_info{};
  if (!GetFileInformationByHandleEx(handle, FileAttributeTagInfo, &tag_info,
                                    sizeof(tag_info)) ||
      (tag_info.FileAttributes &
       (FILE_ATTRIBUTE_DIRECTORY | FILE_ATTRIBUTE_REPARSE_POINT)) != 0) {
    return false;
  }

  FILE_STANDARD_INFO standard_info{};
  if (!GetFileInformationByHandleEx(handle, FileStandardInfo, &standard_info,
                                    sizeof(standard_info)) ||
      standard_info.Directory || standard_info.EndOfFile.QuadPart <= 0) {
    return false;
  }

  *file_size = static_cast<uint64_t>(standard_info.EndOfFile.QuadPart);
  return true;
}

// Owns only the already-validated worker-lease handle. Every operation is
// positioned explicitly while holding one lock, so independent IStream clones
// cannot interfere through the shared synchronous file pointer.
class ReadOnlyHandleBacking final {
 public:
  explicit ReadOnlyHandleBacking(HANDLE owned_handle, uint64_t file_size)
      : handle_(owned_handle), file_size_(file_size) {}
  ~ReadOnlyHandleBacking() {
    if (IsUsableHandle(handle_)) {
      CloseHandle(handle_);
    }
  }

  ReadOnlyHandleBacking(const ReadOnlyHandleBacking&) = delete;
  ReadOnlyHandleBacking& operator=(const ReadOnlyHandleBacking&) = delete;

  uint64_t file_size() const { return file_size_; }

  HRESULT ReadAt(uint64_t* position,
                 void* buffer,
                 ULONG requested,
                 ULONG* bytes_read) {
    if (position == nullptr || (buffer == nullptr && requested != 0)) {
      return E_POINTER;
    }
    if (bytes_read != nullptr) {
      *bytes_read = 0;
    }
    if (requested == 0) {
      return S_OK;
    }
    if (*position > static_cast<uint64_t>(std::numeric_limits<LONGLONG>::max())) {
      return STG_E_INVALIDFUNCTION;
    }

    std::lock_guard<std::mutex> lock(io_mutex_);
    LARGE_INTEGER offset{};
    offset.QuadPart = static_cast<LONGLONG>(*position);
    if (!SetFilePointerEx(handle_, offset, nullptr, FILE_BEGIN)) {
      return HRESULT_FROM_WIN32(GetLastError());
    }

    DWORD count = 0;
    if (!ReadFile(handle_, buffer, requested, &count, nullptr)) {
      return HRESULT_FROM_WIN32(GetLastError());
    }
    *position += count;
    if (bytes_read != nullptr) {
      *bytes_read = count;
    }
    return S_OK;
  }

 private:
  HANDLE handle_ = INVALID_HANDLE_VALUE;
  const uint64_t file_size_;
  std::mutex io_mutex_;
};

// Read-only IStream adapter required by MFCreateMFByteStreamOnStream. There is
// deliberately no path-based or writable source implementation in this file.
class HandleReadStream final
    : public RuntimeClass<RuntimeClassFlags<ClassicCom>, IStream> {
 public:
  HandleReadStream(std::shared_ptr<ReadOnlyHandleBacking> backing,
                   uint64_t position = 0)
      : backing_(std::move(backing)), position_(position) {}

  HRESULT STDMETHODCALLTYPE Read(void* buffer,
                                 ULONG requested,
                                 ULONG* bytes_read) override {
    std::lock_guard<std::mutex> lock(position_mutex_);
    ULONG actual = 0;
    const HRESULT hr = backing_->ReadAt(&position_, buffer, requested, &actual);
    if (bytes_read != nullptr) {
      *bytes_read = actual;
    }
    if (FAILED(hr)) {
      return hr;
    }
    return actual < requested ? S_FALSE : S_OK;
  }

  HRESULT STDMETHODCALLTYPE Write(const void*, ULONG, ULONG* bytes_written) override {
    if (bytes_written != nullptr) {
      *bytes_written = 0;
    }
    return STG_E_ACCESSDENIED;
  }

  HRESULT STDMETHODCALLTYPE Seek(LARGE_INTEGER move,
                                 DWORD origin,
                                 ULARGE_INTEGER* new_position) override {
    std::lock_guard<std::mutex> lock(position_mutex_);
    int64_t base = 0;
    switch (origin) {
      case STREAM_SEEK_SET:
        base = 0;
        break;
      case STREAM_SEEK_CUR:
        if (position_ > static_cast<uint64_t>(
                            std::numeric_limits<int64_t>::max())) {
          return STG_E_INVALIDFUNCTION;
        }
        base = static_cast<int64_t>(position_);
        break;
      case STREAM_SEEK_END:
        if (backing_->file_size() > static_cast<uint64_t>(
                                        std::numeric_limits<int64_t>::max())) {
          return STG_E_INVALIDFUNCTION;
        }
        base = static_cast<int64_t>(backing_->file_size());
        break;
      default:
        return STG_E_INVALIDFUNCTION;
    }

    const int64_t delta = move.QuadPart;
    if ((delta > 0 && base > std::numeric_limits<int64_t>::max() - delta) ||
        (delta < 0 && base < std::numeric_limits<int64_t>::min() - delta)) {
      return STG_E_INVALIDFUNCTION;
    }
    const int64_t next = base + delta;
    if (next < 0) {
      return STG_E_INVALIDFUNCTION;
    }
    position_ = static_cast<uint64_t>(next);
    if (new_position != nullptr) {
      new_position->QuadPart = position_;
    }
    return S_OK;
  }

  HRESULT STDMETHODCALLTYPE SetSize(ULARGE_INTEGER) override {
    return STG_E_ACCESSDENIED;
  }

  HRESULT STDMETHODCALLTYPE CopyTo(IStream*,
                                   ULARGE_INTEGER,
                                   ULARGE_INTEGER*,
                                   ULARGE_INTEGER*) override {
    return E_NOTIMPL;
  }

  HRESULT STDMETHODCALLTYPE Commit(DWORD) override { return STG_E_ACCESSDENIED; }
  HRESULT STDMETHODCALLTYPE Revert() override { return STG_E_ACCESSDENIED; }

  HRESULT STDMETHODCALLTYPE LockRegion(ULARGE_INTEGER,
                                       ULARGE_INTEGER,
                                       DWORD) override {
    return STG_E_ACCESSDENIED;
  }

  HRESULT STDMETHODCALLTYPE UnlockRegion(ULARGE_INTEGER,
                                         ULARGE_INTEGER,
                                         DWORD) override {
    return STG_E_ACCESSDENIED;
  }

  HRESULT STDMETHODCALLTYPE Stat(STATSTG* stat, DWORD flags) override {
    if (stat == nullptr) {
      return E_POINTER;
    }
    std::memset(stat, 0, sizeof(*stat));
    stat->type = STGTY_STREAM;
    stat->cbSize.QuadPart = backing_->file_size();
    stat->grfMode = STGM_READ;
    if ((flags & STATFLAG_NONAME) == 0) {
      // Do not reveal the worker's backing path.
      stat->pwcsName = nullptr;
    }
    return S_OK;
  }

  HRESULT STDMETHODCALLTYPE Clone(IStream** cloned_stream) override {
    if (cloned_stream == nullptr) {
      return E_POINTER;
    }
    *cloned_stream = nullptr;
    std::lock_guard<std::mutex> lock(position_mutex_);
    try {
      ComPtr<HandleReadStream> clone = Make<HandleReadStream>(backing_, position_);
      return clone.CopyTo(cloned_stream);
    } catch (...) {
      return E_OUTOFMEMORY;
    }
  }

 private:
  std::shared_ptr<ReadOnlyHandleBacking> backing_;
  std::mutex position_mutex_;
  uint64_t position_ = 0;
};

struct VideoFrame final {
  size_t width = 0;
  size_t height = 0;
  std::vector<uint8_t> bgra;
};

struct PixelBufferLease final {
  explicit PixelBufferLease(std::shared_ptr<const VideoFrame> initial_frame)
      : frame(std::move(initial_frame)) {
    pixel_buffer.buffer = this->frame->bgra.data();
    pixel_buffer.width = this->frame->width;
    pixel_buffer.height = this->frame->height;
    pixel_buffer.release_callback = [](void* context) {
      delete static_cast<PixelBufferLease*>(context);
    };
    pixel_buffer.release_context = this;
  }

  std::shared_ptr<const VideoFrame> frame;
  FlutterDesktopPixelBuffer pixel_buffer{};
};

bool IsDeviceLost(HRESULT hr) {
  return hr == DXGI_ERROR_DEVICE_REMOVED || hr == DXGI_ERROR_DEVICE_RESET ||
         hr == DXGI_ERROR_DEVICE_HUNG || hr == DXGI_ERROR_DRIVER_INTERNAL_ERROR;
}

std::string ErrorCodeForHRESULT(HRESULT hr) {
  if (IsDeviceLost(hr)) {
    return "device_lost";
  }
  if (hr == REGDB_E_CLASSNOTREG || hr == CLASS_E_CLASSNOTAVAILABLE ||
      hr == MF_E_PLATFORM_NOT_INITIALIZED || hr == E_NOINTERFACE) {
    return "media_engine_unavailable";
  }
  if (hr == MF_E_TOPO_CODEC_NOT_FOUND || hr == MF_E_INVALIDMEDIATYPE ||
      hr == MF_E_UNSUPPORTED_BYTESTREAM_TYPE) {
    return "codec_unavailable";
  }
  if (hr == E_OUTOFMEMORY) {
    return "out_of_memory";
  }
  return "media_engine_error";
}

bool IsSupportedNotification(DWORD event_type) {
  switch (event_type) {
    case MF_MEDIA_ENGINE_EVENT_CANPLAY:
    case MF_MEDIA_ENGINE_EVENT_PLAYING:
    case MF_MEDIA_ENGINE_EVENT_PAUSE:
    case MF_MEDIA_ENGINE_EVENT_ENDED:
    case MF_MEDIA_ENGINE_EVENT_ERROR:
    case MF_MEDIA_ENGINE_EVENT_DURATIONCHANGE:
    case MF_MEDIA_ENGINE_EVENT_VOLUMECHANGE:
      return true;
    default:
      return false;
  }
}

}  // namespace

class NativeMediaManager::Core final
    : public std::enable_shared_from_this<NativeMediaManager::Core> {
 public:
  Core(flutter::TextureRegistrar* texture_registrar, EventCallback event_callback)
      : texture_registrar_(texture_registrar),
        event_callback_(std::move(event_callback)) {}

  ~Core() {
    Stop();
  }

  bool Start() {
    std::promise<void> started;
    std::future<void> ready = started.get_future();
    try {
      const std::shared_ptr<Core> keep_alive = shared_from_this();
      worker_ = std::thread([keep_alive, started = std::move(started)]() mutable {
        keep_alive->Run(std::move(started));
      });
      ready.get();
      return true;
    } catch (...) {
      return false;
    }
  }

  NativeMediaCreateResult Create(HANDLE owned_handle, int width, int height) {
    std::shared_ptr<ScopedHandle> owner;
    try {
      owner = std::make_shared<ScopedHandle>(owned_handle);
    } catch (...) {
      if (IsUsableHandle(owned_handle)) {
        CloseHandle(owned_handle);
      }
      return CreateFailure("out_of_memory");
    }

    auto result = Invoke<NativeMediaCreateResult>([this, owner, width, height]() {
      ScopedHandle handle(owner->release());
      return CreateOnWorker(handle, width, height);
    });
    if (!result.has_value()) {
      // If the task was not accepted, owner still closes the transferred handle.
      // If it ran, the worker's local ScopedHandle or stream backing owns it.
      return CreateFailure("manager_stopped");
    }
    return std::move(*result);
  }

  OperationResult Play(const std::string& player_id) {
    return InvokeOperation([this, player_id] { return PlayOnWorker(player_id); });
  }

  OperationResult Pause(const std::string& player_id) {
    return InvokeOperation([this, player_id] { return PauseOnWorker(player_id); });
  }

  OperationResult Seek(const std::string& player_id, double seconds) {
    return InvokeOperation(
        [this, player_id, seconds] { return SeekOnWorker(player_id, seconds); });
  }

  OperationResult SetVolume(const std::string& player_id, double volume) {
    return InvokeOperation([this, player_id, volume] {
      return SetVolumeOnWorker(player_id, volume);
    });
  }

  OperationResult SetMuted(const std::string& player_id, bool muted) {
    return InvokeOperation([this, player_id, muted] {
      return SetMutedOnWorker(player_id, muted);
    });
  }

  std::optional<NativeMediaEvent> State(const std::string& player_id) {
    auto result = Invoke<std::optional<NativeMediaEvent>>([this, player_id] {
      const auto player = FindPlayer(player_id);
      if (!player) {
        return std::optional<NativeMediaEvent>();
      }
      RefreshState(*player);
      return std::optional<NativeMediaEvent>(player->state);
    });
    if (!result.has_value()) {
      return std::nullopt;
    }
    return std::move(*result);
  }

  OperationResult Dispose(const std::string& player_id) {
    return InvokeOperation([this, player_id] {
      const auto found = players_.find(player_id);
      if (found == players_.end()) {
        // Disposal is intentionally idempotent for duplicate bridge cleanup.
        return OperationResult{true, {}};
      }
      DisposePlayer(found->second);
      players_.erase(found);
      return OperationResult{true, {}};
    });
  }

  void DisposeAll() {
    auto result = Invoke<bool>([this] {
      DisposeAllOnWorker();
      return true;
    });
    (void)result;
  }

  void Stop() {
    if (!worker_.joinable()) {
      return;
    }
    if (std::this_thread::get_id() == worker_.get_id()) {
      {
        std::lock_guard<std::mutex> lock(queue_mutex_);
        stopping_ = true;
      }
      queue_condition_.notify_all();
      // Start() keeps Core alive in the detached thread closure until Run exits.
      worker_.detach();
      return;
    }

    DisposeAll();
    {
      std::lock_guard<std::mutex> lock(queue_mutex_);
      stopping_ = true;
    }
    queue_condition_.notify_all();
    worker_.join();
  }

 private:
  struct Player final {
    Player(std::string player_id, int video_width, int video_height)
        : id(std::move(player_id)),
          width(video_width),
          height(video_height),
          texture(flutter::PixelBufferTexture(
              [](size_t, size_t) -> const FlutterDesktopPixelBuffer* {
                return nullptr;
              })) {
      state.player_id = id;
      state.muted = true;
      state.volume = 1.0;
    }

    void PublishFrame(std::shared_ptr<VideoFrame> frame) {
      std::lock_guard<std::mutex> lock(frame_mutex);
      if (accepting_frames.load(std::memory_order_relaxed)) {
        latest_frame = std::move(frame);
      }
    }

    void ShutdownEngine() {
      // Called only on the serialized media worker so Media Foundation and
      // D3D11 interfaces are released on the same MTA thread that created them.
      if (engine) {
        engine->Shutdown();
      }
      engine_ex.Reset();
      engine.Reset();
      byte_stream.Reset();
      source_stream.Reset();
      notify.Reset();
      output_surface.Reset();
      output_texture.Reset();
      staging_texture.Reset();
      terminal_error = true;
    }

    const std::string id;
    const int width;
    const int height;
    flutter::TextureVariant texture;
    int64_t texture_id = -1;
    NativeMediaEvent state;
    bool terminal_error = false;
    std::chrono::steady_clock::time_point last_state_event{};
    std::atomic<bool> accepting_frames{true};
    std::mutex frame_mutex;
    std::shared_ptr<const VideoFrame> latest_frame;
    ComPtr<IMFMediaEngine> engine;
    ComPtr<IMFMediaEngineEx> engine_ex;
    ComPtr<IMFMediaEngineNotify> notify;
    ComPtr<IStream> source_stream;
    ComPtr<IMFByteStream> byte_stream;
    ComPtr<ID3D11Texture2D> output_texture;
    ComPtr<IDXGISurface> output_surface;
    ComPtr<ID3D11Texture2D> staging_texture;
  };

  class EngineNotify final
      : public RuntimeClass<RuntimeClassFlags<ClassicCom>, IMFMediaEngineNotify> {
   public:
    using NotificationCallback =
        std::function<HRESULT(DWORD, DWORD_PTR, DWORD)>;

    explicit EngineNotify(NotificationCallback callback)
        : callback_(std::move(callback)) {}

    HRESULT STDMETHODCALLTYPE EventNotify(DWORD event_type,
                                          DWORD_PTR param1,
                                          DWORD param2) override {
      if (!callback_ || !IsSupportedNotification(event_type)) {
        return S_OK;
      }
      try {
        return callback_(event_type, param1, param2);
      } catch (...) {
        return E_FAIL;
      }
    }

   private:
    NotificationCallback callback_;
  };

  template <typename Result, typename Function>
  std::optional<Result> Invoke(Function&& function) {
    if (std::this_thread::get_id() == worker_id_) {
      try {
        return function();
      } catch (...) {
        return std::nullopt;
      }
    }

    std::shared_ptr<std::packaged_task<Result()>> task;
    std::future<Result> result;
    try {
      task = std::make_shared<std::packaged_task<Result()>>(
          std::forward<Function>(function));
      result = task->get_future();
      {
        std::lock_guard<std::mutex> lock(queue_mutex_);
        if (stopping_ || !worker_.joinable()) {
          return std::nullopt;
        }
        queue_.emplace_back([task] { (*task)(); });
      }
      queue_condition_.notify_one();
      return result.get();
    } catch (...) {
      return std::nullopt;
    }
  }

  OperationResult InvokeOperation(std::function<OperationResult()> operation) {
    auto result = Invoke<OperationResult>(std::move(operation));
    if (!result.has_value()) {
      return {false, "manager_stopped"};
    }
    return std::move(*result);
  }

  void Run(std::promise<void> started) {
    worker_id_ = std::this_thread::get_id();
    const HRESULT co_result = CoInitializeEx(nullptr, COINIT_MULTITHREADED);
    const bool uninitialize_com = SUCCEEDED(co_result);
    if (FAILED(co_result)) {
      startup_error_code_ = "com_initialization_failed";
    } else {
      const HRESULT mf_result = MFStartup(MF_VERSION, MFSTARTUP_FULL);
      mf_started_ = SUCCEEDED(mf_result);
      if (!mf_started_) {
        startup_error_code_ = "media_foundation_unavailable";
      }
    }
    started.set_value();

    auto next_frame = std::chrono::steady_clock::now();
    while (true) {
      std::function<void()> command;
      {
        std::unique_lock<std::mutex> lock(queue_mutex_);
        queue_condition_.wait_until(lock, next_frame, [this] {
          return stopping_ || !queue_.empty();
        });
        if (!queue_.empty()) {
          command = std::move(queue_.front());
          queue_.pop_front();
        } else if (stopping_) {
          break;
        }
      }

      if (command) {
        try {
          command();
        } catch (...) {
          // Each packaged task transports exceptions to its waiting caller.
        }
      }

      const auto now = std::chrono::steady_clock::now();
      if (now >= next_frame) {
        try {
          Tick(now);
        } catch (...) {
          FailAllForInternalError();
        }
        next_frame = now + kFrameInterval;
      }
    }

    DisposeAllOnWorker();
    device_manager_.Reset();
    device_context_.Reset();
    device_.Reset();
    if (mf_started_) {
      MFShutdown();
      mf_started_ = false;
    }
    if (uninitialize_com) {
      CoUninitialize();
    }
  }

  void PostMediaNotice(std::weak_ptr<Player> weak_player,
                       DWORD event_type,
                       DWORD_PTR param1,
                       DWORD param2) {
    try {
      std::lock_guard<std::mutex> lock(queue_mutex_);
      if (stopping_) {
        return;
      }
      queue_.emplace_back([this, weak_player = std::move(weak_player),
                           event_type, param1, param2] {
        const std::shared_ptr<Player> player = weak_player.lock();
        if (!player) {
          return;
        }
        const auto current = players_.find(player->id);
        if (current == players_.end() || current->second != player) {
          return;
        }
        ProcessMediaNotice(*player, event_type, param1, param2);
      });
      queue_condition_.notify_one();
    } catch (...) {
      // Losing a notification is preferable to unwinding through COM.
    }
  }

  bool EnsureDevice(std::string* error_code) {
    if (device_ && device_context_ && device_manager_) {
      return true;
    }
    if (!mf_started_) {
      if (error_code != nullptr) {
        *error_code = startup_error_code_.empty()
                          ? "media_foundation_unavailable"
                          : startup_error_code_;
      }
      return false;
    }

    D3D_FEATURE_LEVEL feature_level{};
    HRESULT hr = D3D11CreateDevice(
        nullptr, D3D_DRIVER_TYPE_HARDWARE, nullptr,
        D3D11_CREATE_DEVICE_BGRA_SUPPORT | D3D11_CREATE_DEVICE_VIDEO_SUPPORT,
        nullptr, 0, D3D11_SDK_VERSION, &device_, &feature_level,
        &device_context_);
    (void)feature_level;
    if (FAILED(hr)) {
      if (error_code != nullptr) {
        *error_code = IsDeviceLost(hr) ? "device_lost" : "d3d_device_unavailable";
      }
      return false;
    }

    UINT reset_token = 0;
    hr = MFCreateDXGIDeviceManager(&reset_token, &device_manager_);
    if (SUCCEEDED(hr)) {
      hr = device_manager_->ResetDevice(device_.Get(), reset_token);
    }
    if (FAILED(hr)) {
      device_manager_.Reset();
      device_context_.Reset();
      device_.Reset();
      if (error_code != nullptr) {
        *error_code = ErrorCodeForHRESULT(hr);
      }
      return false;
    }
    return true;
  }

  NativeMediaCreateResult CreateOnWorker(ScopedHandle& handle,
                                         int width,
                                         int height) {
    if (texture_registrar_ == nullptr) {
      return CreateFailure("texture_registrar_unavailable");
    }
    if (width <= 0 || height <= 0 || width > kMaximumDimension ||
        height > kMaximumDimension ||
        static_cast<uint64_t>(width) * static_cast<uint64_t>(height) * 4ull >
            kMaximumFrameBytes) {
      return CreateFailure("invalid_dimensions");
    }

    uint64_t file_size = 0;
    if (!ValidateReadHandle(handle.get(), &file_size)) {
      return CreateFailure("invalid_media_handle");
    }

    std::string device_error;
    if (!EnsureDevice(&device_error)) {
      return CreateFailure(std::move(device_error));
    }

    std::shared_ptr<ReadOnlyHandleBacking> backing;
    try {
      backing = std::make_shared<ReadOnlyHandleBacking>(handle.get(), file_size);
    } catch (...) {
      return CreateFailure("out_of_memory");
    }
    handle.release();

    const std::string player_id = std::to_string(next_player_id_++);
    std::shared_ptr<Player> player;
    try {
      player = std::make_shared<Player>(player_id, width, height);
    } catch (...) {
      return CreateFailure("out_of_memory");
    }

    // The weak reference avoids a Player -> TextureVariant -> callback -> Player
    // ownership cycle. Flutter PixelBufferTexture gives each returned buffer a
    // release callback, so frames remain immutable while Flutter copies them.
    player->texture = flutter::PixelBufferTexture(
        [weak_player = std::weak_ptr<Player>(player)](size_t, size_t)
            -> const FlutterDesktopPixelBuffer* {
          const std::shared_ptr<Player> current = weak_player.lock();
          if (!current ||
              !current->accepting_frames.load(std::memory_order_acquire)) {
            return nullptr;
          }
          std::shared_ptr<const VideoFrame> frame;
          {
            std::lock_guard<std::mutex> lock(current->frame_mutex);
            frame = current->latest_frame;
          }
          if (!frame) {
            return nullptr;
          }
          auto* lease = new (std::nothrow) PixelBufferLease(std::move(frame));
          return lease == nullptr ? nullptr : &lease->pixel_buffer;
        });

    const HRESULT hr = CreateMediaEngineForPlayer(player, backing);
    if (FAILED(hr)) {
      if (IsDeviceLost(hr)) {
        FailAllForDeviceLoss();
      }
      player->ShutdownEngine();
      return CreateFailure(ErrorCodeForHRESULT(hr));
    }

    player->texture_id = texture_registrar_->RegisterTexture(&player->texture);
    if (player->texture_id < 0) {
      player->ShutdownEngine();
      return CreateFailure("texture_registration_failed");
    }

    try {
      const auto inserted = players_.emplace(player_id, player);
      if (!inserted.second) {
        DisposePlayer(player);
        return CreateFailure("player_id_collision");
      }
    } catch (...) {
      DisposePlayer(player);
      return CreateFailure("out_of_memory");
    }

    NativeMediaCreateResult result;
    result.player_id = player_id;
    result.texture_id = player->texture_id;
    result.can_play = player->state.can_play;
    return result;
  }

  HRESULT CreateMediaEngineForPlayer(
      const std::shared_ptr<Player>& player,
      const std::shared_ptr<ReadOnlyHandleBacking>& backing) {
    D3D11_TEXTURE2D_DESC output_desc{};
    output_desc.Width = static_cast<UINT>(player->width);
    output_desc.Height = static_cast<UINT>(player->height);
    output_desc.MipLevels = 1;
    output_desc.ArraySize = 1;
    output_desc.Format = DXGI_FORMAT_B8G8R8A8_UNORM;
    output_desc.SampleDesc.Count = 1;
    output_desc.Usage = D3D11_USAGE_DEFAULT;
    output_desc.BindFlags = D3D11_BIND_RENDER_TARGET;

    HRESULT hr = device_->CreateTexture2D(&output_desc, nullptr,
                                          &player->output_texture);
    if (FAILED(hr)) {
      return hr;
    }
    hr = player->output_texture.As(&player->output_surface);
    if (FAILED(hr)) {
      return hr;
    }

    D3D11_TEXTURE2D_DESC staging_desc = output_desc;
    staging_desc.Usage = D3D11_USAGE_STAGING;
    staging_desc.BindFlags = 0;
    staging_desc.CPUAccessFlags = D3D11_CPU_ACCESS_READ;
    hr = device_->CreateTexture2D(&staging_desc, nullptr,
                                  &player->staging_texture);
    if (FAILED(hr)) {
      return hr;
    }

    ComPtr<HandleReadStream> stream_impl;
    try {
      stream_impl = Make<HandleReadStream>(backing);
    } catch (...) {
      return E_OUTOFMEMORY;
    }
    hr = stream_impl.As(&player->source_stream);
    if (FAILED(hr)) {
      return hr;
    }
    hr = MFCreateMFByteStreamOnStream(player->source_stream.Get(),
                                      &player->byte_stream);
    if (FAILED(hr)) {
      return hr;
    }

    const std::weak_ptr<Core> weak_core = weak_from_this();
    const std::weak_ptr<Player> weak_player = player;
    ComPtr<EngineNotify> notify_impl;
    try {
      notify_impl = Make<EngineNotify>(
          [weak_core, weak_player](DWORD event_type, DWORD_PTR param1,
                                   DWORD param2) -> HRESULT {
            const std::shared_ptr<Core> core = weak_core.lock();
            if (!core) {
              return S_OK;
            }
            core->PostMediaNotice(weak_player, event_type, param1, param2);
            return S_OK;
          });
    } catch (...) {
      return E_OUTOFMEMORY;
    }
    hr = notify_impl.As(&player->notify);
    if (FAILED(hr)) {
      return hr;
    }

    ComPtr<IMFAttributes> attributes;
    hr = MFCreateAttributes(&attributes, 3);
    if (FAILED(hr)) {
      return hr;
    }
    hr = attributes->SetUnknown(MF_MEDIA_ENGINE_CALLBACK, player->notify.Get());
    if (SUCCEEDED(hr)) {
      hr = attributes->SetUnknown(MF_MEDIA_ENGINE_DXGI_MANAGER,
                                  device_manager_.Get());
    }
    if (SUCCEEDED(hr)) {
      hr = attributes->SetUINT32(MF_MEDIA_ENGINE_VIDEO_OUTPUT_FORMAT,
                                 DXGI_FORMAT_B8G8R8A8_UNORM);
    }
    if (FAILED(hr)) {
      return hr;
    }

    ComPtr<IMFMediaEngineClassFactory> factory;
    hr = CoCreateInstance(CLSID_MFMediaEngineClassFactory, nullptr,
                          CLSCTX_INPROC_SERVER, IID_PPV_ARGS(&factory));
    if (FAILED(hr)) {
      return hr;
    }
    hr = factory->CreateInstance(0, attributes.Get(), &player->engine);
    if (FAILED(hr)) {
      return hr;
    }
    hr = player->engine.As(&player->engine_ex);
    if (FAILED(hr)) {
      return hr;
    }

    // Never autoplay and never emit preview audio until the user unmutes it.
    hr = player->engine->SetAutoPlay(FALSE);
    if (SUCCEEDED(hr)) {
      hr = player->engine->SetMuted(TRUE);
    }
    if (SUCCEEDED(hr)) {
      hr = player->engine->SetVolume(1.0);
    }
    if (FAILED(hr)) {
      return hr;
    }

    // The URL parameter is an empty BSTR: the engine receives its only source
    // through the worker-owned byte stream, never through a path or URL.
    BSTR empty_url = SysAllocStringLen(L"", 0);
    if (empty_url == nullptr) {
      return E_OUTOFMEMORY;
    }
    hr = player->engine_ex->SetSourceFromByteStream(player->byte_stream.Get(),
                                                     empty_url);
    SysFreeString(empty_url);
    return hr;
  }

  std::shared_ptr<Player> FindPlayer(const std::string& player_id) const {
    const auto found = players_.find(player_id);
    return found == players_.end() ? nullptr : found->second;
  }

  OperationResult PlayOnWorker(const std::string& player_id) {
    const auto player = FindPlayer(player_id);
    if (!player) {
      return {false, "player_not_found"};
    }
    if (player->terminal_error || !player->engine) {
      return {false, player->state.error_code.empty() ? "player_unavailable"
                                                      : player->state.error_code};
    }
    const HRESULT hr = player->engine->Play();
    if (FAILED(hr)) {
      return {false, ErrorCodeForHRESULT(hr)};
    }
    RefreshState(*player);
    player->state.ended = false;
    player->state.playing = true;
    Emit(*player);
    return {true, {}};
  }

  OperationResult PauseOnWorker(const std::string& player_id) {
    const auto player = FindPlayer(player_id);
    if (!player) {
      return {false, "player_not_found"};
    }
    if (player->terminal_error || !player->engine) {
      return {false, player->state.error_code.empty() ? "player_unavailable"
                                                      : player->state.error_code};
    }
    const HRESULT hr = player->engine->Pause();
    if (FAILED(hr)) {
      return {false, ErrorCodeForHRESULT(hr)};
    }
    RefreshState(*player);
    player->state.playing = false;
    Emit(*player);
    return {true, {}};
  }

  OperationResult SeekOnWorker(const std::string& player_id, double seconds) {
    if (!std::isfinite(seconds) || seconds < 0.0) {
      return {false, "invalid_position"};
    }
    const auto player = FindPlayer(player_id);
    if (!player) {
      return {false, "player_not_found"};
    }
    if (player->terminal_error || !player->engine) {
      return {false, player->state.error_code.empty() ? "player_unavailable"
                                                      : player->state.error_code};
    }
    const double duration = player->engine->GetDuration();
    if (std::isfinite(duration) && duration > 0.0) {
      seconds = std::min(seconds, duration);
    }
    const HRESULT hr = player->engine->SetCurrentTime(seconds);
    if (FAILED(hr)) {
      return {false, ErrorCodeForHRESULT(hr)};
    }
    RefreshState(*player);
    player->state.ended = false;
    Emit(*player);
    return {true, {}};
  }

  OperationResult SetVolumeOnWorker(const std::string& player_id,
                                    double volume) {
    if (!std::isfinite(volume) || volume < 0.0 || volume > 1.0) {
      return {false, "invalid_volume"};
    }
    const auto player = FindPlayer(player_id);
    if (!player) {
      return {false, "player_not_found"};
    }
    if (player->terminal_error || !player->engine) {
      return {false, player->state.error_code.empty() ? "player_unavailable"
                                                      : player->state.error_code};
    }
    const HRESULT hr = player->engine->SetVolume(volume);
    if (FAILED(hr)) {
      return {false, ErrorCodeForHRESULT(hr)};
    }
    RefreshState(*player);
    Emit(*player);
    return {true, {}};
  }

  OperationResult SetMutedOnWorker(const std::string& player_id, bool muted) {
    const auto player = FindPlayer(player_id);
    if (!player) {
      return {false, "player_not_found"};
    }
    if (player->terminal_error || !player->engine) {
      return {false, player->state.error_code.empty() ? "player_unavailable"
                                                      : player->state.error_code};
    }
    const HRESULT hr = player->engine->SetMuted(muted ? TRUE : FALSE);
    if (FAILED(hr)) {
      return {false, ErrorCodeForHRESULT(hr)};
    }
    RefreshState(*player);
    Emit(*player);
    return {true, {}};
  }

  void ProcessMediaNotice(Player& player,
                          DWORD event_type,
                          DWORD_PTR param1,
                          DWORD param2) {
    if (player.terminal_error && event_type != MF_MEDIA_ENGINE_EVENT_ERROR) {
      return;
    }
    switch (event_type) {
      case MF_MEDIA_ENGINE_EVENT_CANPLAY:
        player.state.can_play = true;
        RefreshState(player);
        Emit(player);
        break;
      case MF_MEDIA_ENGINE_EVENT_PLAYING:
        player.state.playing = true;
        player.state.ended = false;
        RefreshState(player);
        Emit(player);
        break;
      case MF_MEDIA_ENGINE_EVENT_PAUSE:
        player.state.playing = false;
        RefreshState(player);
        Emit(player);
        break;
      case MF_MEDIA_ENGINE_EVENT_ENDED:
        player.state.playing = false;
        player.state.ended = true;
        RefreshState(player);
        Emit(player);
        break;
      case MF_MEDIA_ENGINE_EVENT_DURATIONCHANGE:
      case MF_MEDIA_ENGINE_EVENT_VOLUMECHANGE:
        RefreshState(player);
        Emit(player);
        break;
      case MF_MEDIA_ENGINE_EVENT_ERROR: {
        const HRESULT detail = static_cast<HRESULT>(param2);
        const auto engine_error = static_cast<MF_MEDIA_ENGINE_ERR>(param1);
        std::string code;
        if (detail == MF_E_TOPO_CODEC_NOT_FOUND ||
            detail == MF_E_INVALIDMEDIATYPE ||
            engine_error == MF_MEDIA_ENGINE_ERR_SRC_NOT_SUPPORTED ||
            engine_error == MF_MEDIA_ENGINE_ERR_DECODE) {
          // Preview artifacts are worker-validated H.264; decode/source errors
          // are surfaced as codec/component failures, never as fake readiness.
          code = "codec_unavailable";
        } else if (engine_error == MF_MEDIA_ENGINE_ERR_NETWORK) {
          // The source is a local worker-owned byte stream; report this as read
          // failure without suggesting any URL/network fallback.
          code = "media_read_failed";
        } else if (engine_error == MF_MEDIA_ENGINE_ERR_ENCRYPTED) {
          code = "encrypted_media_unsupported";
        } else if (engine_error == MF_MEDIA_ENGINE_ERR_ABORTED) {
          code = "media_aborted";
        } else {
          code = ErrorCodeForHRESULT(detail);
          if (code == "media_engine_error") {
            code = "media_engine_error";
          }
        }
        SetPlayerError(player, std::move(code));
        break;
      }
      default:
        break;
    }
  }

  void RefreshState(Player& player) {
    if (player.terminal_error) {
      player.state.playing = false;
      return;
    }
    if (!player.engine) {
      return;
    }
    const double duration = player.engine->GetDuration();
    const double position = player.engine->GetCurrentTime();
    const double volume = player.engine->GetVolume();
    if (std::isfinite(duration) && duration >= 0.0) {
      player.state.duration_seconds = duration;
    }
    if (std::isfinite(position) && position >= 0.0) {
      player.state.position_seconds = position;
    }
    if (std::isfinite(volume)) {
      player.state.volume = std::clamp(volume, 0.0, 1.0);
    }
    player.state.muted = player.engine->GetMuted() != FALSE;
    if (player.state.ready && player.engine->IsEnded() != FALSE) {
      player.state.ended = true;
      player.state.playing = false;
    }
  }

  void Emit(const Player& player) {
    if (!event_callback_) {
      return;
    }
    try {
      event_callback_(player.state);
    } catch (...) {
      // A host callback must not unwind through Media Foundation or this worker.
    }
  }

  void SetPlayerError(Player& player, std::string error_code) {
    player.state.error_code = std::move(error_code);
    player.state.playing = false;
    player.terminal_error = true;
    if (player.engine) {
      // A terminal video/device failure must not leave an unmuted audio stream
      // running behind a preview that can no longer render frames.
      player.engine->Pause();
    }
    Emit(player);
  }

  void Tick(std::chrono::steady_clock::time_point now) {
    if (players_.empty()) {
      return;
    }
    std::vector<std::shared_ptr<Player>> active;
    active.reserve(players_.size());
    for (const auto& entry : players_) {
      active.push_back(entry.second);
    }

    for (const std::shared_ptr<Player>& player : active) {
      if (!player || player->terminal_error || !player->engine_ex ||
          !player->state.can_play) {
        continue;
      }

      const HRESULT frame_result = TransferFrame(*player);
      if (frame_result == S_OK) {
        if (!texture_registrar_->MarkTextureFrameAvailable(player->texture_id)) {
          SetPlayerError(*player, "texture_unavailable");
          continue;
        }
        if (!player->state.ready) {
          player->state.ready = true;
          Emit(*player);
        }
      } else if (frame_result == S_FALSE) {
        // Frame-server mode reports S_FALSE when no new decoded frame is ready.
      } else if (IsDeviceLost(frame_result)) {
        FailAllForDeviceLoss();
        return;
      } else if (frame_result != E_PENDING &&
                 frame_result != MF_E_INVALIDREQUEST &&
                 frame_result != MF_E_NOTACCEPTING) {
        SetPlayerError(*player, frame_result == E_OUTOFMEMORY
                                    ? "out_of_memory"
                                    : "frame_transfer_failed");
        continue;
      }

      if (player->state.playing &&
          (player->last_state_event.time_since_epoch().count() == 0 ||
           now - player->last_state_event >= kStateInterval)) {
        RefreshState(*player);
        Emit(*player);
        player->last_state_event = now;
      }
    }
  }

  HRESULT TransferFrame(Player& player) {
    LONGLONG presentation_time = 0;
    const HRESULT tick_hr = player.engine->OnVideoStreamTick(&presentation_time);
    if (tick_hr == S_FALSE) {
      return S_FALSE;
    }
    if (FAILED(tick_hr)) {
      return tick_hr;
    }
    (void)presentation_time;

    RECT destination{0, 0, player.width, player.height};
    const HRESULT transfer_hr = player.engine_ex->TransferVideoFrame(
        player.output_surface.Get(), nullptr, &destination, nullptr);
    if (FAILED(transfer_hr)) {
      return transfer_hr;
    }

    device_context_->CopyResource(player.staging_texture.Get(),
                                  player.output_texture.Get());
    D3D11_MAPPED_SUBRESOURCE mapped{};
    const HRESULT map_hr = device_context_->Map(
        player.staging_texture.Get(), 0, D3D11_MAP_READ, 0, &mapped);
    if (FAILED(map_hr)) {
      const HRESULT removal_hr = device_->GetDeviceRemovedReason();
      return FAILED(removal_hr) ? removal_hr : map_hr;
    }

    const size_t width = static_cast<size_t>(player.width);
    const size_t height = static_cast<size_t>(player.height);
    const size_t row_bytes = width * 4;
    if (mapped.pData == nullptr || mapped.RowPitch < row_bytes) {
      device_context_->Unmap(player.staging_texture.Get(), 0);
      return E_UNEXPECTED;
    }

    std::shared_ptr<VideoFrame> frame;
    try {
      frame = std::make_shared<VideoFrame>();
      frame->width = width;
      frame->height = height;
      frame->bgra.resize(row_bytes * height);
      const auto* source = static_cast<const uint8_t*>(mapped.pData);
      for (size_t row = 0; row < height; ++row) {
        std::memcpy(frame->bgra.data() + row * row_bytes,
                    source + row * mapped.RowPitch, row_bytes);
      }
    } catch (...) {
      device_context_->Unmap(player.staging_texture.Get(), 0);
      return E_OUTOFMEMORY;
    }
    device_context_->Unmap(player.staging_texture.Get(), 0);
    player.PublishFrame(std::move(frame));
    return S_OK;
  }

  void FailAllForDeviceLoss() {
    std::vector<std::shared_ptr<Player>> active;
    active.reserve(players_.size());
    for (const auto& entry : players_) {
      active.push_back(entry.second);
    }
    for (const std::shared_ptr<Player>& player : active) {
      if (player && !player->terminal_error) {
        SetPlayerError(*player, "device_lost");
      }
    }
  }

  void FailAllForInternalError() noexcept {
    for (auto& entry : players_) {
      const std::shared_ptr<Player>& player = entry.second;
      if (!player || player->terminal_error) {
        continue;
      }
      try {
        player->state.error_code = "native_internal_error";
      } catch (...) {
      }
      player->state.playing = false;
      player->terminal_error = true;
      if (player->engine) {
        player->engine->Pause();
      }
    }
  }

  void DisposePlayer(const std::shared_ptr<Player>& player) {
    if (!player) {
      return;
    }
    player->accepting_frames.store(false, std::memory_order_release);
    player->ShutdownEngine();
    if (player->texture_id >= 0 && texture_registrar_ != nullptr) {
      // Flutter unregister is asynchronous. Retain the PixelBufferTexture and
      // its callback state until Flutter confirms it no longer references it.
      const int64_t texture_id = player->texture_id;
      try {
        texture_registrar_->UnregisterTexture(texture_id,
                                              [keep_alive = player] {});
      } catch (...) {
        // Fall back to the registrar's synchronous overload if allocating the
        // async completion closure fails during low-memory cleanup.
        try {
          texture_registrar_->UnregisterTexture(texture_id);
        } catch (...) {
        }
      }
      player->texture_id = -1;
    }
    {
      std::lock_guard<std::mutex> lock(player->frame_mutex);
      player->latest_frame.reset();
    }
  }

  void DisposeAllOnWorker() {
    while (!players_.empty()) {
      auto found = players_.begin();
      std::shared_ptr<Player> player = std::move(found->second);
      players_.erase(found);
      DisposePlayer(player);
    }
  }

  flutter::TextureRegistrar* const texture_registrar_;
  EventCallback event_callback_;
  std::thread worker_;
  std::thread::id worker_id_;
  std::mutex queue_mutex_;
  std::condition_variable queue_condition_;
  std::deque<std::function<void()>> queue_;
  bool stopping_ = false;
  bool mf_started_ = false;
  std::string startup_error_code_;
  uint64_t next_player_id_ = 1;
  std::unordered_map<std::string, std::shared_ptr<Player>> players_;
  ComPtr<ID3D11Device> device_;
  ComPtr<ID3D11DeviceContext> device_context_;
  ComPtr<IMFDXGIDeviceManager> device_manager_;
};

NativeMediaManager::NativeMediaManager(
    flutter::TextureRegistrar* texture_registrar,
    EventCallback event_callback) {
  try {
    core_ = std::make_shared<Core>(texture_registrar, std::move(event_callback));
    if (!core_->Start()) {
      core_.reset();
    }
  } catch (...) {
    core_.reset();
  }
}

NativeMediaManager::~NativeMediaManager() {
  if (core_) {
    core_->Stop();
    core_.reset();
  }
}

NativeMediaCreateResult NativeMediaManager::Create(HANDLE owned_read_handle,
                                                    int width,
                                                    int height) {
  if (!core_) {
    if (IsUsableHandle(owned_read_handle)) {
      CloseHandle(owned_read_handle);
    }
    return CreateFailure("media_engine_unavailable");
  }
  return core_->Create(owned_read_handle, width, height);
}

bool NativeMediaManager::Play(const std::string& player_id,
                              std::string* error_code) {
  const OperationResult result =
      core_ ? core_->Play(player_id) : OperationResult{false, "manager_stopped"};
  if (error_code != nullptr) {
    *error_code = result.error_code;
  }
  return result.ok;
}

bool NativeMediaManager::Pause(const std::string& player_id,
                               std::string* error_code) {
  const OperationResult result = core_ ? core_->Pause(player_id)
                                       : OperationResult{false, "manager_stopped"};
  if (error_code != nullptr) {
    *error_code = result.error_code;
  }
  return result.ok;
}

bool NativeMediaManager::Seek(const std::string& player_id,
                              double position_seconds,
                              std::string* error_code) {
  const OperationResult result =
      core_ ? core_->Seek(player_id, position_seconds)
            : OperationResult{false, "manager_stopped"};
  if (error_code != nullptr) {
    *error_code = result.error_code;
  }
  return result.ok;
}

bool NativeMediaManager::SetVolume(const std::string& player_id,
                                   double volume,
                                   std::string* error_code) {
  const OperationResult result =
      core_ ? core_->SetVolume(player_id, volume)
            : OperationResult{false, "manager_stopped"};
  if (error_code != nullptr) {
    *error_code = result.error_code;
  }
  return result.ok;
}

bool NativeMediaManager::SetMuted(const std::string& player_id,
                                  bool muted,
                                  std::string* error_code) {
  const OperationResult result =
      core_ ? core_->SetMuted(player_id, muted)
            : OperationResult{false, "manager_stopped"};
  if (error_code != nullptr) {
    *error_code = result.error_code;
  }
  return result.ok;
}

bool NativeMediaManager::State(const std::string& player_id,
                               NativeMediaEvent* state,
                               std::string* error_code) {
  if (state == nullptr) {
    if (error_code != nullptr) {
      *error_code = "invalid_argument";
    }
    return false;
  }
  const std::optional<NativeMediaEvent> result =
      core_ ? core_->State(player_id) : std::nullopt;
  if (!result.has_value()) {
    if (error_code != nullptr) {
      *error_code = core_ ? "player_not_found" : "manager_stopped";
    }
    return false;
  }
  *state = *result;
  if (error_code != nullptr) {
    error_code->clear();
  }
  return true;
}

bool NativeMediaManager::Dispose(const std::string& player_id,
                                 std::string* error_code) {
  const OperationResult result =
      core_ ? core_->Dispose(player_id)
            : OperationResult{true, {}};
  if (error_code != nullptr) {
    *error_code = result.error_code;
  }
  return result.ok;
}

void NativeMediaManager::DisposeAll() {
  if (core_) {
    core_->DisposeAll();
  }
}

}  // namespace chasteady
