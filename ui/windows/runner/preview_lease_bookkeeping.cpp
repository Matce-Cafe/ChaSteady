#include "preview_lease_bookkeeping.h"

#include <utility>

namespace chasteady {

bool OwnedWorkerProcessObservation::HasVerifiedIdentity() const {
  return identity_verified && generation != 0 && pid != 0 && creation_filetime != 0 && !image.empty();
}

bool OwnedWorkerProcessObservation::HasReapedStartupFailure() const {
  return startup_failure_reaped && !identity_verified && generation != 0 && pid != 0 &&
      original_handle_observed && wait_state == WaitState::kSignaled;
}

bool OwnedWorkerProcessObservation::MatchesReapedStartupFailure(
    uint64_t current_generation, uint32_t current_pid, bool ready_ever) const {
  return !ready_ever && HasReapedStartupFailure() && generation == current_generation && pid == current_pid;
}

bool OwnedWorkerProcessObservation::IsVerifiedLive() const {
  return !startup_failure_reaped && HasVerifiedIdentity() && original_handle_observed && wait_state == WaitState::kLive;
}

bool OwnedWorkerProcessObservation::IsVerifiedTerminal() const {
  return !startup_failure_reaped && HasVerifiedIdentity() && original_handle_observed && wait_state == WaitState::kSignaled;
}

bool OwnedWorkerProcessObservation::IsGracefulTerminal() const {
  return IsVerifiedTerminal() && !forced_cleanup_requested && exit_code_known && exit_code == 0;
}

bool PreviewLeaseBookkeeping::Track(const std::string& player_id, const std::string& lease_id) {
  if (player_id.empty() || lease_id.empty() || leases_.find(player_id) != leases_.end() ||
      !worker_ || !worker_->IsVerifiedLive()) return false;
  ++next_generation_;
  if (next_generation_ == 0) ++next_generation_;
  Lease lease;
  lease.player_id = player_id;
  lease.lease_id = lease_id;
  lease.generation = next_generation_;
  return leases_.emplace(player_id, std::move(lease)).second;
}

std::optional<PreviewLeaseBookkeeping::Lease> PreviewLeaseBookkeeping::Find(
    const std::string& player_id) const {
  const auto found = leases_.find(player_id);
  if (found == leases_.end()) return std::nullopt;
  return found->second;
}

bool PreviewLeaseBookkeeping::MarkLocallyDisposed(const std::string& player_id) {
  const auto found = leases_.find(player_id);
  if (found == leases_.end()) return false;
  found->second.locally_disposed = true;
  return true;
}

std::optional<PreviewLeaseBookkeeping::ReleaseToken> PreviewLeaseBookkeeping::PrepareRelease(
    const std::string& player_id) const {
  const auto found = leases_.find(player_id);
  if (found == leases_.end() || !found->second.locally_disposed) return std::nullopt;
  ReleaseToken token;
  token.player_id = found->second.player_id;
  token.lease_id = found->second.lease_id;
  token.generation = found->second.generation;
  token.epoch = epoch_;
  return token;
}

PreviewLeaseBookkeeping::Confirmation PreviewLeaseBookkeeping::ConfirmRelease(
    const ReleaseToken& token, bool worker_confirmed_gone) {
  if (!worker_confirmed_gone) return Confirmation::kRetained;
  if (token.epoch != epoch_ || token.generation == 0) return Confirmation::kStale;
  const auto found = leases_.find(token.player_id);
  if (found == leases_.end()) return Confirmation::kAlreadyConfirmed;
  const Lease& current = found->second;
  if (current.generation != token.generation || current.lease_id != token.lease_id ||
      !current.locally_disposed) return Confirmation::kStale;
  leases_.erase(found);
  return Confirmation::kConfirmed;
}

std::vector<PreviewLeaseBookkeeping::Lease> PreviewLeaseBookkeeping::Snapshot() const {
  std::vector<Lease> result;
  result.reserve(leases_.size());
  for (const auto& pair : leases_) result.push_back(pair.second);
  return result;
}

size_t PreviewLeaseBookkeeping::size() const { return leases_.size(); }

void PreviewLeaseBookkeeping::InvalidatePending() {
  ++epoch_;
  if (epoch_ == 0) ++epoch_;
}

bool PreviewLeaseBookkeeping::BindWorker(const OwnedWorkerProcessObservation& observation) {
  if (!observation.IsVerifiedLive() && !observation.IsVerifiedTerminal()) return false;
  if (worker_ && worker_->generation == observation.generation) {
    if (worker_->pid != observation.pid || worker_->creation_filetime != observation.creation_filetime ||
        worker_->image != observation.image ||
        (worker_->IsVerifiedTerminal() && observation.IsVerifiedLive())) return false;
    worker_ = observation;
    return true;
  }
  if ((worker_ && observation.generation < worker_->generation) || !leases_.empty()) return false;
  worker_ = observation;
  InvalidatePending();
  return true;
}

uint64_t PreviewLeaseBookkeeping::WorkerGeneration() const { return worker_ ? worker_->generation : 0; }

bool PreviewLeaseBookkeeping::CanCloseReapedStartupFailure(
    const OwnedWorkerProcessObservation& observation, uint64_t expected_generation, bool bootstrap_ready) const {
  return !bootstrap_ready && !worker_ && leases_.empty() && observation.HasReapedStartupFailure() &&
      (expected_generation == 0 || expected_generation == observation.generation);
}

bool PreviewLeaseBookkeeping::ClearForTerminalWorker(const OwnedWorkerProcessObservation& observation) {
  if (!observation.IsVerifiedTerminal() || !worker_ || worker_->generation != observation.generation ||
      worker_->pid != observation.pid || worker_->creation_filetime != observation.creation_filetime ||
      worker_->image != observation.image) return false;
  worker_ = observation;
  InvalidatePending();
  leases_.clear();
  return true;
}

}  // namespace chasteady
