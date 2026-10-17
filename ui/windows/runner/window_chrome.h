#ifndef CHASTEADY_UI_WINDOWS_RUNNER_WINDOW_CHROME_H_
#define CHASTEADY_UI_WINDOWS_RUNNER_WINDOW_CHROME_H_

#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>

#include <functional>
#include <memory>
#include <string>

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

  // Call before Flutter's plugin and runner default procedures. State-only
  // observations (notably WM_SIZE and WM_DPICHANGED) ALWAYS return false.
  bool HandleWindowMessage(HWND window, UINT message, WPARAM wparam,
                           LPARAM lparam, LRESULT* result);

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
  void ResetInteraction();
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
};

}  // namespace chasteady

#endif  // CHASTEADY_UI_WINDOWS_RUNNER_WINDOW_CHROME_H_
