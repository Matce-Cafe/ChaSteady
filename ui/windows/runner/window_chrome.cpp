#include "window_chrome.h"

#include <commctrl.h>
#include <dwmapi.h>
#include <windowsx.h>

#include <algorithm>
#include <cmath>
#include <new>
#include <utility>

namespace chasteady {
namespace {

constexpr UINT_PTR kFlutterChildSubclassId = 0x43485343;
constexpr double kMaximumClientWidth = 65536.0;
constexpr double kMaximumTitleBarHeight = 512.0;
// Layout arithmetic at fractional DPI can differ by a sub-pixel rounding ULP.
constexpr double kGeometryEpsilon = 0.001;

bool Fail(std::string* error, const char* code) {
  if (error != nullptr) *error = code;
  return false;
}

bool IsCurrentThreadWindow(HWND window) {
  if (window == nullptr || !IsWindow(window)) return false;
  DWORD process_id = 0;
  const DWORD thread_id = GetWindowThreadProcessId(window, &process_id);
  return process_id == GetCurrentProcessId() && thread_id == GetCurrentThreadId();
}

bool RecalculateFrame(HWND window) {
  return SetWindowPos(window, nullptr, 0, 0, 0, 0,
                      SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE |
                          SWP_FRAMECHANGED) != FALSE;
}

bool GetMonitorInfoForRect(const RECT& rect, MONITORINFO* info) {
  if (info == nullptr) return false;
  info->cbSize = sizeof(*info);
  return GetMonitorInfo(MonitorFromRect(&rect, MONITOR_DEFAULTTONEAREST), info) != FALSE;
}

double DpiScale(HWND window) {
  const UINT dpi = GetDpiForWindow(window);
  return (dpi == 0 ? 96.0 : static_cast<double>(dpi)) / 96.0;
}

}  // namespace

struct WindowChrome::ChildSubclassData {
  WindowChrome* chrome = nullptr;
};

bool WindowChrome::State::operator==(const State& other) const {
  return supported == other.supported &&
         custom_frame_enabled == other.custom_frame_enabled &&
         maximized == other.maximized && always_on_top == other.always_on_top &&
         maximize_button_hovered == other.maximize_button_hovered &&
         maximize_button_pressed == other.maximize_button_pressed;
}

WindowChrome::WindowChrome(HWND owner_window, HWND flutter_child,
                           StateChanged state_changed)
    : owner_window_(owner_window), child_window_(flutter_child),
      state_changed_(std::move(state_changed)) {
  last_state_ = GetState();
}

WindowChrome::~WindowChrome() {
  *alive_ = false;
  state_changed_ = nullptr;
  if (custom_frame_enabled_ && !owner_destroying_) {
    RestoreStockFrame();
  } else {
    RemoveChildSubclass();
  }
  if (child_subclass_ != nullptr) {
    // A failed system removal must not leave a callback pointing at a destroyed
    // helper. The inert hook frees its small record at the child's NCDESTROY.
    child_subclass_->chrome = nullptr;
    child_subclass_ = nullptr;
  }
}

bool WindowChrome::HasOwnedWindows() const {
  if (owner_destroying_ || !IsCurrentThreadWindow(owner_window_) ||
      !IsCurrentThreadWindow(child_window_)) return false;
  if (GetAncestor(child_window_, GA_ROOT) != owner_window_ ||
      GetAncestor(owner_window_, GA_ROOT) != owner_window_) return false;
  const LONG_PTR style = GetWindowLongPtr(owner_window_, GWL_STYLE);
  // Never trade resize/sysmenu/min/max capability for a bare WS_POPUP frame.
  return (style & WS_OVERLAPPEDWINDOW) == WS_OVERLAPPEDWINDOW &&
         (style & WS_CHILD) == 0;
}

WindowChrome::State WindowChrome::GetState() const {
  State state;
  state.supported = HasOwnedWindows();
  if (!state.supported) return state;
  state.custom_frame_enabled = custom_frame_enabled_;
  state.maximized = IsZoomed(owner_window_) != FALSE;
  state.always_on_top =
      (GetWindowLongPtr(owner_window_, GWL_EXSTYLE) & WS_EX_TOPMOST) != 0;
  state.maximize_button_hovered =
      custom_frame_enabled_ && maximize_button_hovered_;
  state.maximize_button_pressed =
      custom_frame_enabled_ && maximize_button_pressed_;
  return state;
}

bool WindowChrome::IsValidGeometry(const Geometry& geometry) {
  const double values[] = {
      geometry.title_bar_height, geometry.controls_left, geometry.client_width,
      geometry.maximize_left, geometry.maximize_top, geometry.maximize_width,
      geometry.maximize_height};
  for (double value : values) {
    if (!std::isfinite(value)) return false;
  }
  return geometry.title_bar_height > 0.0 &&
         geometry.title_bar_height <= kMaximumTitleBarHeight &&
         geometry.client_width > 0.0 &&
         geometry.client_width <= kMaximumClientWidth &&
         geometry.controls_left >= 0.0 &&
         geometry.controls_left <= geometry.client_width &&
         geometry.maximize_left >= geometry.controls_left &&
         geometry.maximize_top >= 0.0 && geometry.maximize_width > 0.0 &&
         geometry.maximize_height > 0.0 &&
         geometry.maximize_width <= kMaximumTitleBarHeight &&
         geometry.maximize_height <= kMaximumTitleBarHeight &&
         geometry.maximize_left + geometry.maximize_width <=
             geometry.client_width + kGeometryEpsilon &&
         geometry.maximize_top + geometry.maximize_height <=
             geometry.title_bar_height + kGeometryEpsilon;
}

bool WindowChrome::InstallChildSubclass() {
  if (child_subclass_ != nullptr) {
    child_subclass_->chrome = this;
    return true;
  }
  if (!HasOwnedWindows()) return false;
  auto* data = new (std::nothrow) ChildSubclassData;
  if (data == nullptr) return false;
  data->chrome = this;
  if (!SetWindowSubclass(child_window_, ChildSubclassProc,
                         kFlutterChildSubclassId,
                         reinterpret_cast<DWORD_PTR>(data))) {
    delete data;
    return false;
  }
  child_subclass_ = data;
  return true;
}

bool WindowChrome::RemoveChildSubclass() {
  if (child_subclass_ == nullptr) return true;
  child_subclass_->chrome = nullptr;
  DWORD_PTR installed_data = 0;
  if (!IsWindow(child_window_) ||
      RemoveWindowSubclass(child_window_, ChildSubclassProc,
                           kFlutterChildSubclassId) ||
      !GetWindowSubclass(child_window_, ChildSubclassProc,
                         kFlutterChildSubclassId, &installed_data) ||
      installed_data != reinterpret_cast<DWORD_PTR>(child_subclass_)) {
    delete child_subclass_;
    child_subclass_ = nullptr;
    return true;
  }
  return false;
}

bool WindowChrome::RestoreStockFrame() {
  frame_transition_ = true;
  custom_frame_enabled_ = false;
  geometry_ = Geometry{};
  ResetInteraction();
  bool restored = true;
  if (!owner_destroying_ && IsCurrentThreadWindow(owner_window_)) {
    const MARGINS margins{0, 0, 0, 0};
    const HRESULT dwm_result = DwmExtendFrameIntoClientArea(owner_window_, &margins);
    // NCCALCSIZE is already disabled even if DWM is temporarily unavailable.
    // Recalculate the stock caption independently of that HRESULT.
    const bool frame_recalculated = RecalculateFrame(owner_window_);
    restored = SUCCEEDED(dwm_result) && frame_recalculated;
    RedrawWindow(owner_window_, nullptr, nullptr,
                 RDW_FRAME | RDW_INVALIDATE | RDW_ALLCHILDREN);
  }
  const bool subclass_removed = RemoveChildSubclass();
  frame_transition_ = false;
  NotifyStateIfChanged();
  return restored && subclass_removed;
}

bool WindowChrome::Configure(bool enabled, const Geometry& geometry,
                             std::string* error) {
#ifdef CHASTEADY_WINDOW_DIAGNOSTICS
  ++geometry_generation_;
  RecordDiagnostic(enabled ? "configure-enabled" : "configure-disabled");
#endif
  if (error != nullptr) error->clear();
  if (!enabled) {
    if (!custom_frame_enabled_ && child_subclass_ == nullptr) return true;
    return RestoreStockFrame() || Fail(error, "window_chrome_restore_failed");
  }
  if (!IsValidGeometry(geometry)) {
    if (custom_frame_enabled_) RestoreStockFrame();
    return Fail(error, "invalid_arguments");
  }
  if (!HasOwnedWindows()) {
    if (custom_frame_enabled_) RestoreStockFrame();
    return Fail(error, "window_chrome_unavailable");
  }
  if (custom_frame_enabled_) {
    // Geometry updates while minimized must not strand an otherwise valid
    // custom frame.
    geometry_ = geometry;
    UpdateHoverFromCursor();
    NotifyStateIfChanged();
    return true;
  }
  // Do not require IsWindowVisible here: Dart's completed AppShell layout can
  // precede FlutterWindow's raster-first-frame Show callback. The bridge gates
  // bootstrap and the bounded, explicit post-layout opt-in instead.
  if (!InstallChildSubclass()) return Fail(error, "window_chrome_unavailable");
  geometry_ = geometry;
  frame_transition_ = true;
  custom_frame_enabled_ = true;
  const MARGINS margins{1, 1, 1, 1};
  const HRESULT dwm_result = DwmExtendFrameIntoClientArea(owner_window_, &margins);
  if (FAILED(dwm_result) || !RecalculateFrame(owner_window_)) {
    const bool restored = RestoreStockFrame();
    return Fail(error, restored ? "window_chrome_failed" :
                                 "window_chrome_restore_failed");
  }
  frame_transition_ = false;
  UpdateHoverFromCursor();
  NotifyStateIfChanged();
  return true;
}

bool WindowChrome::CanCommand(std::string* error) const {
  if (error != nullptr) error->clear();
  if (!HasOwnedWindows() || !IsWindowVisible(owner_window_)) {
    return Fail(error, "window_unavailable");
  }
  return true;
}

bool WindowChrome::Minimize(std::string* error) {
  if (!CanCommand(error)) return false;
  ResetInteraction();
  ShowWindow(owner_window_, SW_MINIMIZE);
  NotifyStateIfChanged();
  return IsIconic(owner_window_) || Fail(error, "window_command_failed");
}

bool WindowChrome::ToggleMaximize(std::string* error) {
  if (!CanCommand(error)) return false;
  const bool was_maximized = IsZoomed(owner_window_) != FALSE;
  ResetInteraction();
  ShowWindow(owner_window_, was_maximized ? SW_RESTORE : SW_MAXIMIZE);
  NotifyStateIfChanged();
  return ((IsZoomed(owner_window_) != FALSE) != was_maximized &&
          !IsIconic(owner_window_)) || Fail(error, "window_command_failed");
}

bool WindowChrome::SetAlwaysOnTop(bool value, std::string* error) {
  if (!CanCommand(error)) return false;
  if (!SetWindowPos(owner_window_, value ? HWND_TOPMOST : HWND_NOTOPMOST,
                    0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)) {
    return Fail(error, "window_command_failed");
  }
  NotifyStateIfChanged();
  return GetState().always_on_top == value || Fail(error, "window_command_failed");
}

bool WindowChrome::StartDrag(std::string* error) {
  if (!CanCommand(error) || IsIconic(owner_window_)) {
    return Fail(error, "window_unavailable");
  }
  POINT cursor{};
  if (!GetCursorPos(&cursor)) return Fail(error, "window_command_failed");
  ResetInteraction();
  ReleaseCapture();
  // Post only to our owner: the channel callback must release its teardown
  // gate before the native move loop pumps messages (including orderly close).
  // The normal owner/default procedure owns drag/restore-from-maximized; this
  // is neither a worker operation nor a second Dart maximize toggle.
  const bool posted = PostMessage(owner_window_, WM_NCLBUTTONDOWN, HTCAPTION,
      MAKELPARAM(static_cast<WORD>(cursor.x), static_cast<WORD>(cursor.y))) != FALSE;
  NotifyStateIfChanged();
  return posted || Fail(error, "window_command_failed");
}

LRESULT WindowChrome::HitTest(POINT screen_point) const {
  RECT window_rect{};
  if (!GetWindowRect(owner_window_, &window_rect)) return HTCLIENT;
  if (!PtInRect(&window_rect, screen_point)) return HTNOWHERE;
  if (!IsZoomed(owner_window_) && !IsIconic(owner_window_)) {
    const UINT window_dpi = GetDpiForWindow(owner_window_);
    const UINT dpi = window_dpi == 0 ? 96 : window_dpi;
    const int padded = GetSystemMetricsForDpi(SM_CXPADDEDBORDER, dpi);
    const int border_x = GetSystemMetricsForDpi(SM_CXSIZEFRAME, dpi) + padded;
    const int border_y = GetSystemMetricsForDpi(SM_CYSIZEFRAME, dpi) + padded;
    const bool left = screen_point.x < window_rect.left + border_x;
    const bool right = screen_point.x >= window_rect.right - border_x;
    const bool top = screen_point.y < window_rect.top + border_y;
    const bool bottom = screen_point.y >= window_rect.bottom - border_y;
    if (top && left) return HTTOPLEFT;
    if (top && right) return HTTOPRIGHT;
    if (bottom && left) return HTBOTTOMLEFT;
    if (bottom && right) return HTBOTTOMRIGHT;
    if (left) return HTLEFT;
    if (right) return HTRIGHT;
    if (top) return HTTOP;
    if (bottom) return HTBOTTOM;
  }
  POINT client_point = screen_point;
  if (!ScreenToClient(owner_window_, &client_point)) return HTCLIENT;
  const double scale = DpiScale(owner_window_);
  const double x = static_cast<double>(client_point.x) / scale;
  const double y = static_cast<double>(client_point.y) / scale;
  RECT client{};
  if (!GetClientRect(owner_window_, &client)) return HTCLIENT;
  // A resize/DPI transition can precede Dart's next presented layout. After
  // system sizing edges, suspend ALL stale title-bar partitions: an old caption
  // boundary must not swallow newly shifted Flutter controls as window drags.
  const bool current_width =
      std::abs(static_cast<double>(client.right - client.left) / scale -
               geometry_.client_width) <= 1.0 / scale;
  if (!current_width) return HTCLIENT;
  if (x >= geometry_.maximize_left &&
      x < geometry_.maximize_left + geometry_.maximize_width &&
      y >= geometry_.maximize_top &&
      y < geometry_.maximize_top + geometry_.maximize_height) {
    return HTMAXBUTTON;  // Real Windows 11 Snap layout affordance, not HTCLIENT.
  }
  if (y >= 0.0 && y < geometry_.title_bar_height &&
      x >= 0.0 && x < geometry_.controls_left) return HTCAPTION;
  // Pin, minimize, close, and every other right-hand control stay in Flutter.
  return HTCLIENT;
}

void WindowChrome::ResetInteraction() {
  maximize_button_hovered_ = false;
  maximize_button_pressed_ = false;
}

void WindowChrome::UpdateHoverFromCursor() {
  POINT cursor{};
  maximize_button_hovered_ = custom_frame_enabled_ &&
      GetCursorPos(&cursor) && HitTest(cursor) == HTMAXBUTTON;
  if (!maximize_button_hovered_ || (GetKeyState(VK_LBUTTON) & 0x8000) == 0) {
    maximize_button_pressed_ = false;
  }
}

#ifdef CHASTEADY_WINDOW_DIAGNOSTICS
void WindowChrome::RecordDiagnostic(const char* stage, UINT message, WPARAM wparam, LRESULT result) {
  DiagnosticRecord record;
  record.sequence = ++diagnostic_sequence_;
  record.tick_ms = GetTickCount64();
  record.geometry_generation = geometry_generation_;
  record.stage = stage;
  record.message = message;
  record.wparam = static_cast<uint64_t>(wparam);
  record.result = static_cast<int64_t>(result);
  record.maximized = IsZoomed(owner_window_) != FALSE;
  record.custom_frame_enabled = custom_frame_enabled_;
  RECT client{};
  if (GetClientRect(owner_window_, &client)) {
    record.client_width = client.right - client.left;
    record.client_height = client.bottom - client.top;
  }
  record.dpi = GetDpiForWindow(owner_window_);
  diagnostics_[(record.sequence - 1) % diagnostics_.size()] = std::move(record);
  diagnostic_count_ = std::min(diagnostic_count_ + 1, diagnostics_.size());
}

std::vector<WindowChrome::DiagnosticRecord> WindowChrome::TakeDiagnostics() {
  std::vector<DiagnosticRecord> result;
  result.reserve(diagnostic_count_);
  const uint64_t first = diagnostic_sequence_ - diagnostic_count_;
  for (size_t index = 0; index < diagnostic_count_; ++index)
    result.push_back(diagnostics_[(first + index) % diagnostics_.size()]);
  diagnostic_count_ = 0;
  return result;
}
#endif

void WindowChrome::NotifyStateIfChanged() {
  if (frame_transition_) return;
  const State state = GetState();
  if (state == last_state_) return;
  last_state_ = state;
  if (state_changed_) state_changed_(state);
}

bool WindowChrome::HandleWindowMessage(HWND window, UINT message, WPARAM wparam,
                                      LPARAM lparam, LRESULT* result) {
  if (window != owner_window_) return false;
#ifdef CHASTEADY_WINDOW_DIAGNOSTICS
  if (message == WM_NCHITTEST || message == WM_NCLBUTTONDOWN || message == WM_NCLBUTTONUP ||
      message == WM_NCLBUTTONDBLCLK || message == WM_SYSCOMMAND || message == WM_SIZE ||
      message == WM_DPICHANGED || message == WM_CLOSE)
    RecordDiagnostic("owner-message", message, wparam);
#endif
  if (message == WM_DESTROY) {
    owner_destroying_ = true;
    custom_frame_enabled_ = false;
    ResetInteraction();
    RemoveChildSubclass();
    return false;
  }
  if (!custom_frame_enabled_) {
    // Stock-caption native windows still report system min/max/topmost changes.
    if (message == WM_SIZE || message == WM_WINDOWPOSCHANGED ||
        message == WM_STYLECHANGED) NotifyStateIfChanged();
    return false;
  }
  LRESULT handled_result = 0;
  switch (message) {
    case WM_NCCALCSIZE: {
      RECT* proposed = wparam != FALSE ?
          &reinterpret_cast<NCCALCSIZE_PARAMS*>(lparam)->rgrc[0] :
          reinterpret_cast<RECT*>(lparam);
      if (IsZoomed(window)) {
        MONITORINFO monitor{};
        if (GetMonitorInfoForRect(*proposed, &monitor)) {
          *proposed = monitor.rcWork;
        }
      }
      // Keep WS_OVERLAPPEDWINDOW; only remove its stock non-client painting.
      break;
    }
    case WM_GETMINMAXINFO: {
      DefWindowProc(window, message, wparam, lparam);
      auto* limits = reinterpret_cast<MINMAXINFO*>(lparam);
      MONITORINFO monitor{};
      monitor.cbSize = sizeof(monitor);
      if (GetMonitorInfo(MonitorFromWindow(window, MONITOR_DEFAULTTONEAREST),
                         &monitor)) {
        // Monitor-relative offsets work for monitors left/above the primary.
        limits->ptMaxPosition.x = monitor.rcWork.left - monitor.rcMonitor.left;
        limits->ptMaxPosition.y = monitor.rcWork.top - monitor.rcMonitor.top;
        limits->ptMaxSize.x = monitor.rcWork.right - monitor.rcWork.left;
        limits->ptMaxSize.y = monitor.rcWork.bottom - monitor.rcWork.top;
      }
      break;
    }
    case WM_NCHITTEST: {
      const POINT point{GET_X_LPARAM(lparam), GET_Y_LPARAM(lparam)};
      handled_result = HitTest(point);
#ifdef CHASTEADY_WINDOW_DIAGNOSTICS
      RecordDiagnostic("owner-hit", message, wparam, handled_result);
#endif
      break;
    }
    case WM_NCMOUSEMOVE: {
      maximize_button_hovered_ = wparam == HTMAXBUTTON;
      if (!maximize_button_hovered_) maximize_button_pressed_ = false;
      TRACKMOUSEEVENT track{};
      track.cbSize = sizeof(track);
      track.dwFlags = TME_LEAVE | TME_NONCLIENT;
      track.hwndTrack = window;
      TrackMouseEvent(&track);
      NotifyStateIfChanged();
      handled_result = DefWindowProc(window, message, wparam, lparam);
      break;
    }
    case WM_NCMOUSELEAVE:
      ResetInteraction();
      NotifyStateIfChanged();
      handled_result = DefWindowProc(window, message, wparam, lparam);
      break;
    case WM_NCLBUTTONDOWN:
    case WM_NCLBUTTONDBLCLK:
    case WM_NCLBUTTONUP:
    case WM_NCRBUTTONDOWN:
    case WM_NCRBUTTONUP:
    case WM_NCRBUTTONDBLCLK: {
      const std::shared_ptr<bool> alive = alive_;
      if (message == WM_NCLBUTTONDOWN && wparam == HTMAXBUTTON) {
        maximize_button_hovered_ = true;
        maximize_button_pressed_ = true;
        NotifyStateIfChanged();
      }
      // The OWN TOP-LEVEL default procedure gets the real NC messages. It is
      // the sole owner of maximize clicks/Snap, caption double-click/drag,
      // system menu, and border sizing. Flutter never sees a second click.
#ifdef CHASTEADY_WINDOW_DIAGNOSTICS
      RecordDiagnostic("nc-default-before", message, wparam);
#endif
      handled_result = DefWindowProc(window, message, wparam, lparam);
      if (*alive) {
#ifdef CHASTEADY_WINDOW_DIAGNOSTICS
        RecordDiagnostic("nc-default-after", message, wparam, handled_result);
#endif
        maximize_button_pressed_ = false;
        UpdateHoverFromCursor();
        NotifyStateIfChanged();
      }
      break;
    }
    case WM_CANCELMODE:
    case WM_CAPTURECHANGED:
      ResetInteraction();
      NotifyStateIfChanged();
      return false;
    case WM_NCACTIVATE:
      if (wparam == FALSE) {
        ResetInteraction();
        NotifyStateIfChanged();
      }
      return false;
    case WM_DPICHANGED:
      ResetInteraction();
      NotifyStateIfChanged();
      return false;  // Runner must apply the suggested DPI rectangle.
    case WM_SIZE:
      if (wparam == SIZE_MINIMIZED) ResetInteraction();
      NotifyStateIfChanged();
      return false;  // NEVER swallow Win32Window's Flutter child MoveWindow.
    case WM_WINDOWPOSCHANGED:
    case WM_STYLECHANGED:
      NotifyStateIfChanged();
      return false;
    default:
      return false;
  }
  if (result != nullptr) *result = handled_result;
  return true;
}

LRESULT CALLBACK WindowChrome::ChildSubclassProc(
    HWND window, UINT message, WPARAM wparam, LPARAM lparam,
    UINT_PTR subclass_id, DWORD_PTR reference_data) {
  auto* data = reinterpret_cast<ChildSubclassData*>(reference_data);
  WindowChrome* chrome = data == nullptr ? nullptr : data->chrome;
  if (message == WM_NCDESTROY) {
    RemoveWindowSubclass(window, ChildSubclassProc, subclass_id);
    if (chrome != nullptr) {
      chrome->child_subclass_ = nullptr;
      chrome->child_window_ = nullptr;
      chrome->ResetInteraction();
      if (chrome->custom_frame_enabled_ && !chrome->owner_destroying_) {
        chrome->RestoreStockFrame();
      }
    }
    delete data;
    return DefSubclassProc(window, message, wparam, lparam);
  }
  if (chrome != nullptr && chrome->custom_frame_enabled_) {
    if (message == WM_NCHITTEST) {
      // Documented same-thread HTTRANSPARENT semantics let the system repeat
      // hit testing on the parent. Returning the owner's HTMAXBUTTON on the
      // CHILD would incorrectly give the child the NC maximize/Snap messages.
      // SetWindowSubclass/DefSubclassProc leave Flutter's WNDPROC intact.
      const LRESULT hit = SendMessage(chrome->owner_window_, WM_NCHITTEST,
                                      wparam, lparam);
#ifdef CHASTEADY_WINDOW_DIAGNOSTICS
      chrome->RecordDiagnostic(hit != HTCLIENT && hit != HTNOWHERE ? "child-transparent" : "child-defer",
          message, wparam, hit != HTCLIENT && hit != HTNOWHERE ? HTTRANSPARENT : 0);
#endif
      if (hit != HTCLIENT && hit != HTNOWHERE) return HTTRANSPARENT;
    } else if (message == WM_MOUSEMOVE || message == WM_LBUTTONUP) {
      if (chrome->maximize_button_hovered_ || chrome->maximize_button_pressed_) {
        chrome->ResetInteraction();
        chrome->NotifyStateIfChanged();
      }
    }
  }
  return DefSubclassProc(window, message, wparam, lparam);
}

}  // namespace chasteady
