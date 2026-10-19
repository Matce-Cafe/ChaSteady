#ifndef NOMINMAX
#define NOMINMAX
#endif
#include "native_bridge.h"

#include "native_media.h"
#include "media_drop_target.h"
#include "native_launch_configuration.h"
#include "preview_lease_bookkeeping.h"
#include "window_chrome.h"
#include "worker_supervisor.h"

#include <windows.h>
#include <shellapi.h>
#include <shobjidl.h>
#include <wrl/client.h>

#include <flutter/encodable_value.h>
#include <flutter/method_channel.h>
#include <flutter/standard_method_codec.h>
#include <flutter/texture_registrar.h>

#include <algorithm>
#include <atomic>
#include <cmath>
#include <condition_variable>
#include <cstdint>
#include <deque>
#include <functional>
#include <initializer_list>
#include <iterator>
#include <map>
#include <memory>
#include <mutex>
#include <new>
#include <string>
#include <thread>
#include <unordered_map>
#include <utility>
#include <vector>

namespace chasteady {
namespace {

using Microsoft::WRL::ComPtr;
using EncodableMap = flutter::EncodableMap;
using EncodableValue = flutter::EncodableValue;
using MethodChannel = flutter::MethodChannel<EncodableValue>;
using MethodResult = flutter::MethodResult<EncodableValue>;
using MethodCall = flutter::MethodCall<EncodableValue>;

constexpr char kNativeChannelName[] = "chasteady/native";
constexpr UINT kNativeReplyMessage = WM_APP + 0x4a0;
constexpr UINT kNativeEventMessage = WM_APP + 0x4a1;
constexpr UINT_PTR kCloseRequestTimer = 0x4a0;
constexpr UINT_PTR kShutdownWarningTimer = 0x4a2;
constexpr UINT_PTR kOwnedProcessObservationTimer = 0x4a3;
constexpr UINT kOwnedProcessObservationMilliseconds = 100;
constexpr UINT kCloseRequestTimeoutMilliseconds = 60000;
constexpr UINT kShutdownWarningTimeoutMilliseconds = 60000;
constexpr UINT kNativeReplySendTimeoutMilliseconds = 250;

const EncodableValue* FindValue(const EncodableMap* map, const char* key) {
  if (map == nullptr) return nullptr;
  const auto found = map->find(EncodableValue(std::string(key)));
  return found == map->end() ? nullptr : &found->second;
}

bool IsNull(const EncodableValue* value) {
  return value == nullptr || value->IsNull();
}

bool IsMap(const EncodableValue* value, const EncodableMap** map) {
  if (value == nullptr || !std::holds_alternative<EncodableMap>(*value)) return false;
  if (map != nullptr) *map = &std::get<EncodableMap>(*value);
  return true;
}

bool HasExactKeys(const EncodableMap& map,
                  std::initializer_list<const char*> keys) {
  if (map.size() != keys.size()) return false;
  for (const char* key : keys) {
    if (FindValue(&map, key) == nullptr) return false;
  }
  return true;
}

bool GetString(const EncodableValue* value, std::string* output) {
  if (value == nullptr || output == nullptr ||
      !std::holds_alternative<std::string>(*value)) return false;
  *output = std::get<std::string>(*value);
  return true;
}

bool GetBoolean(const EncodableValue* value, bool* output) {
  if (value == nullptr || output == nullptr ||
      !std::holds_alternative<bool>(*value)) return false;
  *output = std::get<bool>(*value);
  return true;
}

bool GetFiniteNumber(const EncodableValue* value, double* output) {
  if (value == nullptr || output == nullptr) return false;
  double parsed = 0.0;
  if (std::holds_alternative<double>(*value)) parsed = std::get<double>(*value);
  else if (std::holds_alternative<int32_t>(*value)) parsed = std::get<int32_t>(*value);
  else if (std::holds_alternative<int64_t>(*value)) parsed = static_cast<double>(std::get<int64_t>(*value));
  else return false;
  if (!std::isfinite(parsed)) return false;
  *output = parsed;
  return true;
}

bool GetPositiveGeneration(const EncodableValue* value, int64_t* output) {
  if (value == nullptr || output == nullptr) return false;
  if (std::holds_alternative<int64_t>(*value)) *output = std::get<int64_t>(*value);
  else if (std::holds_alternative<int32_t>(*value)) *output = std::get<int32_t>(*value);
  else return false;
  return *output > 0;
}

WorkerSupervisorOptions SupervisorOptions(
    std::shared_ptr<const NativeLaunchConfiguration> configuration) {
  WorkerSupervisorOptions options;
  options.launch_configuration = std::move(configuration);
  return options;
}

bool NoArguments(const EncodableValue* value) {
  return IsNull(value);
}

bool IsCanonicalUuid(const std::string& value) {
  if (value.size() != 36) return false;
  for (size_t index = 0; index < value.size(); ++index) {
    if (index == 8 || index == 13 || index == 18 || index == 23) {
      if (value[index] != '-') return false;
      continue;
    }
    const char ch = value[index];
    if (!((ch >= '0' && ch <= '9') || (ch >= 'a' && ch <= 'f') ||
          (ch >= 'A' && ch <= 'F'))) return false;
  }
  return true;
}

std::string LowercaseUuid(std::string value) {
  std::transform(value.begin(), value.end(), value.begin(), [](unsigned char ch) {
    return static_cast<char>(ch >= 'A' && ch <= 'F' ? ch - 'A' + 'a' : ch);
  });
  return value;
}

std::wstring Utf8ToWide(const std::string& value) {
  if (value.empty()) return {};
  const int required = MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS,
      value.data(), static_cast<int>(value.size()), nullptr, 0);
  if (required <= 0) return {};
  std::wstring output(static_cast<size_t>(required), L'\0');
  if (MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, value.data(),
      static_cast<int>(value.size()), output.data(), required) != required) return {};
  return output;
}

std::string WideToUtf8(const std::wstring& value) {
  if (value.empty()) return {};
  const int required = WideCharToMultiByte(CP_UTF8, WC_ERR_INVALID_CHARS,
      value.data(), static_cast<int>(value.size()), nullptr, 0, nullptr, nullptr);
  if (required <= 0) return {};
  std::string output(static_cast<size_t>(required), '\0');
  if (WideCharToMultiByte(CP_UTF8, WC_ERR_INVALID_CHARS, value.data(),
      static_cast<int>(value.size()), output.data(), required, nullptr, nullptr) != required) return {};
  return output;
}

EncodableValue StateValue(const NativeMediaEvent& state) {
  EncodableMap map;
  map.emplace(EncodableValue("player_id"), EncodableValue(state.player_id));
  map.emplace(EncodableValue("ready"), EncodableValue(state.ready));
  map.emplace(EncodableValue("can_play"), EncodableValue(state.can_play));
  map.emplace(EncodableValue("playing"), EncodableValue(state.playing));
  map.emplace(EncodableValue("position_seconds"), EncodableValue(state.position_seconds));
  map.emplace(EncodableValue("duration_seconds"), EncodableValue(state.duration_seconds));
  map.emplace(EncodableValue("volume"), EncodableValue(state.volume));
  map.emplace(EncodableValue("muted"), EncodableValue(state.muted));
  map.emplace(EncodableValue("ended"), EncodableValue(state.ended));
  map.emplace(EncodableValue("error_code"), EncodableValue(state.error_code));
  return EncodableValue(std::move(map));
}

EncodableValue WindowStateValue(const WindowChrome::State& state) {
  EncodableMap map;
  map.emplace(EncodableValue("supported"), EncodableValue(state.supported));
  map.emplace(EncodableValue("customFrameEnabled"), EncodableValue(state.custom_frame_enabled));
  map.emplace(EncodableValue("maximized"), EncodableValue(state.maximized));
  map.emplace(EncodableValue("alwaysOnTop"), EncodableValue(state.always_on_top));
  map.emplace(EncodableValue("maximizeButtonHovered"), EncodableValue(state.maximize_button_hovered));
  map.emplace(EncodableValue("maximizeButtonPressed"), EncodableValue(state.maximize_button_pressed));
  return EncodableValue(std::move(map));
}

EncodableValue ErrorDetails(const WorkerFailure& failure) {
  EncodableMap args;
  EncodableMap details;
  details.emplace(EncodableValue("message_key"), EncodableValue(failure.message_key));
  // Current desktop worker typed errors carry no interpolation arguments; this
  // stays an object, matching the contract's typed {message_key,args} envelope.
  details.emplace(EncodableValue("args"), EncodableValue(std::move(args)));
  return EncodableValue(std::move(details));
}

void CompleteMethodError(std::unique_ptr<MethodResult> result,
                   const std::string& code,
                   const std::string& key,
                   const std::string& message) {
  if (!result) return;
  WorkerFailure failure;
  failure.code = code.empty() ? "native_error" : code;
  failure.message_key = key;
  failure.message = message;
  result->Error(failure.code, failure.message,
                ErrorDetails(failure));
}

class CallbackGate final {
 public:
  bool Enter() {
    std::lock_guard<std::mutex> lock(mutex_);
    if (closing_) return false;
    ++active_;
    return true;
  }

  void Leave() {
    std::lock_guard<std::mutex> lock(mutex_);
    if (active_ > 0) --active_;
    if (closing_ && active_ == 0) condition_.notify_all();
  }

  void CloseAndWait() {
    std::unique_lock<std::mutex> lock(mutex_);
    closing_ = true;
    condition_.wait(lock, [this] { return active_ == 0; });
  }

 private:
  std::mutex mutex_;
  std::condition_variable condition_;
  bool closing_ = false;
  size_t active_ = 0;
};

class GateLease final {
 public:
  explicit GateLease(std::shared_ptr<CallbackGate> gate) : gate_(std::move(gate)) {
    entered_ = gate_ && gate_->Enter();
  }
  ~GateLease() { if (entered_) gate_->Leave(); }
  GateLease(const GateLease&) = delete;
  GateLease& operator=(const GateLease&) = delete;
  explicit operator bool() const { return entered_; }
 private:
  std::shared_ptr<CallbackGate> gate_;
  bool entered_ = false;
};

class TaskQueue final {
 public:
  TaskQueue() : thread_([this] { Run(); }) {}
  ~TaskQueue() { StopAndJoin(); }
  TaskQueue(const TaskQueue&) = delete;
  TaskQueue& operator=(const TaskQueue&) = delete;

  bool Post(std::function<void()> task) {
    if (!task) return false;
    {
      std::lock_guard<std::mutex> lock(mutex_);
      if (stopping_) return false;
      tasks_.push_back(std::move(task));
    }
    condition_.notify_one();
    return true;
  }

  void StopAndJoin() {
    {
      std::lock_guard<std::mutex> lock(mutex_);
      stopping_ = true;
    }
    condition_.notify_all();
    if (thread_.joinable()) {
      if (thread_.get_id() == std::this_thread::get_id()) thread_.detach();
      else thread_.join();
    }
  }

 private:
  void Run() {
    for (;;) {
      std::function<void()> task;
      {
        std::unique_lock<std::mutex> lock(mutex_);
        condition_.wait(lock, [this] { return stopping_ || !tasks_.empty(); });
        if (tasks_.empty() && stopping_) return;
        task = std::move(tasks_.front());
        tasks_.pop_front();
      }
      try { task(); } catch (...) {}
    }
  }

  std::mutex mutex_;
  std::condition_variable condition_;
  std::deque<std::function<void()>> tasks_;
  bool stopping_ = false;
  std::thread thread_;
};

template <typename Function>
class CallbackMethodResult final : public MethodResult {
 public:
  explicit CallbackMethodResult(Function callback) : callback_(std::move(callback)) {}

 protected:
  void SuccessInternal(const EncodableValue* result) override {
    if (callback_) callback_(true, result, false);
  }
  void ErrorInternal(const std::string&, const std::string&,
                     const EncodableValue*) override {
    if (callback_) callback_(false, nullptr, false);
  }
  void NotImplementedInternal() override {
    if (callback_) callback_(false, nullptr, true);
  }

 private:
  Function callback_;
};

struct FileDialogResult final {
  bool cancelled = false;
  std::string path;
  std::string error_code;
};

FileDialogResult ShowNativePicker(HWND owner, const std::string& kind) {
  FileDialogResult output;
  const HRESULT initialized = CoInitializeEx(nullptr, COINIT_APARTMENTTHREADED);
  const bool uninitialize = SUCCEEDED(initialized);
  if (FAILED(initialized) && initialized != RPC_E_CHANGED_MODE) {
    output.error_code = "file_picker_unavailable";
    return output;
  }

  ComPtr<IFileOpenDialog> dialog;
  HRESULT hr = CoCreateInstance(CLSID_FileOpenDialog, nullptr, CLSCTX_INPROC_SERVER,
                                IID_PPV_ARGS(dialog.GetAddressOf()));
  if (FAILED(hr)) {
    output.error_code = "file_picker_unavailable";
    if (uninitialize) CoUninitialize();
    return output;
  }

  DWORD options = 0;
  hr = dialog->GetOptions(&options);
  if (SUCCEEDED(hr)) {
    options |= FOS_FORCEFILESYSTEM | FOS_PATHMUSTEXIST;
    if (kind == "folder") options |= FOS_PICKFOLDERS;
    else options |= FOS_FILEMUSTEXIST;
    hr = dialog->SetOptions(options);
  }

  const COMDLG_FILTERSPEC video_types[] = {
      {L"*.mp4; *.mov; *.m4v; *.mkv; *.avi; *.webm; *.mts; *.m2ts; *.mpg; *.mpeg",
       L"*.mp4;*.mov;*.m4v;*.mkv;*.avi;*.webm;*.mts;*.m2ts;*.mpg;*.mpeg"},
      {L"*.*", L"*.*"},
  };
  const COMDLG_FILTERSPEC project_types[] = {
      {L"*.gyroflow; *.gcsv; *.csv; *.json", L"*.gyroflow;*.gcsv;*.csv;*.json"},
      {L"*.*", L"*.*"},
  };
  const COMDLG_FILTERSPEC executable_types[] = {
      {L"*.exe", L"*.exe"},
      {L"*.*", L"*.*"},
  };
  if (SUCCEEDED(hr) && kind != "folder") {
    if (kind == "video") hr = dialog->SetFileTypes(static_cast<UINT>(std::size(video_types)), video_types);
    else if (kind == "project") hr = dialog->SetFileTypes(static_cast<UINT>(std::size(project_types)), project_types);
    else if (kind == "executable") hr = dialog->SetFileTypes(static_cast<UINT>(std::size(executable_types)), executable_types);
    else hr = E_INVALIDARG;
  }
  if (SUCCEEDED(hr)) hr = dialog->Show(owner);
  if (hr == HRESULT_FROM_WIN32(ERROR_CANCELLED)) {
    output.cancelled = true;
  } else if (FAILED(hr)) {
    output.error_code = "file_picker_failed";
  } else {
    ComPtr<IShellItem> item;
    hr = dialog->GetResult(item.GetAddressOf());
    PWSTR path = nullptr;
    if (SUCCEEDED(hr)) hr = item->GetDisplayName(SIGDN_FILESYSPATH, &path);
    if (SUCCEEDED(hr) && path != nullptr) output.path = WideToUtf8(path);
    if (path != nullptr) CoTaskMemFree(path);
    if (FAILED(hr) || output.path.empty()) output.error_code = "file_picker_failed";
  }
  dialog.Reset();
  if (uninitialize) CoUninitialize();
  return output;
}

}  // namespace

class NativeBridge::Impl final {
 public:
  Impl(HWND owner_window,
       HWND flutter_child,
       flutter::BinaryMessenger* messenger,
       flutter::TextureRegistrar* texture_registrar,
       std::shared_ptr<const NativeLaunchConfiguration> launch_configuration)
      : owner_window_(owner_window),
        gate_(std::make_shared<CallbackGate>()),
        supervisor_(SupervisorOptions(std::move(launch_configuration))),
        media_manager_(texture_registrar,
            [this, gate = gate_](const NativeMediaEvent& event) {
              GateLease lease(gate);
              if (!lease) return;
              PostMediaEvent(event);
            }),
        channel_(std::make_unique<MethodChannel>(messenger, kNativeChannelName,
            &flutter::StandardMethodCodec::GetInstance())) {
    window_chrome_ = std::make_unique<WindowChrome>(owner_window_, flutter_child,
        [this](const WindowChrome::State& state) {
          // Chrome lives and emits only on the platform thread, never through
          // the worker operation queue. WindowChrome deduplicates snapshots.
          if (!destroying_.load(std::memory_order_acquire) && channel_) {
#ifdef CHASTEADY_WINDOW_DIAGNOSTICS
            if (window_chrome_) window_chrome_->RecordDiagnostic("dart-state-handoff");
#endif
            channel_->InvokeMethod("windowStateChanged",
                std::make_unique<EncodableValue>(WindowStateValue(state)));
          }
        });
    media_drop_ = std::make_unique<MediaDropTarget>(owner_window_, flutter_child,
        [this] {
          return bootstrap_ready_.load(std::memory_order_acquire) &&
              !worker_session_failed_.load(std::memory_order_acquire) &&
              !shutdown_in_progress_.load(std::memory_order_acquire) &&
              !window_close_pending_.load(std::memory_order_acquire) &&
              !destroying_.load(std::memory_order_acquire);
        },
        [this](const std::string& target, int64_t generation, const std::string& path) {
          if (!channel_ || destroying_.load(std::memory_order_acquire)) return;
          EncodableMap event;
          event.emplace(EncodableValue("targetId"), EncodableValue(target));
          event.emplace(EncodableValue("generation"), EncodableValue(generation));
          event.emplace(EncodableValue("path"), EncodableValue(path));
          channel_->InvokeMethod("mediaFileDropped",
              std::make_unique<EncodableValue>(std::move(event)));
        });
    const std::shared_ptr<CallbackGate> gate = gate_;
    supervisor_.SetExitCallback([this, gate] {
      GateLease lease(gate);
      if (!lease) return;
      worker_session_failed_.store(true, std::memory_order_release);
      UiEvent event;
      event.type = UiEvent::Type::kWorkerSessionFailed;
      event.generation = supervisor_.ObserveOwnedProcess().generation;
      PostEvent(std::move(event));
    });
    channel_->SetMethodCallHandler([this, gate](const MethodCall& call,
                                std::unique_ptr<MethodResult> result) mutable {
      GateLease lease(gate);
      if (!lease) return;
      HandleMethodCall(call, std::move(result));
    });
  }

  ~Impl() {
    // Engine/window teardown cancels any MethodResults still pending; never
    // synthesize a Dart success after the channel owner begins destruction.
    destroying_.store(true, std::memory_order_release);
    terminal_observer_active_.store(false, std::memory_order_release);
    KillTimer(owner_window_, kOwnedProcessObservationTimer);
    if (channel_) channel_->SetMethodCallHandler(nullptr);
    gate_->CloseAndWait();
    // 在 Flutter child / OLE apartment 析构之前撤销拖放注册及子类。
    media_drop_.reset();
    // Remove the documented Flutter child subclass before engine/child teardown.
    window_chrome_.reset();
    KillTimer(owner_window_, kCloseRequestTimer);
    KillTimer(owner_window_, kShutdownWarningTimer);
    operation_queue_.Post([this] {
      media_manager_.DisposeAll();
      // Stop 只转交原有清理链，返回本身不是终态；未 signaled 时不作可信清账。
      supervisor_.Stop();
      const OwnedWorkerProcessObservation observation = supervisor_.ObserveOwnedProcess();
      player_leases_.ClearForTerminalWorker(observation);
    });
    operation_queue_.StopAndJoin();
    supervisor_.Stop();
    {
      std::lock_guard<std::mutex> lock(reply_mutex_);
      pending_replies_.clear();
    }
    {
      std::lock_guard<std::mutex> lock(event_mutex_);
      ui_events_.clear();
    }
    channel_.reset();
  }

  bool HandleWindowMessage(HWND window, UINT message, WPARAM wparam,
                           LPARAM lparam, LRESULT* result) {
    if (window != owner_window_) return false;
    if (media_drop_) media_drop_->HandleWindowMessage(message, wparam, lparam);
    if (!destroying_.load(std::memory_order_acquire)) {
      DrainDeferredReplies();
      EnsureOwnedProcessObservationTimer();
    }
    if (window_chrome_ && window_chrome_->HandleWindowMessage(
        window, message, wparam, lparam, result)) return true;
    if (message == WM_CLOSE) {
      if (CloseRequest()) {
        if (result != nullptr) *result = 0;
        return true;
      }
      return false;
    }
    if (message == WM_TIMER && wparam == kCloseRequestTimer) {
      KillTimer(window, kCloseRequestTimer);
      if (close_pending_) {
        close_pending_ = false;
        window_close_pending_.store(false, std::memory_order_release);
        close_needs_dart_confirmation_ = false;
        ++close_generation_;
      }
      if (result != nullptr) *result = 0;
      return true;
    }
    if (message == WM_TIMER && wparam == kOwnedProcessObservationTimer) {
      QueueOwnedProcessObservation();
      if (result != nullptr) *result = 0;
      return true;
    }
    if (message == WM_TIMER && wparam == kShutdownWarningTimer) {
      KillTimer(window, kShutdownWarningTimer);
      if (shutdown_warning_pending_) FinishShutdownWarning();
      if (result != nullptr) *result = 0;
      return true;
    }
    if (message == kNativeReplyMessage) {
      HandleReplyMessage(static_cast<uint64_t>(wparam));
      if (result != nullptr) *result = 0;
      return true;
    }
    if (message == kNativeEventMessage) {
      HandleEventMessage(static_cast<uint64_t>(wparam));
      if (result != nullptr) *result = 0;
      return true;
    }
    return false;
  }

  bool CloseRequest() {
    if (media_drop_) media_drop_->Disable();
    if (close_committed_) return false;
    if (shutdown_requested_.load(std::memory_order_acquire) &&
        !shutdown_warning_pending_) {
      if (close_pending_) return true;  // Wait for an active Dart close callback/result.
      close_pending_ = true;
      window_close_pending_.store(true, std::memory_order_release);
      close_needs_dart_confirmation_ = false;
      ++close_generation_;
      if (shutdown_result_delivered_.load(std::memory_order_acquire)) {
        CommitClose(close_generation_);
      }
      return true;
    }
    if (shutdown_in_progress_.load(std::memory_order_acquire) && !close_pending_) {
      close_pending_ = true;
      window_close_pending_.store(true, std::memory_order_release);
      close_needs_dart_confirmation_ = false;
      ++close_generation_;
      return true;
    }
    if (close_pending_) return true;
    close_pending_ = true;
    window_close_pending_.store(true, std::memory_order_release);
    const uint64_t generation = ++close_generation_;
    SetTimer(owner_window_, kCloseRequestTimer, kCloseRequestTimeoutMilliseconds, nullptr);

    // Before the worker is ready, Dart's application close handler has not yet
    // been installed and no jobs can have been submitted. Cancel bootstrap or
    // clean up the starting worker directly instead of waiting forever for Dart.
    if (!bootstrap_ready_.load(std::memory_order_acquire)) {
      close_needs_dart_confirmation_ = false;
      ShutdownForClose(generation);
      return true;
    }
    close_needs_dart_confirmation_ = true;

    const std::shared_ptr<CallbackGate> gate = gate_;
    auto callback = std::make_unique<CallbackMethodResult<
        std::function<void(bool, const EncodableValue*, bool)>>>(
        [this, gate, generation](bool success, const EncodableValue* value,
                                 bool not_implemented) {
          GateLease lease(gate);
          if (!lease) return;
          bool accepted = false;
          if (success && value != nullptr && std::holds_alternative<bool>(*value)) {
            accepted = std::get<bool>(*value);
          }
          UiEvent event;
          event.type = UiEvent::Type::kCloseReply;
          event.generation = generation;
          event.accepted = accepted;
          event.not_implemented = not_implemented;
          PostEvent(std::move(event));
        });
    channel_->InvokeMethod("requestClose", nullptr, std::move(callback));
    return true;
  }

 private:
  struct PendingReply final {
    std::unique_ptr<MethodResult> result;
    std::function<void()> after_success;
    bool completed = false;
    bool success = false;
    EncodableValue value;
    std::string error_code;
    std::string error_message;
    EncodableValue error_details;
    bool delivery_deferred = false;
  };

  struct UiEvent final {
    enum class Type {
      kMedia, kWebSession, kCloseReply, kCloseFallback, kWorkerSessionFailed,
      kShutdownWarning, kShutdownWarningReply, kShutdownFailed, kOwnedProcessObserved,
    };
    Type type = Type::kWorkerSessionFailed;
    NativeMediaEvent media;
    uint64_t method_id = 0;
    uint64_t generation = 0;
    bool accepted = false;
    bool not_implemented = false;
    std::string url;
  };

  // 平台线程只调度；账本与 Wait0 观测仍由同一个 operation_queue 独占。
  void BeginOwnedProcessObservation(uint64_t generation) {
    if (generation == 0 || destroying_.load(std::memory_order_acquire) ||
        generation < terminal_observer_generation_.load(std::memory_order_acquire)) return;
    terminal_observer_generation_.store(generation, std::memory_order_release);
    terminal_observer_active_.store(true, std::memory_order_release);
    EnsureOwnedProcessObservationTimer();
    QueueOwnedProcessObservation();
  }

  void EnsureOwnedProcessObservationTimer() {
    if (terminal_observer_timer_armed_ || !terminal_observer_active_.load(std::memory_order_acquire)) return;
    const ULONGLONG now = GetTickCount64();
    if (now < terminal_observer_retry_tick_) return;
    terminal_observer_retry_tick_ = now + kOwnedProcessObservationMilliseconds;
    terminal_observer_timer_armed_ = SetTimer(owner_window_, kOwnedProcessObservationTimer,
        kOwnedProcessObservationMilliseconds, nullptr) != 0;
    // timer 不可用时保留账本；一次观测及后续平台消息可重试，不伪造进程终态。
    if (!terminal_observer_timer_armed_) QueueOwnedProcessObservation();
  }

  void StopOwnedProcessObservation(uint64_t generation) {
    if (generation != terminal_observer_generation_.load(std::memory_order_acquire)) return;
    terminal_observer_active_.store(false, std::memory_order_release);
    KillTimer(owner_window_, kOwnedProcessObservationTimer);
    terminal_observer_timer_armed_ = false;
  }

  void QueueOwnedProcessObservation() {
    if (destroying_.load(std::memory_order_acquire) ||
        !terminal_observer_active_.load(std::memory_order_acquire)) return;
    bool pending = false;
    if (!terminal_observer_poll_pending_.compare_exchange_strong(pending, true, std::memory_order_acq_rel)) return;
    const uint64_t generation = terminal_observer_generation_.load(std::memory_order_acquire);
    const std::shared_ptr<CallbackGate> gate = gate_;
    if (!operation_queue_.Post([this, gate, generation] {
          struct PendingPoll final {
            std::atomic<bool>& pending;
            ~PendingPoll() { pending.store(false, std::memory_order_release); }
          } reset{terminal_observer_poll_pending_};
          GateLease lease(gate);
          if (!lease || destroying_.load(std::memory_order_acquire) ||
              !terminal_observer_active_.load(std::memory_order_acquire) ||
              generation != terminal_observer_generation_.load(std::memory_order_acquire)) return;
          const OwnedWorkerProcessObservation observation = supervisor_.ObserveOwnedProcess();
          const uint64_t ledger_generation = player_leases_.WorkerGeneration();
          bool finished = observation.generation != generation ||
              (ledger_generation != 0 && ledger_generation != generation);
          if (!finished && observation.IsVerifiedTerminal()) {
            if (ledger_generation == 0 && player_leases_.size() == 0) player_leases_.BindWorker(observation);
            finished = player_leases_.ClearForTerminalWorker(observation);
          }
          if (finished && !destroying_.load(std::memory_order_acquire)) {
            UiEvent event;
            event.type = UiEvent::Type::kOwnedProcessObserved;
            event.generation = generation;
            PostEvent(std::move(event));
          }
        })) {
      terminal_observer_poll_pending_.store(false, std::memory_order_release);
    }
  }

  bool ConfirmTerminalPreviewWorker(uint64_t expected_generation) {
    const OwnedWorkerProcessObservation observation = supervisor_.ObserveOwnedProcess();
    if (player_leases_.CanCloseReapedStartupFailure(observation, expected_generation,
        bootstrap_ready_.load(std::memory_order_acquire))) return true;
    // startup 可在 Stop join 期间才建立身份；只允许空且未绑定账本接纳该已验证终态。
    const bool late_startup_identity = expected_generation == 0 && observation.generation != 0 &&
        player_leases_.WorkerGeneration() == 0 && player_leases_.size() == 0;
    if (observation.generation != expected_generation && !late_startup_identity) return false;
    // 只有 Supervisor 已确认的 pre-start shutdown 可没有原进程；此分支不调用清账 API。
    if (observation.generation == 0) return player_leases_.WorkerGeneration() == 0 && player_leases_.size() == 0;
    if (!observation.IsVerifiedTerminal()) return false;
    if (player_leases_.WorkerGeneration() == 0 && player_leases_.size() == 0) player_leases_.BindWorker(observation);
    return player_leases_.ClearForTerminalWorker(observation);
  }

  uint64_t StoreReply(std::unique_ptr<MethodResult> result) {
    if (!result) return 0;
    const uint64_t id = next_message_id_.fetch_add(1, std::memory_order_relaxed);
    PendingReply reply;
    reply.result = std::move(result);
    std::lock_guard<std::mutex> lock(reply_mutex_);
    pending_replies_.emplace(id, std::move(reply));
    return id;
  }

  void CompleteSuccess(uint64_t id,
                       EncodableValue value = EncodableValue(),
                       std::function<void()> after_success = {}) {
    if (id == 0) return;
    {
      std::lock_guard<std::mutex> lock(reply_mutex_);
      const auto found = pending_replies_.find(id);
      if (found == pending_replies_.end() || found->second.completed) return;
      found->second.completed = true;
      found->second.success = true;
      found->second.value = std::move(value);
      found->second.after_success = std::move(after_success);
    }
    if (!PostMessage(owner_window_, kNativeReplyMessage, static_cast<WPARAM>(id), 0)) {
      HandleReplyPostFailure(id);
    }
  }

  void CompleteError(uint64_t id, const std::string& code,
                     const std::string& key,
                     const std::string& message) {
    if (id == 0) return;
    WorkerFailure failure;
    failure.code = code.empty() ? "native_error" : code;
    failure.message_key = key;
    failure.message = message;
    {
      std::lock_guard<std::mutex> lock(reply_mutex_);
      const auto found = pending_replies_.find(id);
      if (found == pending_replies_.end() || found->second.completed) return;
      found->second.completed = true;
      found->second.success = false;
      found->second.error_code = failure.code;
      found->second.error_message = failure.message;
      found->second.error_details = ErrorDetails(failure);
    }
    if (!PostMessage(owner_window_, kNativeReplyMessage, static_cast<WPARAM>(id), 0)) {
      HandleReplyPostFailure(id);
    }
  }

  void CompleteError(uint64_t id, const WorkerFailure& failure) {
    CompleteError(id, failure.code, failure.message_key, failure.message);
  }

  void HandleReplyMessage(uint64_t id) {
    PendingReply reply;
    {
      std::lock_guard<std::mutex> lock(reply_mutex_);
      const auto found = pending_replies_.find(id);
      if (found == pending_replies_.end()) return;
      reply = std::move(found->second);
      pending_replies_.erase(found);
    }
    if (!reply.result || !reply.completed) return;
    if (reply.success) {
      reply.result->Success(reply.value);
      if (reply.after_success) reply.after_success();
    } else {
      reply.result->Error(reply.error_code, reply.error_message, reply.error_details);
    }
  }

  void DropPendingReply(uint64_t id) {
    std::lock_guard<std::mutex> lock(reply_mutex_);
    pending_replies_.erase(id);
  }

  bool HasPendingReply(uint64_t id) {
    std::lock_guard<std::mutex> lock(reply_mutex_);
    return pending_replies_.find(id) != pending_replies_.end();
  }

  void MarkReplyDeliveryDeferred(uint64_t id) {
    std::lock_guard<std::mutex> lock(reply_mutex_);
    const auto found = pending_replies_.find(id);
    if (found != pending_replies_.end() && found->second.completed) {
      found->second.delivery_deferred = true;
    }
  }

  void HandleReplyPostFailure(uint64_t id) {
    if (destroying_.load(std::memory_order_acquire) || !IsWindow(owner_window_)) {
      DropPendingReply(id);  // The Flutter engine/window is tearing down.
      return;
    }

    const DWORD owner_thread = GetWindowThreadProcessId(owner_window_, nullptr);
    if (owner_thread == 0) {
      DropPendingReply(id);
      return;
    }
    if (owner_thread == GetCurrentThreadId()) {
      // We are already on the UI thread; drain directly rather than calling
      // Flutter from a background thread or blocking on our own window.
      HandleReplyMessage(id);
      return;
    }

    DWORD_PTR ignored_result = 0;
    const LRESULT delivered = SendMessageTimeoutW(
        owner_window_, kNativeReplyMessage, static_cast<WPARAM>(id), 0,
        SMTO_ABORTIFHUNG | SMTO_BLOCK | SMTO_ERRORONEXIT,
        kNativeReplySendTimeoutMilliseconds, &ignored_result);
    if (delivered != 0 && !HasPendingReply(id)) return;

    if (destroying_.load(std::memory_order_acquire) || !IsWindow(owner_window_)) {
      DropPendingReply(id);  // Teardown owns cancellation of outstanding replies.
      return;
    }
    if (!HasPendingReply(id) ||
        PostMessage(owner_window_, kNativeReplyMessage, static_cast<WPARAM>(id), 0)) {
      return;
    }
    if (destroying_.load(std::memory_order_acquire) || !IsWindow(owner_window_)) {
      DropPendingReply(id);
      return;
    }
    // Keep the completed result owned until the UI receives another window
    // message; HandleWindowMessage drains it on that thread.
    MarkReplyDeliveryDeferred(id);
  }

  void DrainDeferredReplies() {
    std::vector<uint64_t> replies;
    {
      std::lock_guard<std::mutex> lock(reply_mutex_);
      for (auto& item : pending_replies_) {
        if (item.second.completed && item.second.delivery_deferred) {
          item.second.delivery_deferred = false;
          replies.push_back(item.first);
        }
      }
    }
    for (const uint64_t id : replies) HandleReplyMessage(id);
  }

  bool PostEvent(UiEvent event) {
    const uint64_t id = next_message_id_.fetch_add(1, std::memory_order_relaxed);
    {
      std::lock_guard<std::mutex> lock(event_mutex_);
      ui_events_.emplace(id, std::move(event));
    }
    if (!PostMessage(owner_window_, kNativeEventMessage, static_cast<WPARAM>(id), 0)) {
      std::lock_guard<std::mutex> lock(event_mutex_);
      ui_events_.erase(id);
      return false;
    }
    return true;
  }

  void HandleEventMessage(uint64_t id) {
    UiEvent event;
    {
      std::lock_guard<std::mutex> lock(event_mutex_);
      const auto found = ui_events_.find(id);
      if (found == ui_events_.end()) return;
      event = std::move(found->second);
      ui_events_.erase(found);
    }
    switch (event.type) {
      case UiEvent::Type::kMedia:
        if (channel_) channel_->InvokeMethod("mediaEvent",
            std::make_unique<EncodableValue>(StateValue(event.media)));
        break;
      case UiEvent::Type::kWebSession:
        HandleWebSession(event.method_id, event.url);
        break;
      case UiEvent::Type::kCloseReply:
        HandleCloseReply(event.generation, event.accepted, event.not_implemented);
        break;
      case UiEvent::Type::kCloseFallback:
        HandleCloseFallback(event.generation, event.accepted);
        break;
      case UiEvent::Type::kWorkerSessionFailed:
        if (media_drop_) media_drop_->Disable();
        operation_queue_.Post([this, generation = event.generation] {
          if (destroying_.load(std::memory_order_acquire)) return;
          const OwnedWorkerProcessObservation observation = supervisor_.ObserveOwnedProcess();
          if (generation == 0 || observation.generation != generation ||
              (player_leases_.WorkerGeneration() != 0 && player_leases_.WorkerGeneration() != generation)) return;
          media_manager_.DisposeAll();
          // 服务失效仅废弃旧 callback 并释放本地资源；原 Worker live 时仍持账。
          player_leases_.InvalidatePending();
        });
        BeginOwnedProcessObservation(event.generation);
        break;
      case UiEvent::Type::kOwnedProcessObserved:
        StopOwnedProcessObservation(event.generation);
        break;
      case UiEvent::Type::kShutdownWarning:
        BeginShutdownWarning();
        break;
      case UiEvent::Type::kShutdownWarningReply:
        FinishShutdownWarning();
        break;
      case UiEvent::Type::kShutdownFailed:
        if (close_pending_ && !close_needs_dart_confirmation_ &&
            !shutdown_requested_.load(std::memory_order_acquire)) {
          close_pending_ = false;
          window_close_pending_.store(false, std::memory_order_release);
          ++close_generation_;
          KillTimer(owner_window_, kCloseRequestTimer);
        }
        break;
    }
  }

  void PostMediaEvent(const NativeMediaEvent& event) {
    UiEvent ui_event;
    ui_event.type = UiEvent::Type::kMedia;
    ui_event.media = event;
    PostEvent(std::move(ui_event));
  }

  void HandleMethodCall(const MethodCall& call,
                        std::unique_ptr<MethodResult> result) {
    if (!result) return;
    const std::string& method = call.method_name();
    const EncodableValue* arguments = call.arguments();

#ifdef CHASTEADY_WINDOW_DIAGNOSTICS
    if (method == "readWindowDiagnostics") {
      if (!NoArguments(arguments)) {
        result->Error("invalid_arguments", "Window diagnostics accepts no arguments.");
        return;
      }
      flutter::EncodableList rows;
      if (window_chrome_) {
        for (const auto& record : window_chrome_->TakeDiagnostics()) {
          EncodableMap row;
          row.emplace(EncodableValue("sequence"), EncodableValue(static_cast<int64_t>(record.sequence)));
          row.emplace(EncodableValue("tickMs"), EncodableValue(static_cast<int64_t>(record.tick_ms)));
          row.emplace(EncodableValue("geometryGeneration"), EncodableValue(static_cast<int64_t>(record.geometry_generation)));
          row.emplace(EncodableValue("stage"), EncodableValue(record.stage));
          row.emplace(EncodableValue("message"), EncodableValue(static_cast<int64_t>(record.message)));
          row.emplace(EncodableValue("wparam"), EncodableValue(static_cast<int64_t>(record.wparam)));
          row.emplace(EncodableValue("result"), EncodableValue(record.result));
          row.emplace(EncodableValue("maximized"), EncodableValue(record.maximized));
          row.emplace(EncodableValue("customFrameEnabled"), EncodableValue(record.custom_frame_enabled));
          row.emplace(EncodableValue("clientWidth"), EncodableValue(static_cast<int64_t>(record.client_width)));
          row.emplace(EncodableValue("clientHeight"), EncodableValue(static_cast<int64_t>(record.client_height)));
          row.emplace(EncodableValue("dpi"), EncodableValue(static_cast<int64_t>(record.dpi)));
          rows.emplace_back(std::move(row));
        }
      }
      result->Success(EncodableValue(std::move(rows)));
      return;
    }
#endif

    // Owned-window control is deliberately independent of bootstrap, media,
    // worker capabilities, and the serialized worker operation queue.
    if (method == "getWindowState" || method == "minimizeWindow" ||
        method == "toggleMaximizeWindow" || method == "startWindowDrag") {
      if (!NoArguments(arguments)) {
        result->Error("invalid_arguments", "This window method accepts no arguments.");
        return;
      }
      if (method == "getWindowState") {
        result->Success(WindowStateValue(window_chrome_ ?
            window_chrome_->GetState() : WindowChrome::State{}));
        return;
      }
      std::string error;
      bool succeeded = false;
      if (window_chrome_) {
        if (method == "minimizeWindow") {
          succeeded = window_chrome_->Minimize(&error);
        } else if (method == "toggleMaximizeWindow") {
          succeeded = window_chrome_->ToggleMaximize(&error);
        } else {
          succeeded = window_chrome_->StartDrag(&error);
        }
      }
      if (!succeeded) {
        result->Error(error.empty() ? "window_unavailable" : error,
                      "The owned desktop window could not perform the command.");
      } else {
        result->Success();
      }
      return;
    }
    if (method == "setAlwaysOnTop") {
      const EncodableMap* map = nullptr;
      bool value = false;
      if (!IsMap(arguments, &map) || !HasExactKeys(*map, {"value"}) ||
          !GetBoolean(FindValue(map, "value"), &value)) {
        result->Error("invalid_arguments", "setAlwaysOnTop requires only a boolean value.");
        return;
      }
      std::string error;
      if (!window_chrome_ || !window_chrome_->SetAlwaysOnTop(value, &error)) {
        result->Error(error.empty() ? "window_unavailable" : error,
                      "The owned desktop window could not change its topmost state.");
      } else {
        result->Success();
      }
      return;
    }
    if (method == "configureWindowChrome") {
      const EncodableMap* map = nullptr;
      const EncodableMap* maximize = nullptr;
      WindowChrome::Geometry geometry;
      bool enabled = false;
      bool valid = IsMap(arguments, &map) &&
          GetBoolean(FindValue(map, "enabled"), &enabled);
      if (valid && enabled) {
        valid = HasExactKeys(*map, {"enabled", "titleBarHeight", "controlsLeft",
                                   "clientWidth", "maximizeButton"}) &&
            GetFiniteNumber(FindValue(map, "titleBarHeight"), &geometry.title_bar_height) &&
            GetFiniteNumber(FindValue(map, "controlsLeft"), &geometry.controls_left) &&
            GetFiniteNumber(FindValue(map, "clientWidth"), &geometry.client_width) &&
            IsMap(FindValue(map, "maximizeButton"), &maximize) &&
            HasExactKeys(*maximize, {"left", "top", "width", "height"}) &&
            GetFiniteNumber(FindValue(maximize, "left"), &geometry.maximize_left) &&
            GetFiniteNumber(FindValue(maximize, "top"), &geometry.maximize_top) &&
            GetFiniteNumber(FindValue(maximize, "width"), &geometry.maximize_width) &&
            GetFiniteNumber(FindValue(maximize, "height"), &geometry.maximize_height) &&
            WindowChrome::IsValidGeometry(geometry);
      } else if (valid) {
        valid = HasExactKeys(*map, {"enabled"});
      }
      if (!valid) {
        // Fail closed even on malformed updates: Dart can remove its custom
        // controls without leaving an old native caption-less layout active.
        std::string ignored;
        if (window_chrome_) window_chrome_->Configure(false, {}, &ignored);
        result->Error("invalid_arguments", "Window chrome requires the finite, bounded layout schema.");
        return;
      }
      if (enabled && !bootstrap_ready_.load(std::memory_order_acquire)) {
        result->Error("window_chrome_not_ready", "Enable custom chrome only after the normal AppShell layout.");
        return;
      }
      std::string error;
      if (!window_chrome_ || !window_chrome_->Configure(enabled, geometry, &error)) {
        result->Error(error.empty() ? "window_chrome_unavailable" : error,
                      "The owned desktop window could not configure its frame; use the stock caption.");
      } else {
        result->Success(WindowStateValue(window_chrome_->GetState()));
      }
      return;
    }

    if (method == "configureMediaDrop") {
      const EncodableMap* map = nullptr;
      const EncodableMap* rect = nullptr;
      MediaDropTarget::Configuration configuration;
      bool enabled = false;
      bool valid = IsMap(arguments, &map) && GetBoolean(FindValue(map, "enabled"), &enabled);
      if (valid && enabled) {
        valid = HasExactKeys(*map, {"enabled", "targetId", "generation", "rect", "clientWidth"}) &&
            GetString(FindValue(map, "targetId"), &configuration.target_id) &&
            GetPositiveGeneration(FindValue(map, "generation"), &configuration.generation) &&
            GetFiniteNumber(FindValue(map, "clientWidth"), &configuration.client_width) &&
            IsMap(FindValue(map, "rect"), &rect) && HasExactKeys(*rect, {"left", "top", "right", "bottom"}) &&
            GetFiniteNumber(FindValue(rect, "left"), &configuration.left) &&
            GetFiniteNumber(FindValue(rect, "top"), &configuration.top) &&
            GetFiniteNumber(FindValue(rect, "right"), &configuration.right) &&
            GetFiniteNumber(FindValue(rect, "bottom"), &configuration.bottom) &&
            MediaDropTarget::IsValidConfiguration(configuration);
      } else if (valid) {
        valid = HasExactKeys(*map, {"enabled"});
      }
      if (!valid) {
        if (media_drop_) media_drop_->Disable();
        result->Error("media_drop_invalid_config", "Media drop requires a finite, bounded target configuration.");
        return;
      }
      std::string error;
      if (!media_drop_ || !media_drop_->Configure(enabled, configuration, &error)) {
        result->Error(error.empty() ? "media_drop_unavailable" : error,
                      "The owned media drop target is unavailable or its layout is stale.");
      } else {
        result->Success();
      }
      return;
    }

    if (method == "bootstrap") {
      if (!NoArguments(arguments)) {
        CompleteMethodError(std::move(result), "invalid_arguments", "nativeProtocol.error.invalidRequest",
                      "bootstrap does not accept arguments.");
        return;
      }
      const uint64_t reply_id = StoreReply(std::move(result));
      const std::shared_ptr<CallbackGate> gate = gate_;
      supervisor_.StartAsync([this, gate, reply_id](bool ok, WorkerReady ready,
                                                    WorkerFailure failure) mutable {
        GateLease lease(gate);
        if (!lease) return;
        if (!ok) {
          CompleteError(reply_id, failure);
          return;
        }
        {
          std::lock_guard<std::mutex> lock(session_mutex_);
          session_ready_ = ready;
        }
        bootstrap_ready_.store(true, std::memory_order_release);
        if (closing_before_bootstrap_.load(std::memory_order_acquire)) {
          CompleteError(reply_id, "worker_shutting_down", "nativeWorker.error.stopping",
                        "The private worker is shutting down.");
          return;
        }
        EncodableMap response;
        response.emplace(EncodableValue("origin"), EncodableValue(ready.origin));
        response.emplace(EncodableValue("bearer"), EncodableValue(ready.bearer));
        CompleteSuccess(reply_id, EncodableValue(std::move(response)));
      });
      return;
    }

    if (method == "pickFile") {
      const EncodableMap* map = nullptr;
      std::string kind;
      if (!IsMap(arguments, &map) || !HasExactKeys(*map, {"kind"}) ||
          !GetString(FindValue(map, "kind"), &kind) ||
          (kind != "video" && kind != "project" && kind != "folder" && kind != "executable")) {
        CompleteMethodError(std::move(result), "invalid_picker_kind", "nativePicker.error.invalidKind",
                      "The requested local picker type is not supported.");
        return;
      }
      const FileDialogResult picked = ShowNativePicker(owner_window_, kind);
      if (picked.cancelled) {
        result->Success();
      } else if (!picked.error_code.empty()) {
        CompleteMethodError(std::move(result), picked.error_code, "nativePicker.error.failed",
                      "The local file picker could not complete.");
      } else {
        result->Success(EncodableValue(picked.path));
      }
      return;
    }

    if (method == "openWeb") {
      if (!NoArguments(arguments)) {
        CompleteMethodError(std::move(result), "invalid_arguments", "nativeProtocol.error.invalidRequest",
                      "openWeb does not accept arguments.");
        return;
      }
      const uint64_t reply_id = StoreReply(std::move(result));
      const std::shared_ptr<CallbackGate> gate = gate_;
      supervisor_.GetWebSession([this, gate, reply_id](WorkerReply reply) mutable {
        GateLease lease(gate);
        if (!lease) return;
        if (!reply.ok) {
          CompleteError(reply_id, reply.failure);
          return;
        }
        UiEvent event;
        event.type = UiEvent::Type::kWebSession;
        event.method_id = reply_id;
        event.url = std::move(reply.url);
        PostEvent(std::move(event));
      });
      return;
    }

    if (method == "createPreview") {
      const EncodableMap* map = nullptr;
      std::string artifact_id;
      if (!IsMap(arguments, &map) || !HasExactKeys(*map, {"artifact_id"}) ||
          !GetString(FindValue(map, "artifact_id"), &artifact_id) ||
          !IsCanonicalUuid(artifact_id)) {
        CompleteMethodError(std::move(result), "invalid_native_artifact", "nativeMedia.error.invalidArtifact",
                      "The requested preview artifact is invalid.");
        return;
      }
      artifact_id = LowercaseUuid(std::move(artifact_id));
      const uint64_t reply_id = StoreReply(std::move(result));
      const std::shared_ptr<CallbackGate> gate = gate_;
      supervisor_.AcquireMedia(artifact_id, [this, gate, reply_id](WorkerReply reply) mutable {
        GateLease lease(gate);
        if (!lease) return;
        if (!reply.ok) {
          CompleteError(reply_id, reply.failure);
          return;
        }
        if (shutdown_in_progress_.load(std::memory_order_acquire)) {
          supervisor_.ReleaseMedia(reply.lease_id, [](WorkerReply) {});
          CompleteError(reply_id, "worker_shutting_down", "nativeWorker.error.stopping",
                        "The private worker is shutting down.");
          return;
        }
        auto acquired = std::make_shared<WorkerReply>(std::move(reply));
        if (!operation_queue_.Post([this, gate, reply_id, acquired]() mutable {
              GateLease operation_lease(gate);
              if (!operation_lease) return;
              CreatePreview(reply_id, std::move(*acquired));
            })) {
          supervisor_.ReleaseMedia(acquired->lease_id, [](WorkerReply) {});
          CompleteError(reply_id, "native_media_unavailable", "nativeMedia.error.unavailable",
                        "The native media service is unavailable.");
        }
      });
      return;
    }

    if (method == "play" || method == "pause" || method == "seek" ||
        method == "volume" || method == "muted" || method == "playerState" ||
        method == "disposePreview") {
      HandlePlayerMethod(method, arguments, std::move(result));
      return;
    }

    if (method == "requestShutdown") {
      if (!NoArguments(arguments)) {
        CompleteMethodError(std::move(result), "invalid_arguments", "nativeProtocol.error.invalidRequest",
                      "requestShutdown does not accept arguments.");
        return;
      }
      const uint64_t reply_id = StoreReply(std::move(result));
      if (media_drop_) media_drop_->Disable();
      bool start_shutdown = false;
      bool already_terminal = false;
      bool merged_terminal_waiter = false;
      {
        std::lock_guard<std::mutex> lock(shutdown_mutex_);
        if (shutdown_terminal_ready_ && shutdown_terminal_success_) {
          if (shutdown_result_delivered_.load(std::memory_order_acquire)) {
            already_terminal = true;
          } else {
            shutdown_reply_ids_.push_back(reply_id);
            merged_terminal_waiter = true;
          }
        } else {
          shutdown_reply_ids_.push_back(reply_id);
          if (!shutdown_started_) {
            shutdown_started_ = true;
            shutdown_in_progress_.store(true, std::memory_order_release);
            start_shutdown = true;
          }
        }
      }
      if (already_terminal) {
        CompleteSuccess(reply_id);
        return;
      }
      if (merged_terminal_waiter || !start_shutdown) return;  // Share the pending shutdown response.
      if (!operation_queue_.Post([this] {
            player_leases_.InvalidatePending();
            media_manager_.DisposeAll();
            for (const auto& player : player_leases_.Snapshot()) {
              supervisor_.ReleaseMedia(player.lease_id, [](WorkerReply) {});
            }
            // shutdown 被拒绝时仍保留原映射；成功 callback 也须另核原始对象终态。
            const uint64_t worker_generation = supervisor_.ObserveOwnedProcess().generation;
            const std::shared_ptr<CallbackGate> gate = gate_;
            supervisor_.RequestShutdown([this, gate, worker_generation](WorkerReply reply) mutable {
              GateLease lease(gate);
              if (!lease) return;
              if (!reply.ok || !reply.shutting_down) {
                WorkerFailure failure = reply.failure;
                if (failure.code.empty()) failure.code = "worker_shutdown_failed";
                if (failure.message_key.empty()) failure.message_key = "nativeWorker.error.stopped";
                if (failure.message.empty()) failure.message = "The private worker did not shut down.";
                FailShutdown(std::move(failure));
                return;
              }
              const bool timed_out = reply.shutdown_timed_out;
              if (!operation_queue_.Post([this, timed_out, worker_generation] {
                    if (destroying_.load(std::memory_order_acquire)) return;
                    if (!ConfirmTerminalPreviewWorker(worker_generation)) {
                      WorkerFailure failure;
                      failure.code = "worker_cleanup_unconfirmed";
                      failure.message_key = "nativeWorker.error.exited";
                      failure.message = "The original owned worker process has not reached a confirmed terminal state.";
                      FailShutdown(std::move(failure));
                      return;
                    }
                    shutdown_requested_.store(true, std::memory_order_release);
                    if (timed_out) {
                      UiEvent warning;
                      warning.type = UiEvent::Type::kShutdownWarning;
                      if (!PostEvent(std::move(warning))) {
                        WorkerFailure warning_failure;
                        warning_failure.code = "shutdown_warning_delivery_failed";
                        warning_failure.message_key = "nativeWorker.error.timeout";
                        warning_failure.message = "The forced-shutdown warning could not be delivered.";
                        FailShutdown(std::move(warning_failure));
                      }
                    } else {
                      CompleteShutdownWaiters();
                    }
                  })) {
                WorkerFailure failure;
                failure.code = "native_worker_stopped";
                failure.message_key = "nativeWorker.error.stopped";
                failure.message = "The terminal worker result could not reach the native operation queue.";
                FailShutdown(std::move(failure));
              }
            });
          })) {
        WorkerFailure failure;
        failure.code = "native_worker_stopped";
        failure.message_key = "nativeWorker.error.stopped";
        failure.message = "The private worker is stopping.";
        FailShutdown(std::move(failure));
      }
      return;
    }

    result->NotImplemented();
  }

  // 调用者与账本完成处理都在 operation_queue；Supervisor callback 只转交不可变结果。
  void ReleaseTrackedPreviewLease(const PreviewLeaseBookkeeping::ReleaseToken& token,
                                  uint64_t reply_id) {
    const std::shared_ptr<CallbackGate> gate = gate_;
    supervisor_.ReleaseMedia(token.lease_id,
        [this, gate, token, reply_id](WorkerReply released) mutable {
          GateLease gate_lease(gate);
          if (!gate_lease) return;
          auto outcome = std::make_shared<WorkerReply>(std::move(released));
          if (!operation_queue_.Post([this, token, reply_id, outcome] {
                if (destroying_.load(std::memory_order_acquire)) return;
                // 协议 1 的 ok:true/released:false 是 Worker 确认已不存在，亦可幂等收账。
                const auto confirmation = player_leases_.ConfirmRelease(token, outcome->ok);
                if (reply_id == 0) return;
                if (!outcome->ok) {
                  CompleteError(reply_id, outcome->failure);
                } else if (confirmation == PreviewLeaseBookkeeping::Confirmation::kStale) {
                  CompleteError(reply_id, "player_dispose_stale", "nativeMedia.error.leaseUnavailable",
                                "The preview release belongs to an obsolete lifetime.");
                } else {
                  CompleteSuccess(reply_id);
                }
              }) && reply_id != 0 && !destroying_.load(std::memory_order_acquire)) {
            CompleteError(reply_id, "native_media_unavailable", "nativeMedia.error.unavailable",
                          "The native media service is unavailable.");
          }
        });
  }

  void HandlePlayerMethod(const std::string& method,
                          const EncodableValue* arguments,
                          std::unique_ptr<MethodResult> result) {
    if (shutdown_in_progress_.load(std::memory_order_acquire)) {
      CompleteMethodError(std::move(result), "worker_shutting_down", "nativeWorker.error.stopping",
                    "The private worker is shutting down.");
      return;
    }
    const EncodableMap* map = nullptr;
    if (!IsMap(arguments, &map)) {
      CompleteMethodError(std::move(result), "invalid_player_arguments", "nativeMedia.error.invalidPlayer",
                    "A native player identifier is required.");
      return;
    }
    std::string player_id;
    if (!GetString(FindValue(map, "player_id"), &player_id) || player_id.empty()) {
      CompleteMethodError(std::move(result), "invalid_player_arguments", "nativeMedia.error.invalidPlayer",
                    "A native player identifier is required.");
      return;
    }

    double number = 0.0;
    bool boolean = false;
    if (method == "seek") {
      if (!HasExactKeys(*map, {"player_id", "position_seconds"}) ||
          !GetFiniteNumber(FindValue(map, "position_seconds"), &number) || number < 0.0) {
        CompleteMethodError(std::move(result), "invalid_seek_position", "nativeMedia.error.invalidPosition",
                      "The seek position is invalid.");
        return;
      }
    } else if (method == "volume") {
      if (!HasExactKeys(*map, {"player_id", "volume"}) ||
          !GetFiniteNumber(FindValue(map, "volume"), &number) || number < 0.0 || number > 1.0) {
        CompleteMethodError(std::move(result), "invalid_volume", "nativeMedia.error.invalidVolume",
                      "The player volume must be between zero and one.");
        return;
      }
    } else if (method == "muted") {
      if (!HasExactKeys(*map, {"player_id", "muted"}) ||
          !GetBoolean(FindValue(map, "muted"), &boolean)) {
        CompleteMethodError(std::move(result), "invalid_muted_value", "nativeMedia.error.invalidMuted",
                      "The player muted state is invalid.");
        return;
      }
    } else if (!HasExactKeys(*map, {"player_id"})) {
      CompleteMethodError(std::move(result), "invalid_player_arguments", "nativeMedia.error.invalidPlayer",
                    "The player request contains unsupported fields.");
      return;
    }

    const uint64_t reply_id = StoreReply(std::move(result));
    if (!operation_queue_.Post([this, method, player_id, number, boolean, reply_id] {
          if (worker_session_failed_.load(std::memory_order_acquire) && method != "disposePreview") {
            CompleteError(reply_id, "worker_exited", "nativeWorker.error.exited",
                          "The private worker is no longer available.");
            return;
          }
          if (method == "playerState") {
            NativeMediaEvent state;
            std::string error;
            if (!media_manager_.State(player_id, &state, &error)) {
              CompleteError(reply_id, error.empty() ? "player_not_found" : error,
                            "nativeMedia.error.playerNotFound",
                            "The native player is no longer available.");
              return;
            }
            CompleteSuccess(reply_id, StateValue(state));
            return;
          }
          if (method == "disposePreview") {
            std::string error;
            const auto lease = player_leases_.Find(player_id);
            const bool disposed = (lease && lease->locally_disposed) ||
                media_manager_.Dispose(player_id, &error);
            if (!disposed) {
              // 本地资源仍活跃时不释放 Worker lease，也不忘记可重试映射。
              CompleteError(reply_id, error.empty() ? "player_dispose_failed" : error,
                            "nativeMedia.error.disposeFailed",
                            "The native player could not be disposed.");
              return;
            }
            if (!lease) {
              CompleteSuccess(reply_id);
              return;
            }
            player_leases_.MarkLocallyDisposed(player_id);
            const auto token = player_leases_.PrepareRelease(player_id);
            if (!token) {
              CompleteError(reply_id, "native_media_unavailable", "nativeMedia.error.leaseUnavailable",
                            "The preview lease could not be prepared for release.");
              return;
            }
            // queue-full/请求失败保留该 lease；即使 player 已幂等 Dispose，retry 仍发送原 lease。
            ReleaseTrackedPreviewLease(*token, reply_id);
            return;
          }
          std::string error;
          bool ok = false;
          if (method == "play") ok = media_manager_.Play(player_id, &error);
          else if (method == "pause") ok = media_manager_.Pause(player_id, &error);
          else if (method == "seek") ok = media_manager_.Seek(player_id, number, &error);
          else if (method == "volume") ok = media_manager_.SetVolume(player_id, number, &error);
          else if (method == "muted") ok = media_manager_.SetMuted(player_id, boolean, &error);
          if (ok) CompleteSuccess(reply_id);
          else CompleteError(reply_id, error.empty() ? "native_media_action_failed" : error,
                             "nativeMedia.error.playerAction",
                             "The native media command could not be completed.");
        })) {
      CompleteError(reply_id, "native_media_unavailable", "nativeMedia.error.unavailable",
                    "The native media service is unavailable.");
    }
  }

  void CreatePreview(uint64_t reply_id, WorkerReply acquired) {
    if (shutdown_in_progress_.load(std::memory_order_acquire)) {
      if (!acquired.lease_id.empty()) supervisor_.ReleaseMedia(acquired.lease_id, [](WorkerReply) {});
      CompleteError(reply_id, "worker_shutting_down", "nativeWorker.error.stopping",
                    "The private worker is shutting down.");
      return;
    }
    if (!acquired.owned_read_handle || acquired.lease_id.empty()) {
      if (!acquired.lease_id.empty()) supervisor_.ReleaseMedia(acquired.lease_id, [](WorkerReply) {});
      CompleteError(reply_id, "media_handle_missing", "nativeMedia.error.leaseUnavailable",
                    "A validated preview handle was not returned.");
      return;
    }
    const OwnedWorkerProcessObservation observation = supervisor_.ObserveOwnedProcess();
    if (!bootstrap_ready_.load(std::memory_order_acquire) ||
        worker_session_failed_.load(std::memory_order_acquire) || destroying_.load(std::memory_order_acquire) ||
        !supervisor_.IsReady() || !observation.IsVerifiedLive() || !player_leases_.BindWorker(observation)) {
      supervisor_.ReleaseMedia(acquired.lease_id, [](WorkerReply) {});
      CompleteError(reply_id, "worker_not_ready", "nativeWorker.error.notReady",
                    "The owned private worker is not ready for a preview.");
      return;
    }
    const std::string lease_id = acquired.lease_id;
    NativeMediaCreateResult created = media_manager_.Create(
        acquired.owned_read_handle.release(), acquired.width, acquired.height);
    if (!created.ok()) {
      supervisor_.ReleaseMedia(lease_id, [](WorkerReply) {});
      CompleteError(reply_id, created.error_code.empty() ? "native_media_create_failed" : created.error_code,
                    "nativeMedia.error.unavailable",
                    "The native preview player could not be created.");
      return;
    }
    if (!player_leases_.Track(created.player_id, lease_id)) {
      // 内部 player UUID 不应重复；不覆盖已有 lease 账本，也不释放仍活跃的本地资源。
      if (media_manager_.Dispose(created.player_id, nullptr)) {
        supervisor_.ReleaseMedia(lease_id, [](WorkerReply) {});
      }
      CompleteError(reply_id, "native_media_unavailable", "nativeMedia.error.unavailable",
                    "The native preview identifier could not be tracked.");
      return;
    }
    NativeMediaEvent state;
    std::string state_error;
    if (!media_manager_.State(created.player_id, &state, &state_error)) {
      if (media_manager_.Dispose(created.player_id, nullptr)) {
        player_leases_.MarkLocallyDisposed(created.player_id);
        const auto token = player_leases_.PrepareRelease(created.player_id);
        if (token) ReleaseTrackedPreviewLease(*token, 0);
      }
      CompleteError(reply_id, state_error.empty() ? "player_state_unavailable" : state_error,
                    "nativeMedia.error.unavailable",
                    "The native preview state could not be read.");
      return;
    }
    EncodableMap response;
    response.emplace(EncodableValue("player_id"), EncodableValue(created.player_id));
    response.emplace(EncodableValue("texture_id"), EncodableValue(created.texture_id));
    response.emplace(EncodableValue("width"), EncodableValue(acquired.width));
    response.emplace(EncodableValue("height"), EncodableValue(acquired.height));
    response.emplace(EncodableValue("state"), StateValue(state));
    CompleteSuccess(reply_id, EncodableValue(std::move(response)));
  }

  void HandleWebSession(uint64_t reply_id, const std::string& url) {
    WorkerReady ready;
    {
      std::lock_guard<std::mutex> lock(session_mutex_);
      ready = session_ready_;
    }
    const std::string expected = ready.origin + "/#session=" + ready.bearer;
    if (ready.origin.empty() || ready.bearer.empty() || url != expected) {
      CompleteError(reply_id, "invalid_web_session", "nativeWeb.error.invalidSession",
                    "The worker returned an invalid local web session.");
      return;
    }
    const std::wstring wide_url = Utf8ToWide(url);
    if (wide_url.empty()) {
      CompleteError(reply_id, "invalid_web_session", "nativeWeb.error.invalidSession",
                    "The worker returned an invalid local web session.");
      return;
    }
    const INT_PTR launched = reinterpret_cast<INT_PTR>(ShellExecuteW(
        owner_window_, L"open", wide_url.c_str(), nullptr, nullptr, SW_SHOWNORMAL));
    if (launched <= 32) {
      CompleteError(reply_id, "web_open_failed", "nativeWeb.error.openFailed",
                    "The local web session could not be opened.");
      return;
    }
    CompleteSuccess(reply_id);
  }

  void HandleCloseReply(uint64_t generation, bool accepted, bool not_implemented) {
    if (!close_pending_ || generation != close_generation_) return;
    if (!accepted) {
      if (not_implemented || !bootstrap_ready_.load(std::memory_order_acquire)) {
        ShutdownForClose(generation);
        return;
      }
      close_pending_ = false;
      window_close_pending_.store(false, std::memory_order_release);
      close_needs_dart_confirmation_ = false;
      KillTimer(owner_window_, kCloseRequestTimer);
      return;
    }
    if (shutdown_requested_.load(std::memory_order_acquire)) {
      CommitClose(generation);
      return;
    }
    // A true close response is accepted only after shutdown was requested. If
    // an older adapter did not request it itself, do the owned orderly shutdown
    // here rather than allowing the window to orphan the worker.
    ShutdownForClose(generation);
  }

  void ShutdownForClose(uint64_t generation) {
    closing_before_bootstrap_.store(true, std::memory_order_release);
    shutdown_in_progress_.store(true, std::memory_order_release);
    if (!operation_queue_.Post([this, generation] {
          player_leases_.InvalidatePending();
          media_manager_.DisposeAll();
          for (const auto& player : player_leases_.Snapshot()) {
            supervisor_.ReleaseMedia(player.lease_id, [](WorkerReply) {});
          }
          const uint64_t worker_generation = supervisor_.ObserveOwnedProcess().generation;
          const std::shared_ptr<CallbackGate> gate = gate_;
          supervisor_.RequestShutdown([this, gate, generation, worker_generation](WorkerReply reply) mutable {
            GateLease lease(gate);
            if (!lease) return;
            const bool accepted = reply.ok && reply.shutting_down;
            if (!operation_queue_.Post([this, generation, worker_generation, accepted] {
                  if (destroying_.load(std::memory_order_acquire)) return;
                  const bool confirmed = accepted && ConfirmTerminalPreviewWorker(worker_generation);
                  if (confirmed) shutdown_requested_.store(true, std::memory_order_release);
                  UiEvent event;
                  event.type = UiEvent::Type::kCloseFallback;
                  event.generation = generation;
                  event.accepted = confirmed;
                  PostEvent(std::move(event));
                })) {
              UiEvent event;
              event.type = UiEvent::Type::kCloseFallback;
              event.generation = generation;
              event.accepted = false;
              PostEvent(std::move(event));
            }
          });
        })) {
      HandleCloseFallback(generation, false);
    }
  }

  void CompleteShutdownWaiters() {
    std::vector<uint64_t> replies;
    {
      std::lock_guard<std::mutex> lock(shutdown_mutex_);
      if (shutdown_terminal_ready_) return;
      shutdown_terminal_ready_ = true;
      shutdown_terminal_success_ = true;
      replies.swap(shutdown_reply_ids_);
    }
    CompleteShutdownReplyBatch(std::move(replies));
  }

  void CompleteShutdownReplyBatch(std::vector<uint64_t> replies) {
    if (replies.empty()) return;
    const std::shared_ptr<CallbackGate> gate = gate_;
    for (size_t index = 0; index < replies.size(); ++index) {
      const uint64_t reply_id = replies[index];
      if (index + 1 != replies.size()) {
        CompleteSuccess(reply_id);
        continue;
      }
      CompleteSuccess(reply_id, EncodableValue(), [this, gate] {
        GateLease completion_lease(gate);
        if (!completion_lease) return;
        std::vector<uint64_t> additional_replies;
        {
          std::lock_guard<std::mutex> lock(shutdown_mutex_);
          additional_replies.swap(shutdown_reply_ids_);
          if (additional_replies.empty()) {
            shutdown_result_delivered_.store(true, std::memory_order_release);
          }
        }
        if (!additional_replies.empty()) {
          CompleteShutdownReplyBatch(std::move(additional_replies));
          return;
        }
        // A system WM_CLOSE is still waiting for the Dart requestClose response.
        // File-menu close has no such pending callback, so close only after all
        // merged MethodChannel shutdown results have been sent.
        if (close_pending_ && !close_needs_dart_confirmation_) {
          CommitClose(close_generation_);
        } else if (!window_close_pending_.load(std::memory_order_acquire)) {
          PostMessage(owner_window_, WM_CLOSE, 0, 0);
        }
      });
    }
  }

  void FailShutdown(WorkerFailure failure) {
    std::vector<uint64_t> replies;
    {
      std::lock_guard<std::mutex> lock(shutdown_mutex_);
      replies.swap(shutdown_reply_ids_);
      shutdown_started_ = false;
      shutdown_terminal_ready_ = false;
      shutdown_terminal_success_ = false;
      shutdown_in_progress_.store(false, std::memory_order_release);
      shutdown_requested_.store(false, std::memory_order_release);
      shutdown_result_delivered_.store(false, std::memory_order_release);
    }
    for (const uint64_t reply_id : replies) CompleteError(reply_id, failure);
    UiEvent event;
    event.type = UiEvent::Type::kShutdownFailed;
    PostEvent(std::move(event));
  }

  void BeginShutdownWarning() {
    if (shutdown_warning_pending_) return;
    if (!channel_) {
      FinishShutdownWarning();
      return;
    }
    shutdown_warning_pending_ = true;
    if (SetTimer(owner_window_, kShutdownWarningTimer,
                 kShutdownWarningTimeoutMilliseconds, nullptr) == 0) {
      shutdown_warning_pending_ = false;
      WorkerFailure failure;
      failure.code = "shutdown_warning_timer_unavailable";
      failure.message_key = "nativeWorker.error.timeout";
      failure.message = "A bounded forced-shutdown warning could not be scheduled.";
      FailShutdown(std::move(failure));
      return;
    }

    EncodableMap arguments;
    arguments.emplace(EncodableValue("message_key"),
                      EncodableValue("nativeWorker.error.timeout"));
    arguments.emplace(EncodableValue("args"), EncodableValue(EncodableMap{}));
    const std::shared_ptr<CallbackGate> gate = gate_;
    auto callback = std::make_unique<CallbackMethodResult<
        std::function<void(bool, const EncodableValue*, bool)>>>(
        [this, gate](bool, const EncodableValue*, bool) {
          GateLease lease(gate);
          if (!lease) return;
          UiEvent event;
          event.type = UiEvent::Type::kShutdownWarningReply;
          PostEvent(std::move(event));
        });
    channel_->InvokeMethod("shutdownWarning",
        std::make_unique<EncodableValue>(EncodableValue(std::move(arguments))),
        std::move(callback));
  }

  void FinishShutdownWarning() {
    if (!shutdown_warning_pending_) return;
    shutdown_warning_pending_ = false;
    KillTimer(owner_window_, kShutdownWarningTimer);
    CompleteShutdownWaiters();
  }

  void HandleCloseFallback(uint64_t generation, bool accepted) {
    if (!close_pending_ || generation != close_generation_) return;
    if (accepted && shutdown_requested_.load(std::memory_order_acquire)) {
      CommitClose(generation);
      return;
    }
    close_pending_ = false;
    window_close_pending_.store(false, std::memory_order_release);
    close_needs_dart_confirmation_ = false;
    shutdown_in_progress_.store(false, std::memory_order_release);
    KillTimer(owner_window_, kCloseRequestTimer);
  }

  void CommitClose(uint64_t generation) {
    if (!close_pending_ || generation != close_generation_ ||
        !shutdown_requested_.load(std::memory_order_acquire)) return;
    close_pending_ = false;
    window_close_pending_.store(false, std::memory_order_release);
    close_needs_dart_confirmation_ = false;
    close_committed_ = true;
    KillTimer(owner_window_, kCloseRequestTimer);
    PostMessage(owner_window_, WM_CLOSE, 0, 0);
  }

  HWND owner_window_ = nullptr;
  std::shared_ptr<CallbackGate> gate_;
  WorkerSupervisor supervisor_;
  NativeMediaManager media_manager_;
  std::unique_ptr<MethodChannel> channel_;
  std::unique_ptr<WindowChrome> window_chrome_;  // Platform thread only.
  std::unique_ptr<MediaDropTarget> media_drop_;  // 仅平台线程。
  TaskQueue operation_queue_;

  std::mutex session_mutex_;
  WorkerReady session_ready_;
  std::mutex shutdown_mutex_;
  std::vector<uint64_t> shutdown_reply_ids_;
  bool shutdown_started_ = false;
  bool shutdown_terminal_ready_ = false;
  bool shutdown_terminal_success_ = false;
  std::atomic<bool> bootstrap_ready_{false};
  std::atomic<bool> closing_before_bootstrap_{false};
  std::atomic<bool> shutdown_in_progress_{false};
  std::atomic<bool> shutdown_requested_{false};
  std::atomic<bool> shutdown_result_delivered_{false};
  std::atomic<bool> worker_session_failed_{false};
  std::atomic<bool> window_close_pending_{false};
  std::atomic<bool> destroying_{false};

  std::mutex reply_mutex_;
  std::unordered_map<uint64_t, PendingReply> pending_replies_;
  std::mutex event_mutex_;
  std::unordered_map<uint64_t, UiEvent> ui_events_;
  std::atomic<uint64_t> next_message_id_{1};

  bool close_pending_ = false;
  bool close_committed_ = false;
  bool close_needs_dart_confirmation_ = false;
  bool shutdown_warning_pending_ = false;
  uint64_t close_generation_ = 0;
  PreviewLeaseBookkeeping player_leases_;  // 仅原串行 operation_queue 访问。
  std::atomic<uint64_t> terminal_observer_generation_{0};
  std::atomic<bool> terminal_observer_active_{false};
  std::atomic<bool> terminal_observer_poll_pending_{false};
  bool terminal_observer_timer_armed_ = false;  // 仅平台线程。
  ULONGLONG terminal_observer_retry_tick_ = 0;  // 仅平台线程。
};

NativeBridge::NativeBridge(HWND owner_window,
                           HWND flutter_child,
                           flutter::BinaryMessenger* messenger,
                           flutter::TextureRegistrar* texture_registrar,
                           std::shared_ptr<const NativeLaunchConfiguration> launch_configuration)
    : impl_(std::make_unique<Impl>(owner_window, flutter_child, messenger,
                                   texture_registrar, std::move(launch_configuration))) {}
NativeBridge::~NativeBridge() = default;

bool NativeBridge::HandleWindowMessage(HWND window, UINT message, WPARAM wparam,
                                       LPARAM lparam, LRESULT* result) {
  return impl_ && impl_->HandleWindowMessage(window, message, wparam, lparam, result);
}

bool NativeBridge::CloseRequest() {
  return impl_ && impl_->CloseRequest();
}

}  // namespace chasteady
