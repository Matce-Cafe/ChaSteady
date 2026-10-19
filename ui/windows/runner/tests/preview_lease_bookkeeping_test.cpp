// 直接链接 production PreviewLeaseBookkeeping；不创建窗口、Worker、媒体会话或文件。
#include "preview_lease_bookkeeping.h"

#include <cstdio>
#include <cstdlib>
#include <string>
#include <vector>

namespace {
using Book = chasteady::PreviewLeaseBookkeeping;
using Result = Book::Confirmation;
using Observation = chasteady::OwnedWorkerProcessObservation;
int checks = 0;

// 纯状态机输入，不创建进程、kernel HANDLE 或任何路径实体。
Observation FakeLiveWorker(uint64_t generation) {
  Observation result;
  result.generation = generation;
  result.pid = static_cast<uint32_t>(4000 + generation);
  result.creation_filetime = 0x100000000ULL + generation;
  result.image = L"X:\\owned-fixture\\Worker.exe";
  result.identity_verified = true;
  result.original_handle_observed = true;
  result.wait_state = Observation::WaitState::kLive;
  return result;
}

Observation FakeSignaledWorker(uint64_t generation) {
  Observation result = FakeLiveWorker(generation);
  result.wait_state = Observation::WaitState::kSignaled;
  result.exit_code_known = true;
  result.exit_code = 0;
  return result;
}

void Check(bool condition, const char* description) {
  ++checks;
  if (!condition) {
    std::fprintf(stderr, "FAIL: %s\n", description);
    std::exit(EXIT_FAILURE);
  }
}

struct QueueRejection {
  size_t pending = 64;
  std::vector<std::string> attempted_leases;
  bool TryRelease(const Book::ReleaseToken& token) {
    attempted_leases.push_back(token.lease_id);
    if (pending >= 64) return false;
    ++pending;
    return true;
  }
};

void QueueFullAndRetry() {
  Book book;
  Check(book.BindWorker(FakeLiveWorker(1)), "bind verified live worker for original queue-full regression");
  Check(book.Track("player-a", "lease-original"), "track actual production ownership entry");
  Check(!book.Track("player-a", "lease-overwrite"), "never overwrite an unreleased entry");
  Check(!book.PrepareRelease("player-a"), "active local resources cannot prepare remote release");
  Check(book.Find("player-a")->lease_id == "lease-original", "local disposal failure retains original lease");
  Check(!book.Find("player-a")->locally_disposed, "unconfirmed local disposal is not marked disposed");
  Check(book.MarkLocallyDisposed("player-a"), "record successful local disposal");
  const auto first = book.PrepareRelease("player-a");
  Check(first.has_value(), "prepare only after local disposal succeeded");
  QueueRejection queue;
  Check(!queue.TryRelease(*first), "model actual 64-request immediate queue rejection");
  Check(book.ConfirmRelease(*first, false) == Result::kRetained, "queue rejection must not erase ownership");
  Check(book.size() == 1 && book.Find("player-a")->lease_id == "lease-original",
        "failed release retains player-to-original-lease mapping");
  Check(book.Find("player-a")->locally_disposed, "retry remembers local player was already disposed");
  const auto retry = book.PrepareRelease("player-a");
  Check(retry && retry->lease_id == first->lease_id && retry->generation == first->generation,
        "retry uses the exact same original lease and ownership generation");
  queue.pending = 63;
  Check(queue.TryRelease(*retry), "retry can be accepted after one queue slot becomes available");
  Check(queue.attempted_leases.size() == 2 && queue.attempted_leases[0] == queue.attempted_leases[1],
        "no new lease is substituted by an idempotent local Dispose retry");
  Check(book.size() == 1, "accepted request without ACK still retains ownership");
  Check(book.ConfirmRelease(*retry, true) == Result::kConfirmed, "authenticated Worker ACK erases matching entry");
  Check(book.size() == 0, "successful remote completion leaves no old lease entry");
  Check(book.ConfirmRelease(*first, true) == Result::kAlreadyConfirmed, "late duplicate ACK is idempotent");
}

void DuplicateAndOutOfOrderCallbacks() {
  Book book;
  Check(book.BindWorker(FakeLiveWorker(1)), "bind verified live worker for original duplicate ACK regression");
  Check(book.Track("player", "lease-one"), "track duplicate-dispose case");
  Check(book.MarkLocallyDisposed("player"), "dispose local resource once");
  const auto request_one = *book.PrepareRelease("player");
  const auto request_two = *book.PrepareRelease("player");
  Check(request_one.lease_id == request_two.lease_id, "concurrent disposals release the same lease");
  Check(book.ConfirmRelease(request_two, true) == Result::kConfirmed, "second request may complete first");
  Check(book.ConfirmRelease(request_one, false) == Result::kRetained && book.size() == 0,
        "late failure cannot recreate or erase any ownership");
  Check(book.Track("player", "lease-two"), "new ownership may reuse player key only after confirmation");
  const auto replacement = book.Find("player");
  Check(replacement->generation != request_one.generation, "replacement ownership has a new generation");
  Check(book.ConfirmRelease(request_one, true) == Result::kStale,
        "late old ACK cannot delete the new generation");
  Check(book.Find("player")->lease_id == "lease-two", "new lease survives old success callback");
  Check(book.MarkLocallyDisposed("player"), "dispose replacement locally");
  auto current = *book.PrepareRelease("player");
  auto mismatched = current;
  mismatched.lease_id = "different-lease";
  Check(book.ConfirmRelease(mismatched, true) == Result::kStale, "matching generation with wrong lease is rejected");
  Check(book.Find("player")->lease_id == "lease-two", "mismatched callback retains new lease");
  Check(book.ConfirmRelease(current, true) == Result::kConfirmed, "matching current ACK completes replacement");
}

void ShutdownFailureAndTerminalEpoch() {
  Book book;
  Check(book.BindWorker(FakeLiveWorker(1)), "bind verified live identity for original shutdown regression");
  Check(book.Track("player-close", "lease-close"), "track shutdown case");
  Check(book.MarkLocallyDisposed("player-close"), "dispose shutdown case locally");
  const auto before_close = *book.PrepareRelease("player-close");
  book.InvalidatePending();
  Check(book.size() == 1, "shutdown initiation cannot prematurely forget lease");
  Check(book.ConfirmRelease(before_close, true) == Result::kStale, "pre-close ACK cannot mutate closing epoch");
  Check(book.Find("player-close")->lease_id == "lease-close", "shutdown failure leaves original mapping recoverable");
  const auto after_failed_close = *book.PrepareRelease("player-close");
  Check(after_failed_close.epoch != before_close.epoch &&
        after_failed_close.lease_id == before_close.lease_id,
        "retry after failed shutdown has new epoch and exact original lease");
  Check(book.ConfirmRelease(after_failed_close, false) == Result::kRetained,
        "repeated queue or shutdown rejection does not clear ownership");
  // 协议 1 的 ok:true/released:false 是权威 absence；桥接层同样传 confirmed_gone=true。
  Check(book.ConfirmRelease(after_failed_close, true) == Result::kConfirmed,
        "authoritative already-absent ACK is a valid idempotent confirmation");
  Check(book.Track("player-close", "lease-new-session"), "track later session generation");
  Check(book.MarkLocallyDisposed("player-close"), "prepare later session disposal");
  const auto before_exit = *book.PrepareRelease("player-close");
  Check(book.ClearForTerminalWorker(FakeSignaledWorker(1)), "only matching original-object signal authorizes reset");
  Check(book.size() == 0, "confirmed terminal Worker clears ledger");
  Check(!book.Track("player-close", "lease-with-dead-worker"), "terminal worker cannot create fresh ownership");
  Check(book.BindWorker(FakeLiveWorker(2)), "bind newer verified live worker before replacement ownership");
  Check(book.Track("player-close", "lease-after-exit"), "create a new ownership after terminal reset");
  Check(book.ConfirmRelease(before_exit, true) == Result::kStale,
        "terminal old callback cannot delete later ownership");
  Check(book.Find("player-close")->lease_id == "lease-after-exit", "post-exit ownership survives old ACK");
}

void SnapshotAndIndependentEntries() {
  Book book;
  Check(book.BindWorker(FakeLiveWorker(1)), "bind verified live worker for original independent-ledger regression");
  Check(!book.Track("", "lease") && !book.Track("player", ""), "reject empty ownership identifiers");
  Check(!book.Find("unknown") && !book.PrepareRelease("unknown") && !book.MarkLocallyDisposed("unknown"),
        "unknown ownership cannot manufacture a release token");
  std::vector<Book::ReleaseToken> tokens;
  for (int index = 0; index < 64; ++index) {
    const std::string player = "p-" + std::to_string(index);
    Check(book.Track(player, "l-" + std::to_string(index)), "track independent ownership");
    Check(book.MarkLocallyDisposed(player), "dispose independent local resource");
    tokens.push_back(*book.PrepareRelease(player));
  }
  auto snapshot = book.Snapshot();
  Check(snapshot.size() == 64 && book.size() == 64, "snapshot contains every retained ownership");
  const std::string original_player = snapshot[0].player_id;
  const std::string original_lease = snapshot[0].lease_id;
  snapshot[0].lease_id = "mutated-copy";
  Check(book.Find(original_player)->lease_id == original_lease, "snapshot cannot mutate production ledger");
  for (size_t index = tokens.size(); index > 0; --index)
    Check(book.ConfirmRelease(tokens[index - 1], true) == Result::kConfirmed,
          "out-of-order ACK only removes its exact matching ownership");
  Check(book.size() == 0, "all independent confirmed releases completed");
}
void ObservationProofPredicates() {
  Observation unknown;
  Check(!unknown.HasVerifiedIdentity() && !unknown.IsVerifiedLive() && !unknown.IsVerifiedTerminal(),
        "default or no-owned-process observation is not proof");
  unknown.wait_state = Observation::WaitState::kSignaled;
  Check(!unknown.IsVerifiedTerminal(), "a fabricated signaled flag without identity is not proof");
  const Observation live = FakeLiveWorker(10);
  Check(live.HasVerifiedIdentity() && live.IsVerifiedLive() && !live.IsVerifiedTerminal(),
        "verified original-object WAIT_TIMEOUT remains live");
  const Observation terminal = FakeSignaledWorker(10);
  Check(terminal.IsVerifiedTerminal(), "verified original-object signal is terminal resource proof");
  Check(terminal.IsGracefulTerminal(), "process-only natural predicate still leaves ACK and EOF to Supervisor");
  for (int missing = 0; missing < 6; ++missing) {
    Observation invalid = terminal;
    if (missing == 0) invalid.identity_verified = false;
    if (missing == 1) invalid.generation = 0;
    if (missing == 2) invalid.pid = 0;
    if (missing == 3) invalid.creation_filetime = 0;
    if (missing == 4) invalid.image.clear();
    if (missing == 5) invalid.original_handle_observed = false;
    Check(!invalid.IsVerifiedLive() && !invalid.IsVerifiedTerminal() && !invalid.IsGracefulTerminal(),
          "every identity component and original-handle observation is mandatory");
  }
  for (Observation::WaitState state : {Observation::WaitState::kUnknown, Observation::WaitState::kLive,
                                     Observation::WaitState::kFailed}) {
    Observation not_terminal = terminal;
    not_terminal.wait_state = state;
    not_terminal.forced_cleanup_requested = true;
    Check(!not_terminal.IsVerifiedTerminal() && !not_terminal.IsGracefulTerminal(),
          "WAIT_FAILED unknown or live cannot become terminal from a cleanup request or exit code");
  }
  Observation changed = terminal;
  changed.forced_cleanup_requested = true;
  Check(changed.IsVerifiedTerminal() && !changed.IsGracefulTerminal(),
        "forced cleanup can reach resource terminal but is never graceful proof");
  changed = terminal;
  changed.exit_code_known = false;
  Check(changed.IsVerifiedTerminal() && !changed.IsGracefulTerminal(),
        "unknown exit code allows proven resource terminal but not natural-success classification");
  changed = terminal;
  changed.exit_code = 1;
  Check(changed.IsVerifiedTerminal() && !changed.IsGracefulTerminal(),
        "nonzero exit code is not graceful completion");
}

void SessionFailureDoesNotMeanProcessExit() {
  Book book;
  const Observation live = FakeLiveWorker(20);
  Check(book.BindWorker(live), "bind actual production ledger to verified live process identity");
  Check(book.Track("player-terminal", "lease-original-live"), "track lease before session failure");
  Check(book.MarkLocallyDisposed("player-terminal"), "local resource disposal precedes terminal observation");
  const auto pending = *book.PrepareRelease("player-terminal");
  book.InvalidatePending();
  Check(book.size() == 1, "protocol or timeout failure retains worker lease after local disposal");
  Check(book.ConfirmRelease(pending, true) == Result::kStale,
        "late pre-failure ACK cannot bypass the failed-session epoch");
  Observation not_signaled = live;
  not_signaled.forced_cleanup_requested = true;
  Check(!book.ClearForTerminalWorker(not_signaled), "CloseJob or Stop return with live original handle is not terminal");
  Check(book.size() == 1 && book.Find("player-terminal")->lease_id == "lease-original-live",
        "request-timeout callback and asynchronous cleanup transfer preserve exact lease");
  for (Observation::WaitState state : {Observation::WaitState::kLive, Observation::WaitState::kFailed,
                                     Observation::WaitState::kUnknown, Observation::WaitState::kLive}) {
    not_signaled.wait_state = state;
    Check(!book.ClearForTerminalWorker(not_signaled),
          "repeated polls including failed CloseHandle or WAIT_FAILED cannot clear live ownership");
    Check(book.size() == 1, "each nonterminal poll preserves bookkeeping until subsequent real signal");
  }
  Observation forged = FakeSignaledWorker(20);
  forged.original_handle_observed = false;
  Check(!book.ClearForTerminalWorker(forged), "a claimed terminal callback without original handle cannot clear ledger");
  Check(book.size() == 1, "untrusted terminal claim retains ownership");
  Observation forced_terminal = FakeSignaledWorker(20);
  forced_terminal.forced_cleanup_requested = true;
  forced_terminal.exit_code = 1;
  Check(book.ClearForTerminalWorker(forced_terminal),
        "a later actual signaled observation of the same original object finally clears resources");
  Check(book.size() == 0, "asynchronous owned cleanup has a reachable proof-gated completion path");
  Check(!forced_terminal.IsGracefulTerminal(), "resource ledger cleanup cannot convert forced failure into graceful PASS");
  Check(!book.BindWorker(live), "a terminal process identity cannot become live again");
  Check(!book.Track("player-terminal", "lease-resurrection"), "no new player lease belongs to the dead worker");
}

void IdentityAndGenerationIsolation() {
  Book book;
  const Observation live = FakeLiveWorker(30);
  const Observation terminal = FakeSignaledWorker(30);
  Check(book.BindWorker(live), "bind first process generation");
  Check(book.Track("player-generation", "lease-generation-one"), "track generation-one lease");
  Check(book.MarkLocallyDisposed("player-generation"), "dispose generation-one local resource");
  const auto old_token = *book.PrepareRelease("player-generation");
  for (int mismatch = 0; mismatch < 5; ++mismatch) {
    Observation other = terminal;
    if (mismatch == 0) ++other.pid;
    if (mismatch == 1) ++other.creation_filetime;
    if (mismatch == 2) other.image = L"X:\\different-owned-fixture\\Worker.exe";
    if (mismatch == 3) --other.generation;
    if (mismatch == 4) ++other.generation;
    Check(!book.ClearForTerminalWorker(other), "wrong PID creation time image or generation cannot clear current ledger");
    Check(book.size() == 1 && book.WorkerGeneration() == live.generation,
          "mismatched terminal evidence leaves old ownership and binding intact");
    Check(!book.BindWorker(other), "unreleased entries prevent binding a different identity or generation");
  }
  Check(!book.BindWorker(FakeLiveWorker(31)), "new live worker cannot overwrite unreleased old-generation ownership");
  Check(book.ClearForTerminalWorker(terminal), "matching first original-object proof clears first generation");
  Check(book.BindWorker(FakeLiveWorker(31)), "newer verified-live generation can bind after real terminal cleanup");
  Check(book.Track("player-generation", "lease-generation-two"), "replacement generation has independent ownership");
  Check(!book.ClearForTerminalWorker(terminal), "late old-worker signal cannot erase new-worker map");
  Check(book.ConfirmRelease(old_token, true) == Result::kStale, "late old-worker ACK cannot erase newer ownership epoch");
  Check(!book.BindWorker(live), "late old live observation cannot rebind a higher generation");
  Check(book.WorkerGeneration() == 31 && book.Find("player-generation")->lease_id == "lease-generation-two",
        "newer worker and lease survive every old identity notification");
  Check(book.MarkLocallyDisposed("player-generation"), "dispose replacement local resource");
  Check(book.ClearForTerminalWorker(FakeSignaledWorker(31)), "matching replacement signal clears only replacement ownership");
  Check(!book.BindWorker(live) && !book.BindWorker(terminal), "even an empty ledger cannot roll back to an older worker generation");
}

void UnknownObservationCannotAuthorizeCleanup() {
  Book book;
  const Observation terminal = FakeSignaledWorker(40);
  Check(!book.ClearForTerminalWorker(terminal), "signaled evidence without any bound owner cannot authorize ledger reset");
  Observation unknown = FakeLiveWorker(40);
  unknown.wait_state = Observation::WaitState::kFailed;
  Check(!book.BindWorker(unknown) && book.WorkerGeneration() == 0, "WAIT_FAILED cannot become a verified creation binding");
  unknown.wait_state = Observation::WaitState::kUnknown;
  Check(!book.BindWorker(unknown) && book.WorkerGeneration() == 0, "unknown wait cannot enable preview admission");
  unknown = FakeLiveWorker(40);
  unknown.original_handle_observed = false;
  Check(!book.BindWorker(unknown), "no original HANDLE observation cannot enable preview admission");
  Check(!book.Track("unbound-player", "unbound-lease"), "an unbound ledger cannot manufacture preview ownership");
  Check(book.size() == 0, "unknown admission creates no untracked remote ownership entry");
  Check(book.BindWorker(FakeLiveWorker(40)), "only a verified live original object enables new preview ownership");
  Check(book.Track("bound-player", "bound-lease"), "valid identity is required before actual production Track");
  unknown = terminal;
  unknown.original_handle_observed = false;
  Check(!book.ClearForTerminalWorker(unknown) && book.size() == 1,
        "a later unknown terminal claim still fails closed and retains the valid ownership");
}
void StartupFailureReapIsNotLeaseAuthority() {
  Observation reaped;
  reaped.generation = 50;
  reaped.pid = 4050;
  reaped.original_handle_observed = true;
  reaped.wait_state = Observation::WaitState::kSignaled;
  reaped.startup_failure_reaped = true;
  reaped.forced_cleanup_requested = true;
  Book empty;
  Check(reaped.HasReapedStartupFailure(), "saved actual original-handle signal can confirm pre-ready startup cleanup");
  Check(!reaped.IsVerifiedLive() && !reaped.IsVerifiedTerminal() && !reaped.IsGracefulTerminal(),
        "startup-only reap evidence is never verified-live lease terminal or graceful authority");
  Check(reaped.MatchesReapedStartupFailure(50, 4050, false), "only same source generation and CreateProcess PID expose reap proof");
  Check(!reaped.MatchesReapedStartupFailure(51, 4050, false), "PID reuse in a later generation cannot reuse old startup proof");
  Check(!reaped.MatchesReapedStartupFailure(50, 4051, false), "same generation with another created PID cannot expose proof");
  Check(!reaped.MatchesReapedStartupFailure(50, 4050, true), "ever-ready source cannot expose startup-only proof");
  Check(!Observation{}.MatchesReapedStartupFailure(50, 4050, false), "reset or new-source empty evidence is not completion");
  Check(empty.CanCloseReapedStartupFailure(reaped, 50, false), "empty unbound pre-ready error page can close after actual reap");
  Check(empty.CanCloseReapedStartupFailure(reaped, 0, false), "same pre-start attempt may publish its first identity during Stop join");
  Check(!empty.CanCloseReapedStartupFailure(reaped, 49, false) &&
        !empty.CanCloseReapedStartupFailure(reaped, 51, false), "explicit generation mismatch cannot authorize close");
  Check(!empty.CanCloseReapedStartupFailure(reaped, 50, true), "bootstrap-ready bridge cannot consume startup cleanup evidence");
  Check(!empty.BindWorker(reaped) && !empty.ClearForTerminalWorker(reaped),
        "startup proof cannot bind a media worker or authorize lease clearing");
  Check(!empty.Track("startup-player", "startup-lease"), "startup failure proof never enables new media ownership");
  Check(empty.size() == 0 && empty.WorkerGeneration() == 0, "closeability query neither creates binding nor mutates ledger");
  for (int missing = 0; missing < 8; ++missing) {
    Observation incomplete = reaped;
    if (missing == 0) incomplete.startup_failure_reaped = false;
    if (missing == 1) incomplete.generation = 0;
    if (missing == 2) incomplete.pid = 0;
    if (missing == 3) incomplete.original_handle_observed = false;
    if (missing == 4) incomplete.wait_state = Observation::WaitState::kUnknown;
    if (missing == 5) incomplete.wait_state = Observation::WaitState::kLive;
    if (missing == 6) incomplete.wait_state = Observation::WaitState::kFailed;
    if (missing == 7) incomplete.identity_verified = true;
    Check(!incomplete.HasReapedStartupFailure(),
          "Stop transfer CloseJob request timeout failed wait or incomplete source identity is not startup reap proof");
    Check(!empty.CanCloseReapedStartupFailure(incomplete, 50, false),
          "every missing or conflicting startup proof component fails close confirmation");
  }
  Observation mixed = FakeSignaledWorker(50);
  mixed.startup_failure_reaped = true;
  Check(!mixed.IsVerifiedLive() && !mixed.IsVerifiedTerminal() && !mixed.HasReapedStartupFailure(),
        "mixing startup-only and full-identity roles grants neither authority");
  Book bound;
  Check(bound.BindWorker(FakeLiveWorker(50)), "bind ordinary live worker for startup-proof isolation");
  Check(bound.Track("existing-player", "existing-lease"), "retain ordinary ownership before bogus startup proof");
  Check(!bound.CanCloseReapedStartupFailure(reaped, 50, false) && !bound.ClearForTerminalWorker(reaped),
        "even same PID generation startup proof cannot clear existing lease or authorize its close path");
  Check(bound.size() == 1 && bound.Find("existing-player")->lease_id == "existing-lease",
        "startup proof does not forget any real ownership");
  Check(bound.MarkLocallyDisposed("existing-player"), "dispose ordinary resource through original protocol path");
  const auto token = *bound.PrepareRelease("existing-player");
  Check(bound.ConfirmRelease(token, true) == Result::kConfirmed, "authenticated ordinary release remains independent");
  Check(!bound.CanCloseReapedStartupFailure(reaped, 50, false),
        "previously bound ordinary worker cannot become startup-only even after ledger empties");
  Check(bound.BindWorker(FakeLiveWorker(51)), "later source has its independent verified live generation");
  Check(!bound.CanCloseReapedStartupFailure(reaped, 51, false) && !bound.ClearForTerminalWorker(reaped),
        "old startup evidence cannot authorize a later worker close or erase later ownership");
}
}  // namespace

int main() {
  QueueFullAndRetry();
  DuplicateAndOutOfOrderCallbacks();
  ShutdownFailureAndTerminalEpoch();
  SnapshotAndIndependentEntries();
  ObservationProofPredicates();
  SessionFailureDoesNotMeanProcessExit();
  IdentityAndGenerationIsolation();
  UnknownObservationCannotAuthorizeCleanup();
  StartupFailureReapIsNotLeaseAuthority();
  std::printf("PASS: production preview lease bookkeeping %d checks; no GUI/Worker/media engine.\n", checks);
  return EXIT_SUCCESS;
}
