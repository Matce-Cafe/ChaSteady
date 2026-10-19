#ifndef CHASTEADY_UI_WINDOWS_RUNNER_WORKER_SUPERVISOR_H_
#define CHASTEADY_UI_WINDOWS_RUNNER_WORKER_SUPERVISOR_H_

#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>

#include <cstdint>
#include <functional>
#include <memory>
#include <string>

namespace chasteady {

class NativeLaunchConfiguration;
struct OwnedWorkerProcessObservation;

// An owned kernel handle. Move it into NativeMediaManager::Create to transfer
// the duplicated worker lease for the full playback lifetime.
class OwnedWorkerHandle final {
 public:
  explicit OwnedWorkerHandle(HANDLE handle = INVALID_HANDLE_VALUE) noexcept;
  ~OwnedWorkerHandle();

  OwnedWorkerHandle(const OwnedWorkerHandle&) = delete;
  OwnedWorkerHandle& operator=(const OwnedWorkerHandle&) = delete;
  OwnedWorkerHandle(OwnedWorkerHandle&& other) noexcept;
  OwnedWorkerHandle& operator=(OwnedWorkerHandle&& other) noexcept;

  HANDLE get() const noexcept;
  HANDLE release() noexcept;
  explicit operator bool() const noexcept;

 private:
  HANDLE handle_;
};

struct WorkerReady final {
  // The capability is intentionally never present in this public bootstrap
  // value; it remains private to WorkerSupervisor and is attached to stdio
  // protocol requests internally.
  std::string origin;
  std::string bearer;
};

struct WorkerFailure final {
  std::string code;
  std::string message_key;
  std::string message;
  // Canonical, bounded JSON object from the worker's typed error envelope.
  std::string args_json = "{}";
};

struct WorkerReply final {
  bool ok = false;
  WorkerFailure failure;

  // web_session
  std::string url;

  // acquire_media; owned_read_handle is a DuplicateHandle result from the
  // supervisor's already-owned Worker.exe process handle, never a path or PID.
  std::string lease_id;
  OwnedWorkerHandle owned_read_handle;
  uint64_t remote_worker_handle = 0;
  int width = 0;
  int height = 0;
  bool audio_present = false;

  // release_media / shutdown
  bool released = false;
  bool shutting_down = false;
  // True only when the bounded fallback closed the owned job after the
  // graceful shutdown response but before Worker.exe completed naturally.
  bool shutdown_timed_out = false;
};

struct WorkerSupervisorOptions final {
  // 只接受 main 验收后的不可变原生配置，不提供任意路径字符串选项。
  std::shared_ptr<const NativeLaunchConfiguration> launch_configuration;
  DWORD startup_timeout_ms = 30000;
  DWORD request_timeout_ms = 15000;
  DWORD graceful_shutdown_timeout_ms = 30000;
};

// Owns the bundled Worker.exe process, its stdio protocol, one per-data-root
// singleton mutex, and a kill-on-close process job. All potentially blocking
// pipe/process work is performed on supervisor threads. Ready/reply callbacks
// normally run on a dispatch thread; if dispatch allocation/startup fails, they
// may run inline after supervisor locks are released and must marshal UI work.
class WorkerSupervisor final {
 public:
  using ReadyCallback = std::function<void(bool, WorkerReady, WorkerFailure)>;
  using ReplyCallback = std::function<void(WorkerReply)>;
  using ExitCallback = std::function<void()>;

  explicit WorkerSupervisor(WorkerSupervisorOptions options = {});
  ~WorkerSupervisor();

  WorkerSupervisor(const WorkerSupervisor&) = delete;
  WorkerSupervisor& operator=(const WorkerSupervisor&) = delete;
  WorkerSupervisor(WorkerSupervisor&&) = delete;
  WorkerSupervisor& operator=(WorkerSupervisor&&) = delete;

  // Resolves the bundle relative to the current executable and chooses a
  // writable LocalAppData data root scoped to the current Windows SID. Repeated
  // calls while starting/running join the same bootstrap operation.
  void StartAsync(ReadyCallback callback);

  void GetWebSession(ReplyCallback callback);
  void AcquireMedia(const std::string& artifact_id, ReplyCallback callback);
  void ReleaseMedia(const std::string& lease_id, ReplyCallback callback);

  // For a ready worker the callback is delivered only after stdout EOF and the
  // owned Worker.exe process handle is signaled. shutdown_timed_out distinguishes
  // a terminal owned-job fallback from graceful completion. Pre-ready shutdown
  // cancels and reaps any process/pipes before completing.
  void RequestShutdown(ReplyCallback callback);

  // 这是会话不可用通知，含协议/超时失败；不保证原始进程已经结束。
  // callback 在监督器线程调用，不可在其中销毁本对象。
  void SetExitCallback(ExitCallback callback);
  // 仅观测本次 CreateProcess 的原始进程对象及其 duplicate，不按 PID 重新打开。
  // Wait0、不可阻塞平台；duplicate 在 Stop 转移清理 handles 后仍保持有效。
  OwnedWorkerProcessObservation ObserveOwnedProcess() const;
  bool IsReady() const noexcept;

  // Parent cleanup: close stdin to request the worker's EOF cleanup, then close
  // the owned job if necessary. Closing the job only affects this supervisor's
  // own process tree and never queries or terminates an arbitrary PID.
  void Stop();

 private:
  class Impl;
  std::unique_ptr<Impl> impl_;
};

}  // namespace chasteady

#endif  // CHASTEADY_UI_WINDOWS_RUNNER_WORKER_SUPERVISOR_H_
