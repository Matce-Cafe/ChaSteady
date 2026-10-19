#ifndef CHASTEADY_UI_WINDOWS_RUNNER_WINDOW_CHROME_H_
#define CHASTEADY_UI_WINDOWS_RUNNER_WINDOW_CHROME_H_

#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>

#include <functional>
#include <cstdint>
#include <memory>
#include <string>
#ifdef CHASTEADY_WINDOW_DIAGNOSTICS
#include <array>
#include <cstdint>
#include <vector>
#endif

namespace chasteady {

// Platform-thread-only chrome for the runner's OWN top-level HWND and Flutter
// child. No window handles, process IDs, or paths are accepted from Dart.
class WindowChrome final {
 public:
  struct State {
    bool supported = false;
    bool custom_frame_enabled = false;
    bool maximized = false;
    bool always_on_top = false;
    bool maximize_button_hovered = false;
    bool maximize_button_pressed = false;

    bool operator==(const State& other) const;
  };

  // All coordinates are logical pixels in the Flutter/owner client area.
  struct Geometry {
    double title_bar_height = 0.0;
    double controls_left = 0.0;
    double client_width = 0.0;
    double maximize_left = 0.0;
    double maximize_top = 0.0;
    double maximize_width = 0.0;
    double maximize_height = 0.0;
  };

  using StateChanged = std::function<void(const State&)>;

  WindowChrome(HWND owner_window, HWND flutter_child, StateChanged state_changed);
  ~WindowChrome();

  WindowChrome(const WindowChrome&) = delete;
  WindowChrome& operator=(const WindowChrome&) = delete;

  State GetState() const;
  static bool IsValidGeometry(const Geometry& geometry);

  // Disabled by default. The bridge only enables after bootstrap and the Dart
  // normal AppShell's valid post-layout opt-in. Native Show may still be pending.
  // Any frame setup failure attempts to restore the stock caption and returns
  // an explicit error; it never leaves a successful custom-frame response.
  bool Configure(bool enabled, const Geometry& geometry, std::string* error);
  bool Minimize(std::string* error);
  bool ToggleMaximize(std::string* error);
  bool SetAlwaysOnTop(bool value, std::string* error);
  bool StartDrag(std::string* error);
  // 仅平台线程；关闭只取消输入能力，不绕过受管关闭链。
  void SetClosing(bool closing);
  bool HasActiveMaximizeCapture() const;
  uint64_t ActiveMaximizePressEpoch() const;

  // Call before Flutter's plugin and runner default procedures. State-only
  // observations (notably WM_SIZE and WM_DPICHANGED) ALWAYS return false.
  bool HandleWindowMessage(HWND window, UINT message, WPARAM wparam,
                           LPARAM lparam, LRESULT* result);

#ifdef CHASTEADY_WINDOW_DIAGNOSTICS
  // 仅诊断目标编译；512 条环形记录，不接受 HWND/PID，也不改变消息路由。
  struct DiagnosticRecord {
    uint64_t sequence = 0;
    uint64_t tick_ms = 0;
    uint64_t geometry_generation = 0;
    std::string stage;
    UINT message = 0;
    uint64_t wparam = 0;
    int64_t result = 0;
    bool maximized = false;
    bool custom_frame_enabled = false;
    LONG client_width = 0;
    LONG client_height = 0;
    UINT dpi = 0;
  };
  void RecordDiagnostic(const char* stage, UINT message = 0, WPARAM wparam = 0, LRESULT result = 0);
  std::vector<DiagnosticRecord> TakeDiagnostics();
  // 私有诊断只读 ring 视图；不会消费原73/Trial的记录。
  template <typename Visitor>
  void VisitDiagnosticsForPrivateProbe(Visitor&& visitor) const {
    const size_t count = diagnostic_count_;
    const uint64_t first = diagnostic_sequence_ - count;
    for (size_t index = 0; index < count; ++index)
      visitor(diagnostics_[(first + index) % diagnostics_.size()], index, count);
  }

#endif

 private:
  struct ChildSubclassData;

  static LRESULT CALLBACK ChildSubclassProc(HWND window, UINT message,
                                            WPARAM wparam, LPARAM lparam,
                                            UINT_PTR subclass_id,
                                            DWORD_PTR reference_data);
  bool HasOwnedWindows() const;
  bool CanCommand(std::string* error) const;
  bool InstallChildSubclass();
  bool RemoveChildSubclass();
  bool RestoreStockFrame();
  LRESULT HitTest(POINT screen_point) const;
  bool ResetInteraction();
  enum class PressPhase { kIdle, kPressedInside, kPressedOutside };
  struct PressSnapshot {
    uint64_t epoch = 0;
    bool maximized = false;
    UINT dpi = 0;
    LONG client_width = 0;
    LONG client_height = 0;
    LONG_PTR style = 0;
  };
  bool AdvanceInteractionEpoch();
  bool CancelMaximizePress(bool release_owned = true);
  bool MaximizePressEligible(POINT screen) const;
  bool PressSnapshotCurrent(const PressSnapshot& snapshot) const;
  bool BeginMaximizePress(POINT screen);
  bool MoveMaximizePress(POINT screen);
  bool EndMaximizePress(POINT screen);
  bool SubmitMaximize(bool was_maximized, uint64_t expected_epoch, std::string* error);
  void UpdateHoverFromCursor();
  void NotifyStateIfChanged();

  HWND owner_window_ = nullptr;
  HWND child_window_ = nullptr;
  ChildSubclassData* child_subclass_ = nullptr;
  StateChanged state_changed_;
  // DefWindowProc's native move/button loops can pump an orderly WM_CLOSE and
  // destroy this helper before returning. A local token guards post-loop work.
  std::shared_ptr<bool> alive_ = std::make_shared<bool>(true);
  Geometry geometry_;
  State last_state_;
  bool custom_frame_enabled_ = false;
  bool maximize_button_hovered_ = false;
  bool maximize_button_pressed_ = false;
  bool owner_destroying_ = false;
  bool frame_transition_ = false;
  // 正式 epoch/capture 状态不依赖 DIAGNOSTICS，溢出不回卷。
  uint64_t interaction_epoch_ = 0;
  PressPhase press_phase_ = PressPhase::kIdle;
  PressSnapshot press_;
  bool capture_claimed_ = false;
  bool capture_confirmed_ = false;
  bool acquiring_capture_ = false;
  bool releasing_capture_ = false;
  bool command_in_progress_ = false;
  bool closing_ = false;
  bool destructing_ = false;
#ifdef CHASTEADY_WINDOW_DIAGNOSTICS
  std::array<DiagnosticRecord, 512> diagnostics_{};
  uint64_t diagnostic_sequence_ = 0;
  uint64_t geometry_generation_ = 0;
  size_t diagnostic_count_ = 0;
#endif
};

}  // namespace chasteady

#endif  // CHASTEADY_UI_WINDOWS_RUNNER_WINDOW_CHROME_H_
