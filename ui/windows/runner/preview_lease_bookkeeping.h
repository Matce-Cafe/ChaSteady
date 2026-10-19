#ifndef CHASTEADY_UI_WINDOWS_RUNNER_PREVIEW_LEASE_BOOKKEEPING_H_
#define CHASTEADY_UI_WINDOWS_RUNNER_PREVIEW_LEASE_BOOKKEEPING_H_

#include <cstddef>
#include <cstdint>
#include <map>
#include <optional>
#include <string>
#include <vector>

namespace chasteady {

// 仅原生监督器可产生的观测；Job 关闭/会话失败不等于原始进程对象 signaled。
struct OwnedWorkerProcessObservation final {
  enum class WaitState { kUnknown, kLive, kSignaled, kFailed };
  uint64_t generation = 0;
  uint32_t pid = 0;
  uint64_t creation_filetime = 0;
  std::wstring image;
  bool identity_verified = false;
  bool original_handle_observed = false;
  WaitState wait_state = WaitState::kUnknown;
  bool forced_cleanup_requested = false;
  bool exit_code_known = false;
  uint32_t exit_code = 0;
  // 仅启动失败且从未 ready 的原始 HANDLE 已实际 signaled；绝不授权 live/lease 终态。
  bool startup_failure_reaped = false;

  bool HasVerifiedIdentity() const;
  bool HasReapedStartupFailure() const;
  bool MatchesReapedStartupFailure(uint64_t current_generation, uint32_t current_pid, bool ready_ever) const;
  bool IsVerifiedLive() const;
  bool IsVerifiedTerminal() const;
  // 只描述该进程自然结束；正常关闭还须 Supervisor 的 ACK 与 stdout EOF 门禁。
  bool IsGracefulTerminal() const;
};

// 由 NativeBridge 的原串行 operation_queue 独占；Worker callback 不得直接访问账本。
class PreviewLeaseBookkeeping final {
 public:
  struct Lease {
    std::string player_id;
    std::string lease_id;
    uint64_t generation = 0;
    bool locally_disposed = false;
  };
  struct ReleaseToken {
    std::string player_id;
    std::string lease_id;
    uint64_t generation = 0;
    uint64_t epoch = 0;
  };
  enum class Confirmation {
    kRetained,
    kConfirmed,
    kAlreadyConfirmed,
    kStale,
  };

  PreviewLeaseBookkeeping() = default;
  PreviewLeaseBookkeeping(const PreviewLeaseBookkeeping&) = delete;
  PreviewLeaseBookkeeping& operator=(const PreviewLeaseBookkeeping&) = delete;

  bool Track(const std::string& player_id, const std::string& lease_id);
  std::optional<Lease> Find(const std::string& player_id) const;
  bool MarkLocallyDisposed(const std::string& player_id);
  std::optional<ReleaseToken> PrepareRelease(const std::string& player_id) const;
  // worker_confirmed_gone 只来自已认证 Worker 的成功响应，含已不存在的幂等确认。
  Confirmation ConfirmRelease(const ReleaseToken& token, bool worker_confirmed_gone);
  std::vector<Lease> Snapshot() const;
  size_t size() const;

  // 关闭发起/失败只废弃旧 callback 代次，不能提前忘记原 lease。
  void InvalidatePending();
  bool BindWorker(const OwnedWorkerProcessObservation& observation);
  uint64_t WorkerGeneration() const;
  // 只确认空且未绑定账本的 pre-ready 错误页可关闭；不清账、不提升为 lease 终态。
  bool CanCloseReapedStartupFailure(const OwnedWorkerProcessObservation& observation,
                                   uint64_t expected_generation, bool bootstrap_ready) const;
  // 只接受同一身份/代次的原始 own HANDLE 已实际 signaled 的证据；Stop 返回不是证据。
  bool ClearForTerminalWorker(const OwnedWorkerProcessObservation& observation);

 private:
  std::map<std::string, Lease> leases_;
  uint64_t next_generation_ = 0;
  uint64_t epoch_ = 1;
  std::optional<OwnedWorkerProcessObservation> worker_;
};

}  // namespace chasteady

#endif  // CHASTEADY_UI_WINDOWS_RUNNER_PREVIEW_LEASE_BOOKKEEPING_H_
