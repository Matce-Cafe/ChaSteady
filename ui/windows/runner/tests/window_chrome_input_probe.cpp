// 需 Main 单独批准运行；只操作独立 owned fixture，不接受外部 HWND/PID，不截图。
// SELF_TEST 分支完全排除 Win32/SendInput/窗口代码，只测试同一输入收尾状态机。
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <functional>
#include <memory>
#include <string>

#ifndef CHASTEADY_INPUT_SEQUENCE_SELF_TEST
#include "window_chrome.h"
#ifndef CHASTEADY_WINDOW_DIAGNOSTICS
#error This probe requires bounded window diagnostics.
#endif
#endif

namespace {

class OwnedInputSequence final {
 public:
  using Sender = std::function<unsigned()>;

  bool Begin(const Sender& initial_batch, const Sender& own_left_up) {
    if (started_) return false;
    started_ = true;
    inserted_ = initial_batch();
    known_own_down_ = inserted_ == 2 || inserted_ == 3;
    released_ = !known_own_down_;
    // 只有前三项中恰好 MOVE+LEFTDOWN 已插入，才回滚自己确认注入的 DOWN。
    if (inserted_ == 2) {
      compensation_attempts_ = 1;
      compensation_accepted_ = own_left_up() == 1;
    }
    return true;
  }

  void ObserveRelease(bool left_is_up, bool owned_capture, bool after_message_pump) {
    if (after_message_pump && known_own_down_ && left_is_up && !owned_capture) released_ = true;
  }
  void DeadlineReached() { expired_ = true; }
  bool HasUnfinishedOwnDown() const { return known_own_down_ && !released_; }
  bool CanFinish() const { return !HasUnfinishedOwnDown(); }
  bool Succeeded() const { return started_ && inserted_ == 3 && released_ && !expired_; }
  bool Incomplete() const { return expired_ && HasUnfinishedOwnDown(); }
  bool Started() const { return started_; }
  bool FullBatchQueued() const { return started_ && inserted_ == 3; }
  unsigned Inserted() const { return inserted_; }
  unsigned CompensationAttempts() const { return compensation_attempts_; }
  bool CompensationAccepted() const { return compensation_accepted_; }
  bool ResetForNextGesture() {
    if (!started_) return true;
    if (!Succeeded()) return false;
    *this = OwnedInputSequence{};
    return true;
  }

 private:
  bool started_ = false;
  bool known_own_down_ = false;
  bool released_ = false;
  bool expired_ = false;
  unsigned inserted_ = 0;
  unsigned compensation_attempts_ = 0;
  bool compensation_accepted_ = false;
};

#ifdef CHASTEADY_INPUT_SEQUENCE_SELF_TEST

int fake_checks = 0;
void FakeCheck(bool condition, const char* description) {
  ++fake_checks;
  if (!condition) {
    std::fprintf(stderr, "FAIL: %s\n", description);
    std::exit(EXIT_FAILURE);
  }
}

int FakeSelfTest() {
  for (unsigned count = 0; count <= 3; ++count) {
    unsigned initial_calls = 0;
    unsigned up_calls = 0;
    OwnedInputSequence sequence;
    FakeCheck(sequence.Begin([&] { ++initial_calls; return count; },
                             [&] { ++up_calls; return 1u; }), "start one fake initial batch");
    FakeCheck(initial_calls == 1, "never retry an initial gesture");
    FakeCheck(up_calls == (count == 2 ? 1u : 0u), "only confirmed partial DOWN gets one UP");
    FakeCheck(sequence.CompensationAttempts() == up_calls, "compensation count is explicit");
    FakeCheck(!sequence.Succeeded(), "queued input is not observed completion");
    if (count < 2) {
      FakeCheck(sequence.CanFinish(), "zero/move-only inserted no owned DOWN");
      FakeCheck(!sequence.ResetForNextGesture(), "partial failure cannot start a retry");
    } else {
      FakeCheck(!sequence.CanFinish(), "do not close while own DOWN is unfinished");
      sequence.ObserveRelease(true, false, false);
      FakeCheck(!sequence.CanFinish(), "pre-pump key snapshot cannot confirm queued input");
      sequence.ObserveRelease(false, false, true);
      FakeCheck(!sequence.CanFinish(), "button still down blocks close");
      sequence.ObserveRelease(true, true, true);
      FakeCheck(!sequence.CanFinish(), "owned capture still active blocks close");
      sequence.ObserveRelease(true, false, true);
      FakeCheck(sequence.CanFinish(), "post-pump up and ended capture permit close");
      FakeCheck(sequence.Succeeded() == (count == 3), "partial remains failure even after compensation");
    }
    FakeCheck(!sequence.Begin([&] { ++initial_calls; return 3u; },
                              [&] { ++up_calls; return 1u; }), "no second sender on the same sequence");
    FakeCheck(initial_calls == 1 && up_calls == (count == 2 ? 1u : 0u), "no hidden gesture or UP retry");
  }
  unsigned compensations = 0;
  OwnedInputSequence incomplete;
  FakeCheck(incomplete.Begin([] { return 2u; }, [&] { ++compensations; return 0u; }),
            "model failed single compensation");
  FakeCheck(!incomplete.CompensationAccepted(), "failed UP insertion is not claimed complete");
  for (int index = 0; index < 5; ++index) incomplete.ObserveRelease(false, true, true);
  incomplete.DeadlineReached();
  FakeCheck(incomplete.Incomplete() && !incomplete.CanFinish(), "deadline with pending DOWN is INCOMPLETE");
  FakeCheck(compensations == 1, "polling and deadline never retry compensation");
  incomplete.ObserveRelease(true, false, true);
  FakeCheck(incomplete.CanFinish() && !incomplete.Succeeded(), "late observed release still cannot become PASS");
  FakeCheck(!incomplete.ResetForNextGesture(), "failed sequence never starts another gesture");
  OwnedInputSequence full;
  FakeCheck(full.Begin([] { return 3u; }, [] { return 0u; }), "model a full batch");
  FakeCheck(!full.ResetForNextGesture(), "full batch also waits for observed release");
  full.ObserveRelease(true, false, true);
  FakeCheck(full.Succeeded() && full.ResetForNextGesture(), "only observed full success permits next planned gesture");
  FakeCheck(!full.Started(), "new planned gesture starts from a clean state");
  std::printf("PASS: owned input sequence %d checks; pure fake senders 0/1/2/3; no Windows/SendInput/window code.\n",
              fake_checks);
  return EXIT_SUCCESS;
}

#else

constexpr wchar_t kClass[] = L"ChaSteady_OwnedInputProbe";
constexpr UINT_PTR kTimer = 0x4348;

struct Probe {
  HWND owner = nullptr;
  HWND child = nullptr;
  std::unique_ptr<chasteady::WindowChrome> chrome;
  ULONGLONG deadline = 0;
  ULONGLONG next_action = 0;
  int phase = 0;
  int state_events = 0;
  int gesture_attempts = 0;
  unsigned timer_turn = 0;
  unsigned submitted_turn = 0;
  OwnedInputSequence sequence;
  bool failure_draining = false;
  bool incomplete_reported = false;
  std::string failure_reason;
  bool finished = false;
  bool success = false;

  ~Probe() {
    chrome.reset();
    if (owner && IsWindow(owner)) DestroyWindow(owner);
    UnregisterClassW(kClass, GetModuleHandleW(nullptr));
  }

  chasteady::WindowChrome::Geometry Geometry() const {
    RECT client{};
    GetClientRect(owner, &client);
    const double scale = GetDpiForWindow(owner) / 96.0;
    chasteady::WindowChrome::Geometry result;
    result.client_width = client.right / scale;
    result.title_bar_height = 48;
    result.controls_left = result.client_width - 192;
    result.maximize_left = result.client_width - 96;
    result.maximize_width = 48;
    result.maximize_height = 48;
    return result;
  }

  bool NoUserButtonsOrModifiers() const {
    const int keys[] = {VK_LBUTTON, VK_RBUTTON, VK_MBUTTON, VK_XBUTTON1, VK_XBUTTON2,
                        VK_SHIFT, VK_CONTROL, VK_MENU, VK_LWIN, VK_RWIN};
    for (int key : keys) if ((GetAsyncKeyState(key) & 0x8000) != 0) return false;
    return true;
  }

  bool OwnedPoint(POINT point) const {
    DWORD process = 0;
    return owner && child && IsWindowVisible(owner) && IsWindowEnabled(owner) &&
        GetForegroundWindow() == owner && GetParent(child) == owner &&
        GetWindowThreadProcessId(owner, &process) == GetCurrentThreadId() &&
        process == GetCurrentProcessId() && GetAncestor(WindowFromPoint(point), GA_ROOT) == owner &&
        NoUserButtonsOrModifiers();
  }

  bool ClickOwnedMaximize() {
    if (gesture_attempts >= 2 || !sequence.ResetForNextGesture()) return false;
    auto geometry = Geometry();
    std::string error;
    if (!chrome->Configure(true, geometry, &error)) return false;
    const double scale = GetDpiForWindow(owner) / 96.0;
    POINT point{static_cast<LONG>((geometry.maximize_left + 24) * scale), static_cast<LONG>(24 * scale)};
    if (!ClientToScreen(owner, &point) || !OwnedPoint(point)) return false;
    const int left = GetSystemMetrics(SM_XVIRTUALSCREEN);
    const int top = GetSystemMetrics(SM_YVIRTUALSCREEN);
    const int width = GetSystemMetrics(SM_CXVIRTUALSCREEN);
    const int height = GetSystemMetrics(SM_CYVIRTUALSCREEN);
    if (width < 2 || height < 2) return false;
    INPUT input[3]{};
    for (auto& item : input) item.type = INPUT_MOUSE;
    input[0].mi.dx = MulDiv(point.x - left, 65535, width - 1);
    input[0].mi.dy = MulDiv(point.y - top, 65535, height - 1);
    input[0].mi.dwFlags = MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK;
    input[1].mi.dwFlags = MOUSEEVENTF_LEFTDOWN;
    input[2].mi.dwFlags = MOUSEEVENTF_LEFTUP;
    submitted_turn = timer_turn;
    ++gesture_attempts;
    sequence.Begin([&] { return SendInput(3, input, sizeof(INPUT)); }, [] {
      // 只能由返回 2 的状态机调用一次；不移动、不补 DOWN，也不重试任何手势。
      INPUT own_up{};
      own_up.type = INPUT_MOUSE;
      own_up.mi.dwFlags = MOUSEEVENTF_LEFTUP;
      return SendInput(1, &own_up, sizeof(INPUT));
    });
    std::printf("INPUT_SEQUENCE inserted=%u compensationAttempts=%u compensationAccepted=%d\n",
                sequence.Inserted(), sequence.CompensationAttempts(), sequence.CompensationAccepted() ? 1 : 0);
    return sequence.FullBatchQueued();
  }

  void BeginFailureDrain(const char* reason) {
    failure_draining = true;
    failure_reason = reason;
    // 不在 SendInput 返回的当前 turn 立刻关闭；下一次原消息循环 timer 才能确认收尾。
  }

  void Finish(bool passed, const char* reason) {
    if (finished) return;
    if (!sequence.CanFinish()) { BeginFailureDrain(reason); return; }
    finished = true;
    success = passed && sequence.Succeeded() && gesture_attempts == 2;
    KillTimer(owner, kTimer);
    int maximize_commands = 0;
    int restore_commands = 0;
    for (const auto& record : chrome->TakeDiagnostics()) {
      if (record.stage == "owner-message" && record.message == WM_SYSCOMMAND) {
        const UINT command = static_cast<UINT>(record.wparam) & 0xfff0;
        if (command == SC_MAXIMIZE) ++maximize_commands;
        if (command == SC_RESTORE) ++restore_commands;
      }
      std::printf("{\"sequence\":%llu,\"stage\":\"%s\",\"message\":%u,\"wparam\":%llu,"
                  "\"result\":%lld,\"zoomed\":%s,\"geometryGeneration\":%llu,\"dpi\":%u,"
                  "\"width\":%ld,\"height\":%ld}\n",
          static_cast<unsigned long long>(record.sequence), record.stage.c_str(), record.message,
          static_cast<unsigned long long>(record.wparam), static_cast<long long>(record.result),
          record.maximized ? "true" : "false", static_cast<unsigned long long>(record.geometry_generation),
          record.dpi, record.client_width, record.client_height);
    }
    success = success && maximize_commands == 1 && restore_commands == 1;
    std::printf("%s: %s; maxSC=%d restoreSC=%d stateEvents=%d; Win32 fixture only, not Flutter/Snap acceptance.\n",
                success ? "PASS" : "FAIL", reason, maximize_commands, restore_commands, state_events);
    PostMessageW(owner, WM_CLOSE, 0, 0);
  }

  void Tick() {
    ++timer_turn;
    if (finished) return;
    const HWND capture = GetCapture();
    const bool owned_capture = capture && (capture == owner || GetAncestor(capture, GA_ROOT) == owner);
    sequence.ObserveRelease((GetAsyncKeyState(VK_LBUTTON) & 0x8000) == 0, owned_capture,
                            timer_turn > submitted_turn);
    const ULONGLONG now = GetTickCount64();
    if (now >= deadline) {
      sequence.DeadlineReached();
      if (sequence.HasUnfinishedOwnDown()) {
        BeginFailureDrain("owned input completion remained unconfirmed");
        if (!incomplete_reported) {
          incomplete_reported = true;
          std::printf("INCOMPLETE: own injected DOWN/up or capture is unconfirmed; no further input; await bounded parent cleanup.\n");
          std::fflush(stdout);
        }
        return;
      }
      Finish(false, "bounded deadline reached");
      return;
    }
    if (failure_draining) {
      if (sequence.CanFinish()) Finish(false, failure_reason.c_str());
      return;
    }
    if (now < next_action || sequence.HasUnfinishedOwnDown()) return;
    if (phase == 0) {
      if (IsZoomed(owner) || !ClickOwnedMaximize()) { BeginFailureDrain("owned first input guard/batch failed"); return; }
      phase = 1;
      next_action = now + 750;
    } else if (phase == 1) {
      if (!IsZoomed(owner)) { BeginFailureDrain("first real gesture did not maximize"); return; }
      if (!ClickOwnedMaximize()) { BeginFailureDrain("owned restore input guard/batch failed"); return; }
      phase = 2;
      next_action = now + 750;
    } else {
      Finish(!IsZoomed(owner), IsZoomed(owner) ? "second gesture did not restore" : "one maximize and one restore gesture");
    }
  }
};

LRESULT CALLBACK Procedure(HWND window, UINT message, WPARAM wparam, LPARAM lparam) {
  if (message == WM_NCCREATE) {
    SetWindowLongPtrW(window, GWLP_USERDATA,
        reinterpret_cast<LONG_PTR>(reinterpret_cast<CREATESTRUCTW*>(lparam)->lpCreateParams));
  }
  auto* probe = reinterpret_cast<Probe*>(GetWindowLongPtrW(window, GWLP_USERDATA));
  if (probe && message == WM_CLOSE && probe->sequence.HasUnfinishedOwnDown()) {
    probe->BeginFailureDrain("close requested before own injected input completed");
    return 0;
  }
  if (probe && probe->chrome) {
    LRESULT result = 0;
    if (probe->chrome->HandleWindowMessage(window, message, wparam, lparam, &result)) return result;
  }
  if (probe && message == WM_TIMER && wparam == kTimer) { probe->Tick(); return 0; }
  if (probe && message == WM_SIZE && probe->child) {
    RECT client{};
    GetClientRect(window, &client);
    MoveWindow(probe->child, 0, 0, client.right, client.bottom, TRUE);
    if (probe->chrome) {
      std::string error;
      probe->chrome->Configure(true, probe->Geometry(), &error);
    }
  }
  if (message == WM_DESTROY) { PostQuitMessage(0); return 0; }
  return DefWindowProcW(window, message, wparam, lparam);
}

#endif
}  // namespace

#ifdef CHASTEADY_INPUT_SEQUENCE_SELF_TEST
int main() { return FakeSelfTest(); }
#else
int main(int argc, char** argv) {
  if (argc != 2 || std::strcmp(argv[1], "--owned-input-probe") != 0) return 2;
  FILETIME created{}, exited{}, kernel{}, user{};
  wchar_t image[32768]{};
  GetProcessTimes(GetCurrentProcess(), &created, &exited, &kernel, &user);
  GetModuleFileNameW(nullptr, image, 32768);
  char utf8[65536]{};
  WideCharToMultiByte(CP_UTF8, WC_ERR_INVALID_CHARS, image, -1, utf8, sizeof(utf8), nullptr, nullptr);
  std::printf("OWN PID=%lu CREATED=%08lx%08lx IMAGE=%s\n", GetCurrentProcessId(),
              created.dwHighDateTime, created.dwLowDateTime, utf8);
  Probe probe;
  WNDCLASSW definition{};
  definition.style = CS_DBLCLKS;
  definition.lpfnWndProc = Procedure;
  definition.hInstance = GetModuleHandleW(nullptr);
  definition.lpszClassName = kClass;
  if (!RegisterClassW(&definition)) return 2;
  probe.owner = CreateWindowExW(0, kClass, L"ChaSteady OWNED INPUT PROBE", WS_OVERLAPPEDWINDOW,
      80, 80, 960, 640, nullptr, nullptr, GetModuleHandleW(nullptr), &probe);
  if (!probe.owner) return 2;
  probe.child = CreateWindowExW(0, L"STATIC", L"", WS_CHILD | WS_VISIBLE | SS_NOTIFY,
      0, 0, 1, 1, probe.owner, nullptr, GetModuleHandleW(nullptr), nullptr);
  if (!probe.child) return 2;
  probe.chrome = std::make_unique<chasteady::WindowChrome>(probe.owner, probe.child,
      [&](const chasteady::WindowChrome::State&) { ++probe.state_events; });
  std::string error;
  if (!probe.chrome->Configure(true, probe.Geometry(), &error)) return 2;
  ShowWindow(probe.owner, SW_SHOWNORMAL);
  if (!SetForegroundWindow(probe.owner) || GetForegroundWindow() != probe.owner) return 2;
  probe.deadline = GetTickCount64() + 15000;
  probe.next_action = GetTickCount64() + 500;
  if (!SetTimer(probe.owner, kTimer, 100, nullptr)) return 2;
  MSG message{};
  int result = 0;
  while ((result = GetMessageW(&message, nullptr, 0, 0)) > 0) {
    TranslateMessage(&message);
    DispatchMessageW(&message);
  }
  return result == 0 && probe.success ? EXIT_SUCCESS : EXIT_FAILURE;
}
#endif
