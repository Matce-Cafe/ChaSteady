#include "window_chrome.h"

#include <commctrl.h>
#include <dwmapi.h>
#include <windowsx.h>

#include <algorithm>
#include <cmath>
#include <new>
#include <limits>
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
  destructing_ = true;
  closing_ = true;
  state_changed_ = nullptr;
  CancelMaximizePress();
  if (custom_frame_enabled_ && !owner_destroying_) RestoreStockFrame();
  else RemoveChildSubclass();
  *alive_ = false;
  if (child_subclass_ != nullptr) {
    child_subclass_->chrome = nullptr;
    child_subclass_ = nullptr;
  }
}

bool WindowChrome::HasOwnedWindows() const {
  if (owner_destroying_ || destructing_ || !IsCurrentThreadWindow(owner_window_) ||
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
  const auto alive = alive_;
  if (!CancelMaximizePress()) return false;
  frame_transition_ = true;
  custom_frame_enabled_ = false;
  geometry_ = Geometry{};
  bool restored = true;
  if (!owner_destroying_ && IsCurrentThreadWindow(owner_window_)) {
    const MARGINS margins{0, 0, 0, 0};
    const HRESULT dwm_result = DwmExtendFrameIntoClientArea(owner_window_, &margins);
    if (!*alive) return false;
    const bool recalculated = RecalculateFrame(owner_window_);
    if (!*alive) return false;
    restored = SUCCEEDED(dwm_result) && recalculated;
    RedrawWindow(owner_window_, nullptr, nullptr, RDW_FRAME | RDW_INVALIDATE | RDW_ALLCHILDREN);
    if (!*alive) return false;
  }
  const bool removed = RemoveChildSubclass();
  frame_transition_ = false;
  NotifyStateIfChanged();
  return restored && removed;
}

bool WindowChrome::Configure(bool enabled, const Geometry& geometry, std::string* error) {
  const auto alive = alive_;
#ifdef CHASTEADY_WINDOW_DIAGNOSTICS
  ++geometry_generation_;
  RecordDiagnostic(enabled ? "configure-enabled" : "configure-disabled");
#endif
  if (error) error->clear();
  const bool same_layout = enabled && custom_frame_enabled_ &&
      geometry.title_bar_height == geometry_.title_bar_height && geometry.controls_left == geometry_.controls_left &&
      geometry.client_width == geometry_.client_width && geometry.maximize_left == geometry_.maximize_left &&
      geometry.maximize_top == geometry_.maximize_top && geometry.maximize_width == geometry_.maximize_width &&
      geometry.maximize_height == geometry_.maximize_height;
  if (!same_layout && !CancelMaximizePress()) return Fail(error, "window_unavailable");
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
    geometry_ = geometry;
    UpdateHoverFromCursor();
    NotifyStateIfChanged();
    return true;
  }
  if (!InstallChildSubclass()) return Fail(error, "window_chrome_unavailable");
  geometry_ = geometry;
  frame_transition_ = true;
  custom_frame_enabled_ = true;
  const MARGINS margins{1, 1, 1, 1};
  const HRESULT result = DwmExtendFrameIntoClientArea(owner_window_, &margins);
  if (!*alive) return Fail(error, "window_unavailable");
  const bool recalculated = RecalculateFrame(owner_window_);
  if (!*alive) return Fail(error, "window_unavailable");
  if (FAILED(result) || !recalculated) {
    const bool restored = RestoreStockFrame();
    return Fail(error, restored ? "window_chrome_failed" : "window_chrome_restore_failed");
  }
  frame_transition_ = false;
  UpdateHoverFromCursor();
  NotifyStateIfChanged();
  return true;
}

bool WindowChrome::CanCommand(std::string* error) const {
  if (error) error->clear();
  if (closing_ || destructing_ || !HasOwnedWindows() || !IsWindowVisible(owner_window_) ||
      !IsWindowEnabled(owner_window_)) return Fail(error, "window_unavailable");
  return true;
}

bool WindowChrome::Minimize(std::string* error) {
  const auto alive = alive_;
  const HWND owner = owner_window_;
  if (!CanCommand(error) || !ResetInteraction()) return false;
  ShowWindow(owner, SW_MINIMIZE);
  if (!*alive) return false;
  const bool minimized = IsIconic(owner) != FALSE;
  NotifyStateIfChanged();
  return minimized || Fail(error, "window_command_failed");
}

bool WindowChrome::ToggleMaximize(std::string* error) {
  const auto alive = alive_;
  if (!CancelMaximizePress() || !*alive || !CanCommand(error)) return false;
  const bool was_maximized = IsZoomed(owner_window_) != FALSE;
  return SubmitMaximize(was_maximized, 0, error);
}

bool WindowChrome::SetAlwaysOnTop(bool value, std::string* error) {
  const auto alive = alive_;
  if (!CanCommand(error)) return false;
  if (!SetWindowPos(owner_window_, value ? HWND_TOPMOST : HWND_NOTOPMOST, 0, 0, 0, 0,
                    SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)) return Fail(error, "window_command_failed");
  if (!*alive) return false;
  const bool changed = GetState().always_on_top == value;
  NotifyStateIfChanged();
  return changed || Fail(error, "window_command_failed");
}

bool WindowChrome::StartDrag(std::string* error) {
  const auto alive = alive_;
  if (!CanCommand(error) || IsIconic(owner_window_)) return Fail(error, "window_unavailable");
  POINT cursor{};
  if (!GetCursorPos(&cursor) || !ResetInteraction() || !*alive || GetCapture() != nullptr)
    return Fail(error, "window_command_failed");
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

bool WindowChrome::AdvanceInteractionEpoch() {
  if (interaction_epoch_ == std::numeric_limits<uint64_t>::max()) {
    closing_ = true;
    return false;
  }
  ++interaction_epoch_;
  return true;
}

bool WindowChrome::CancelMaximizePress(bool release_owned) {
  const auto alive = alive_;
  const HWND owner = owner_window_;
  const bool claimed = capture_claimed_;
  AdvanceInteractionEpoch();
  const uint64_t cancelled_epoch = interaction_epoch_;
  press_phase_ = PressPhase::kIdle;
  press_ = PressSnapshot{};
  capture_claimed_ = false;
  capture_confirmed_ = false;
  maximize_button_hovered_ = false;
  maximize_button_pressed_ = false;
  if (release_owned && claimed && GetCapture() == owner) {
    const bool was_releasing = releasing_capture_;
    releasing_capture_ = true;
    const BOOL released = ReleaseCapture();
    if (!*alive) return false;
    releasing_capture_ = was_releasing;
    // 失败只保留同一代的自有清理责任；不把重入后新的 capture 认作旧责任。
    if (!released && interaction_epoch_ == cancelled_epoch && GetCapture() == owner)
      capture_claimed_ = true;
  }
  return *alive;
}

void WindowChrome::SetClosing(bool closing) {
  if (!*alive_ || !IsCurrentThreadWindow(owner_window_)) return;
  if (closing_ == closing && (!closing || !capture_claimed_)) return;
  const auto alive = alive_;
  closing_ = closing;
  if (!CancelMaximizePress() || !*alive) return;
  NotifyStateIfChanged();
}

bool WindowChrome::HasActiveMaximizeCapture() const {
  return *alive_ && !closing_ && !destructing_ &&
      press_phase_ != PressPhase::kIdle && capture_claimed_ && capture_confirmed_ &&
      press_.epoch == interaction_epoch_ && HasOwnedWindows() && GetCapture() == owner_window_;
}

uint64_t WindowChrome::ActiveMaximizePressEpoch() const {
  return HasActiveMaximizeCapture() ? press_.epoch : 0;
}

bool WindowChrome::MaximizePressEligible(POINT screen) const {
  return !closing_ && !destructing_ && custom_frame_enabled_ && HasOwnedWindows() &&
      IsWindowVisible(owner_window_) && IsWindowVisible(child_window_) &&
      IsWindowEnabled(owner_window_) && IsWindowEnabled(child_window_) &&
      !IsIconic(owner_window_) && GetForegroundWindow() == owner_window_ &&
      IsValidGeometry(geometry_) && GetDpiForWindow(owner_window_) != 0 &&
      HitTest(screen) == HTMAXBUTTON;
}

bool WindowChrome::PressSnapshotCurrent(const PressSnapshot& snapshot) const {
  RECT client{};
  return snapshot.epoch != 0 && snapshot.epoch == interaction_epoch_ &&
      !closing_ && !destructing_ && custom_frame_enabled_ && HasOwnedWindows() &&
      IsWindowVisible(owner_window_) && IsWindowVisible(child_window_) &&
      IsWindowEnabled(owner_window_) && IsWindowEnabled(child_window_) &&
      !IsIconic(owner_window_) && GetForegroundWindow() == owner_window_ &&
      GetDpiForWindow(owner_window_) == snapshot.dpi &&
      GetWindowLongPtr(owner_window_, GWL_STYLE) == snapshot.style &&
      (IsZoomed(owner_window_) != FALSE) == snapshot.maximized &&
      GetClientRect(owner_window_, &client) &&
      client.right - client.left == snapshot.client_width &&
      client.bottom - client.top == snapshot.client_height;
}

bool WindowChrome::BeginMaximizePress(POINT screen) {
  const auto alive = alive_;
  if (press_phase_ != PressPhase::kIdle || capture_claimed_) {
    if (CancelMaximizePress() && *alive) NotifyStateIfChanged();
    return false;
  }
  if (acquiring_capture_ || releasing_capture_ || command_in_progress_ ||
      !MaximizePressEligible(screen) || GetCapture() != nullptr) return false;
  RECT client{};
  if (!GetClientRect(owner_window_, &client) || !AdvanceInteractionEpoch()) return false;
  PressSnapshot snapshot;
  snapshot.epoch = interaction_epoch_;
  snapshot.maximized = IsZoomed(owner_window_) != FALSE;
  snapshot.dpi = GetDpiForWindow(owner_window_);
  snapshot.style = GetWindowLongPtr(owner_window_, GWL_STYLE);
  snapshot.client_width = client.right - client.left;
  snapshot.client_height = client.bottom - client.top;
  press_ = snapshot;
  press_phase_ = PressPhase::kPressedInside;
  capture_claimed_ = true;
  capture_confirmed_ = false;
  acquiring_capture_ = true;
  SetCapture(owner_window_);
  if (!*alive) return false;
  acquiring_capture_ = false;
  if (!PressSnapshotCurrent(snapshot) || press_phase_ == PressPhase::kIdle ||
      !capture_claimed_ || GetCapture() != owner_window_) {
    if (CancelMaximizePress() && *alive) NotifyStateIfChanged();
    return false;
  }
  capture_confirmed_ = true;
  maximize_button_hovered_ = true;
  maximize_button_pressed_ = true;
  NotifyStateIfChanged();
  return *alive;
}

bool WindowChrome::MoveMaximizePress(POINT screen) {
  const auto alive = alive_;
  if (!PressSnapshotCurrent(press_) || GetCapture() != owner_window_ || !capture_confirmed_) {
    if (CancelMaximizePress(GetCapture() == owner_window_) && *alive) NotifyStateIfChanged();
    return false;
  }
  const bool inside = MaximizePressEligible(screen);
  press_phase_ = inside ? PressPhase::kPressedInside : PressPhase::kPressedOutside;
  maximize_button_hovered_ = inside;
  maximize_button_pressed_ = inside;
  NotifyStateIfChanged();
  return *alive;
}

bool WindowChrome::SubmitMaximize(bool was_maximized, uint64_t expected_epoch, std::string* error) {
  const auto alive = alive_;
  const HWND owner = owner_window_;
  if (command_in_progress_ || acquiring_capture_ || releasing_capture_ ||
      (expected_epoch != 0 && expected_epoch != interaction_epoch_) || !CanCommand(error) ||
      IsIconic(owner) || GetCapture() != nullptr ||
      (IsZoomed(owner) != FALSE) != was_maximized) return Fail(error, "window_unavailable");
  if (!AdvanceInteractionEpoch()) return Fail(error, "window_unavailable");
  command_in_progress_ = true;
  // 鼠标和显式 Toggle 的唯一同步提交点；从不补第二次 toggle。
  SendMessage(owner, WM_SYSCOMMAND, was_maximized ? SC_RESTORE : SC_MAXIMIZE, 0);
  if (!*alive) return false;
  command_in_progress_ = false;
  const bool changed = (IsZoomed(owner) != FALSE) != was_maximized && !IsIconic(owner);
  NotifyStateIfChanged();
  return changed || Fail(error, "window_command_failed");
}

bool WindowChrome::EndMaximizePress(POINT screen) {
  const auto alive = alive_;
  if (press_phase_ == PressPhase::kIdle) {
    if (capture_claimed_ && !releasing_capture_ && CancelMaximizePress() && *alive) NotifyStateIfChanged();
    return false;
  }
  const PressSnapshot snapshot = press_;
  const bool valid = capture_confirmed_ && capture_claimed_ && GetCapture() == owner_window_ &&
      press_phase_ == PressPhase::kPressedInside && PressSnapshotCurrent(snapshot) &&
      MaximizePressEligible(screen);
  // 在可能重入的 ReleaseCapture 之前清 active；重复 UP 没有第二个提交能力。
  press_phase_ = PressPhase::kIdle;
  capture_confirmed_ = false;
  maximize_button_pressed_ = false;
  maximize_button_hovered_ = false;
  const bool had_claim = capture_claimed_;
  BOOL released = FALSE;
  if (had_claim && GetCapture() == owner_window_) {
    releasing_capture_ = true;
    released = ReleaseCapture();
    if (!*alive) return false;
    releasing_capture_ = false;
  }
  if (GetCapture() != owner_window_) capture_claimed_ = false;
  if (!released && had_claim && interaction_epoch_ == snapshot.epoch && GetCapture() == owner_window_) {
    // release 失败仍保留可证明的本代自有清理责任，但不再保留点击提交能力。
    AdvanceInteractionEpoch();
    press_ = PressSnapshot{};
    capture_claimed_ = true;
    NotifyStateIfChanged();
    return false;
  }
  if (!valid || !released || interaction_epoch_ != snapshot.epoch ||
      !PressSnapshotCurrent(snapshot) || !MaximizePressEligible(screen) || GetCapture() != nullptr) {
    if (CancelMaximizePress(false) && *alive) NotifyStateIfChanged();
    return false;
  }
  capture_claimed_ = false;
  return SubmitMaximize(snapshot.maximized, snapshot.epoch, nullptr);
}

bool WindowChrome::ResetInteraction() {
  return CancelMaximizePress();
}

void WindowChrome::UpdateHoverFromCursor() {
  if (press_phase_ != PressPhase::kIdle) return;
  POINT cursor{};
  maximize_button_hovered_ = !closing_ && custom_frame_enabled_ &&
      GetCursorPos(&cursor) && HitTest(cursor) == HTMAXBUTTON;
  maximize_button_pressed_ = false;
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
  if (frame_transition_ || destructing_) return;
  const State state = GetState();
  if (state == last_state_) return;
  last_state_ = state;
  // 副本存活到回调返回，允许回调同步销毁本 helper。
  const StateChanged callback = state_changed_;
  if (callback) callback(state);
}

bool WindowChrome::HandleWindowMessage(HWND window, UINT message, WPARAM wparam, LPARAM lparam, LRESULT* result) {
  if (window != owner_window_ || !*alive_) return false;
  const auto alive = alive_;
  auto consumed = [result]() { if (result) *result = 0; return true; };
#ifdef CHASTEADY_WINDOW_DIAGNOSTICS
  if (message == WM_NCHITTEST || message == WM_NCLBUTTONDOWN || message == WM_NCLBUTTONUP ||
      message == WM_NCLBUTTONDBLCLK || message == WM_SYSCOMMAND || message == WM_SIZE ||
      message == WM_DPICHANGED || message == WM_CLOSE) RecordDiagnostic("owner-message", message, wparam);
#endif
  if (message == WM_DESTROY || message == WM_NCDESTROY) {
    owner_destroying_ = true;
    closing_ = true;
    if (!CancelMaximizePress()) return false;
    custom_frame_enabled_ = false;
    RemoveChildSubclass();
    return false;
  }
  if (message == WM_CLOSE) { SetClosing(true); return false; }
  if (message == WM_CAPTURECHANGED) {
    // 正常自有 release 的通知不取消待提交 token；任何新 capture 或真正失捕获都取消。
    if (releasing_capture_ && press_phase_ == PressPhase::kIdle && lparam == 0) return false;
    if (CancelMaximizePress(false) && *alive) NotifyStateIfChanged();
    return false;
  }
  const bool cancel = message == WM_CANCELMODE || message == WM_DPICHANGED || message == WM_SIZE ||
      message == WM_STYLECHANGING || message == WM_STYLECHANGED || message == WM_WINDOWPOSCHANGING ||
      message == WM_WINDOWPOSCHANGED || (message == WM_ENABLE && !wparam) ||
      (message == WM_SHOWWINDOW && !wparam) || (message == WM_ACTIVATE && LOWORD(wparam) == WA_INACTIVE) ||
      (message == WM_NCACTIVATE && !wparam);
  if (cancel) {
    if (CancelMaximizePress() && *alive) NotifyStateIfChanged();
    return false;  // 尤其 SIZE/DPI 必须继续让 runner 处理子窗口和建议矩形。
  }
  if (message == WM_SYSCOMMAND) {
    const UINT command = static_cast<UINT>(wparam) & 0xfff0;
    const bool max_or_restore = command == SC_MAXIMIZE || command == SC_RESTORE;
    if (closing_ && max_or_restore) return consumed();
    if (!CancelMaximizePress()) return consumed();
    const uint64_t cancelled_epoch = interaction_epoch_;
    const bool qualified_before_notify = !max_or_restore || CanCommand(nullptr);
    NotifyStateIfChanged();
    if (!*alive) return consumed();
    // 通知可以关开窗口或改变布局；只阻止 MAX/RESTORE 的资格变化，不套用鼠标/最小化门禁。
    if (max_or_restore && (closing_ || interaction_epoch_ != cancelled_epoch ||
        CanCommand(nullptr) != qualified_before_notify)) return consumed();
    return false;
  }
  if (!custom_frame_enabled_) return false;
  if ((message == WM_NCLBUTTONDOWN || message == WM_NCLBUTTONDBLCLK) && wparam == HTMAXBUTTON) {
    BeginMaximizePress(POINT{GET_X_LPARAM(lparam), GET_Y_LPARAM(lparam)});
    return consumed();  // 自定义按钮只走捕获路线，绝不再交给默认 NC 按钮循环。
  }
  const bool moving = message == WM_MOUSEMOVE || message == WM_NCMOUSEMOVE;
  const bool up = message == WM_LBUTTONUP || message == WM_NCLBUTTONUP;
  if ((press_phase_ != PressPhase::kIdle || capture_claimed_) && (moving || up)) {
    POINT point{GET_X_LPARAM(lparam), GET_Y_LPARAM(lparam)};
    const bool client = message == WM_MOUSEMOVE || message == WM_LBUTTONUP;
    if (client && !ClientToScreen(owner_window_, &point)) {
      if (CancelMaximizePress() && *alive) NotifyStateIfChanged();
      return consumed();
    }
    if (moving && press_phase_ != PressPhase::kIdle) MoveMaximizePress(point);
    else if (up) EndMaximizePress(point);
    return consumed();
  }
  if (message == WM_NCLBUTTONUP && wparam == HTMAXBUTTON) return consumed();
  LRESULT handled = 0;
  switch (message) {
    case WM_NCCALCSIZE: {
      RECT* proposed = wparam ? &reinterpret_cast<NCCALCSIZE_PARAMS*>(lparam)->rgrc[0] : reinterpret_cast<RECT*>(lparam);
      if (IsZoomed(window)) { MONITORINFO monitor{}; if (GetMonitorInfoForRect(*proposed, &monitor)) *proposed = monitor.rcWork; }
      break;
    }
    case WM_GETMINMAXINFO: {
      DefWindowProc(window, message, wparam, lparam);
      if (!*alive) return consumed();
      auto* limits = reinterpret_cast<MINMAXINFO*>(lparam);
      MONITORINFO monitor{}; monitor.cbSize = sizeof(monitor);
      if (GetMonitorInfo(MonitorFromWindow(window, MONITOR_DEFAULTTONEAREST), &monitor)) {
        limits->ptMaxPosition.x = monitor.rcWork.left - monitor.rcMonitor.left;
        limits->ptMaxPosition.y = monitor.rcWork.top - monitor.rcMonitor.top;
        limits->ptMaxSize.x = monitor.rcWork.right - monitor.rcWork.left;
        limits->ptMaxSize.y = monitor.rcWork.bottom - monitor.rcWork.top;
      }
      break;
    }
    case WM_NCHITTEST:
      handled = HitTest(POINT{GET_X_LPARAM(lparam), GET_Y_LPARAM(lparam)});
#ifdef CHASTEADY_WINDOW_DIAGNOSTICS
      RecordDiagnostic("owner-hit", message, wparam, handled);
#endif
      break;
    case WM_NCMOUSEMOVE: {
      maximize_button_hovered_ = !closing_ && wparam == HTMAXBUTTON;
      TRACKMOUSEEVENT track{}; track.cbSize = sizeof(track); track.dwFlags = TME_LEAVE | TME_NONCLIENT; track.hwndTrack = window;
      TrackMouseEvent(&track);
      NotifyStateIfChanged();
      if (!*alive) return consumed();
      handled = DefWindowProc(window, message, wparam, lparam);
      break;
    }
    case WM_NCMOUSELEAVE:
      if (press_phase_ != PressPhase::kIdle) return consumed();
      if (!ResetInteraction()) return consumed();
      NotifyStateIfChanged();
      if (!*alive) return consumed();
      handled = DefWindowProc(window, message, wparam, lparam);
      break;
    case WM_NCLBUTTONDOWN:
    case WM_NCLBUTTONDBLCLK:
    case WM_NCLBUTTONUP:
    case WM_NCRBUTTONDOWN:
    case WM_NCRBUTTONUP:
    case WM_NCRBUTTONDBLCLK:
      if (!ResetInteraction()) return consumed();
      handled = DefWindowProc(window, message, wparam, lparam);
      if (!*alive) return consumed();
      UpdateHoverFromCursor();
      NotifyStateIfChanged();
      break;
    default: return false;
  }
  if (result) *result = handled;
  return true;
}

LRESULT CALLBACK WindowChrome::ChildSubclassProc(HWND window, UINT message, WPARAM wparam, LPARAM lparam,
                                                UINT_PTR subclass_id, DWORD_PTR reference_data) {
  auto* data = reinterpret_cast<ChildSubclassData*>(reference_data);
  WindowChrome* chrome = data == nullptr ? nullptr : data->chrome;
  if (message == WM_NCDESTROY) {
    RemoveWindowSubclass(window, ChildSubclassProc, subclass_id);
    if (chrome) {
      const auto alive = chrome->alive_;
      chrome->child_subclass_ = nullptr;
      chrome->child_window_ = nullptr;
      if (chrome->CancelMaximizePress() && *alive && chrome->custom_frame_enabled_ && !chrome->owner_destroying_)
        chrome->RestoreStockFrame();
    }
    delete data;
    return DefSubclassProc(window, message, wparam, lparam);
  }
  if (chrome && ((message == WM_ENABLE && !wparam) || (message == WM_SHOWWINDOW && !wparam))) {
    const auto alive = chrome->alive_;
    if (chrome->CancelMaximizePress() && *alive) chrome->NotifyStateIfChanged();
    return DefSubclassProc(window, message, wparam, lparam);
  }
  if (chrome && chrome->custom_frame_enabled_ && message == WM_NCHITTEST) {
    const auto alive = chrome->alive_;
    const HWND owner = chrome->owner_window_;
    const LRESULT hit = SendMessage(owner, WM_NCHITTEST, wparam, lparam);
    if (!*alive) return DefSubclassProc(window, message, wparam, lparam);
#ifdef CHASTEADY_WINDOW_DIAGNOSTICS
    chrome->RecordDiagnostic(hit != HTCLIENT && hit != HTNOWHERE ? "child-transparent" : "child-defer",
        message, wparam, hit != HTCLIENT && hit != HTNOWHERE ? HTTRANSPARENT : 0);
#endif
    if (hit != HTCLIENT && hit != HTNOWHERE) return HTTRANSPARENT;
  }
  return DefSubclassProc(window, message, wparam, lparam);
}

}  // namespace chasteady
