// Optional standalone Win32 smoke test. It creates ONLY its own fixture HWNDs;
// it does not enumerate windows, send input, capture the screen, start Flutter,
// or start a worker. Not a substitute for interactive Windows 11 Snap/DPI tests.
#include "window_chrome.h"

#include <windowsx.h>

#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <limits>
#include <memory>
#include <string>

namespace {

constexpr wchar_t kFixtureClass[] = L"ChaSteady_WindowChromeSmoke";

void Check(bool condition, const char* description) {
  if (condition) return;
  std::fprintf(stderr, "FAIL: %s (Win32 error %lu)\n", description, GetLastError());
  std::exit(EXIT_FAILURE);
}

struct Fixture {
  HWND owner = nullptr;
  HWND child = nullptr;
  int state_events = 0;
  std::unique_ptr<chasteady::WindowChrome> chrome;

  ~Fixture() {
    chrome.reset();
    // Fixture teardown only. No application command destroys an HWND.
    if (owner != nullptr) DestroyWindow(owner);
    UnregisterClass(kFixtureClass, GetModuleHandle(nullptr));
  }
};

LRESULT CALLBACK FixtureProc(HWND window, UINT message,
                             WPARAM wparam, LPARAM lparam) {
  if (message == WM_NCCREATE) {
    const auto* create = reinterpret_cast<CREATESTRUCT*>(lparam);
    SetWindowLongPtr(window, GWLP_USERDATA,
                     reinterpret_cast<LONG_PTR>(create->lpCreateParams));
  }
  auto* fixture = reinterpret_cast<Fixture*>(
      GetWindowLongPtr(window, GWLP_USERDATA));
  if (fixture != nullptr && fixture->chrome != nullptr) {
    LRESULT result = 0;
    if (fixture->chrome->HandleWindowMessage(window, message, wparam, lparam,
                                             &result)) return result;
  }
  if (message == WM_SIZE && fixture != nullptr && fixture->child != nullptr) {
    RECT client{};
    GetClientRect(window, &client);
    MoveWindow(fixture->child, 0, 0, client.right, client.bottom, TRUE);
    return 0;
  }
  return DefWindowProc(window, message, wparam, lparam);
}

double Scale(HWND window) {
  const UINT dpi = GetDpiForWindow(window);
  return (dpi == 0 ? 96.0 : static_cast<double>(dpi)) / 96.0;
}

chasteady::WindowChrome::Geometry Layout(HWND window) {
  RECT rect{};
  Check(GetClientRect(window, &rect) != FALSE, "read fixture client size");
  chasteady::WindowChrome::Geometry geometry;
  geometry.title_bar_height = 48.0;
  geometry.client_width = static_cast<double>(rect.right) / Scale(window);
  geometry.controls_left = geometry.client_width - 192.0;
  geometry.maximize_left = geometry.client_width - 96.0;
  geometry.maximize_top = 0.0;
  geometry.maximize_width = 48.0;
  geometry.maximize_height = 48.0;
  return geometry;
}

LPARAM ScreenPoint(POINT point) {
  return MAKELPARAM(static_cast<WORD>(point.x), static_cast<WORD>(point.y));
}

LPARAM ClientPoint(HWND window, double x, double y) {
  const double scale = Scale(window);
  POINT point{static_cast<LONG>(std::lround(x * scale)),
              static_cast<LONG>(std::lround(y * scale))};
  Check(ClientToScreen(window, &point) != FALSE, "map fixture client point");
  return ScreenPoint(point);
}

LRESULT Hit(HWND window, LPARAM point) {
  return SendMessage(window, WM_NCHITTEST, 0, point);
}

void PureGeometryChecks() {
  chasteady::WindowChrome::Geometry geometry;
  geometry.title_bar_height = 48.0;
  geometry.client_width = 960.0;
  geometry.controls_left = 768.0;
  geometry.maximize_left = 864.0;
  geometry.maximize_width = 48.0;
  geometry.maximize_height = 48.0;
  Check(chasteady::WindowChrome::IsValidGeometry(geometry), "valid logical layout");
  auto invalid = geometry;
  invalid.controls_left = -1.0;
  Check(!chasteady::WindowChrome::IsValidGeometry(invalid), "reject negative controls");
  invalid = geometry;
  invalid.maximize_top = 40.0;
  Check(!chasteady::WindowChrome::IsValidGeometry(invalid), "reject button outside title bar");
  invalid = geometry;
  invalid.client_width = std::numeric_limits<double>::infinity();
  Check(!chasteady::WindowChrome::IsValidGeometry(invalid), "reject infinity");
  invalid = geometry;
  invalid.maximize_left = std::numeric_limits<double>::quiet_NaN();
  Check(!chasteady::WindowChrome::IsValidGeometry(invalid), "reject NaN");
  invalid = geometry;
  invalid.client_width = 1000000.0;
  Check(!chasteady::WindowChrome::IsValidGeometry(invalid), "reject unbounded layout");
}

void OwnedWindowChecks() {
  Fixture fixture;
  WNDCLASS window_class{};
  window_class.style = CS_DBLCLKS;
  window_class.lpfnWndProc = FixtureProc;
  window_class.hInstance = GetModuleHandle(nullptr);
  window_class.lpszClassName = kFixtureClass;
  Check(RegisterClass(&window_class) != 0, "register fixture class");
  fixture.owner = CreateWindowEx(0, kFixtureClass, L"ChaSteady native chrome smoke",
      WS_OVERLAPPEDWINDOW, 60, 60, 960, 640, nullptr, nullptr,
      GetModuleHandle(nullptr), &fixture);
  Check(fixture.owner != nullptr, "create owned fixture");
  // STATIC defaults to HTTRANSPARENT without SS_NOTIFY. Use client hits so
  // delegation checks exercise our subclass, not the base control's transparency.
  fixture.child = CreateWindowEx(0, L"STATIC", L"", WS_CHILD | WS_VISIBLE | SS_NOTIFY,
      0, 0, 1, 1, fixture.owner, nullptr, GetModuleHandle(nullptr), nullptr);
  Check(fixture.child != nullptr, "create same-thread fixture child");
  fixture.chrome = std::make_unique<chasteady::WindowChrome>(
      fixture.owner, fixture.child,
      [&fixture](const chasteady::WindowChrome::State&) { ++fixture.state_events; });
  Check(fixture.chrome->GetState().supported, "window capability independent of worker");
  Check(!fixture.chrome->GetState().custom_frame_enabled, "stock caption at startup");
  std::string error;
  Check(fixture.chrome->Configure(true, Layout(fixture.owner), &error),
        "post-layout frame opt-in may precede native Show callback");
  Check(fixture.chrome->GetState().custom_frame_enabled,
        "hidden valid opt-in is not permanently rejected");
  Check(fixture.chrome->Configure(false, {}, &error), "restore stock before fixture Show");

  // When explicitly run by the tester, this displays only this new fixture,
  // without activating or attaching to any existing application window.
  ShowWindow(fixture.owner, SW_SHOWNOACTIVATE);
  Check(fixture.chrome->Configure(true, Layout(fixture.owner), &error), "enable custom frame");
  auto geometry = Layout(fixture.owner);  // Frame expansion changes client size.
  Check(fixture.chrome->Configure(true, geometry, &error), "present updated logical layout");
  Check(fixture.chrome->GetState().custom_frame_enabled, "custom-frame state");
  Check((GetWindowLongPtr(fixture.owner, GWL_STYLE) & WS_OVERLAPPEDWINDOW) ==
            WS_OVERLAPPEDWINDOW, "preserve resize/sysmenu/min/max styles");
  const LPARAM caption = ClientPoint(fixture.owner, 80.0, 24.0);
  const LPARAM maximize = ClientPoint(fixture.owner, geometry.maximize_left + 24.0, 24.0);
  const LPARAM pin = ClientPoint(fixture.owner, geometry.controls_left + 24.0, 24.0);
  Check(Hit(fixture.owner, caption) == HTCAPTION, "caption native hit");
  Check(Hit(fixture.owner, maximize) == HTMAXBUTTON, "real owner HTMAXBUTTON for Snap");
  Check(Hit(fixture.owner, pin) == HTCLIENT, "other controls stay Flutter client");
  Check(Hit(fixture.child, maximize) == HTTRANSPARENT, "child delegates max hit to owner");
  Check(Hit(fixture.child, caption) == HTTRANSPARENT, "child delegates caption hit to owner");
  Check(Hit(fixture.child, pin) == HTCLIENT, "child retains Flutter control hits");

  RECT outer{};
  Check(GetWindowRect(fixture.owner, &outer) != FALSE, "read fixture outer bounds");
  Check(Hit(fixture.owner, ScreenPoint({outer.left + 1, outer.top + 1})) == HTTOPLEFT,
        "top left system sizing");
  Check(Hit(fixture.owner, ScreenPoint({outer.left + 1, outer.top + 120})) == HTLEFT,
        "left edge sizing outranks caption");
  Check(Hit(fixture.child, ScreenPoint({outer.left + 1, outer.top + 120})) == HTTRANSPARENT,
        "child does not hide sizing edge");

  auto stale = geometry;
  stale.client_width += 20.0;
  Check(fixture.chrome->Configure(true, stale, &error), "accept bounded stale layout");
  Check(Hit(fixture.owner, maximize) == HTCLIENT, "no invisible stale max hit target");
  Check(fixture.chrome->Configure(true, geometry, &error), "refresh max hit target");

  // Shrink the real fixture while native still has the old wider layout. The
  // new right-hand buttons now occupy part of the OLD caption partition.
  const int narrow_width = static_cast<int>((outer.right - outer.left) * 3 / 4);
  Check(SetWindowPos(fixture.owner, nullptr, 0, 0, narrow_width,
                    outer.bottom - outer.top,
                    SWP_NOMOVE | SWP_NOZORDER | SWP_NOACTIVATE) != FALSE,
        "shrink own fixture without updating native geometry");
  const auto narrow_geometry = Layout(fixture.owner);
  Check(narrow_geometry.client_width < geometry.client_width,
        "fixture has a narrower actual client than configured layout");
  const double control_centers[] = {24.0, 72.0, 120.0, 168.0};
  for (double offset : control_centers) {
    const LPARAM shifted_control = ClientPoint(
        fixture.owner, narrow_geometry.controls_left + offset, 24.0);
    Check(Hit(fixture.owner, shifted_control) == HTCLIENT,
          "stale caption does not swallow shifted pin/min/max/close controls");
    Check(Hit(fixture.child, shifted_control) == HTCLIENT,
          "child retains shifted control hits while native geometry is stale");
  }
  const double narrow_caption_x = narrow_geometry.controls_left / 2.0;
  Check(Hit(fixture.owner, ClientPoint(fixture.owner, narrow_caption_x, 24.0)) == HTCLIENT,
        "stale width temporarily suspends caption hits too");
  Check(Hit(fixture.owner, ScreenPoint({outer.left + 1, outer.top + 120})) == HTLEFT,
        "stale width preserves system sizing edges");
  Check(fixture.chrome->Configure(true, narrow_geometry, &error),
        "present narrower title-bar geometry");
  Check(Hit(fixture.owner, ClientPoint(fixture.owner, narrow_caption_x, 24.0)) == HTCAPTION,
        "fresh narrower layout restores caption hits");
  Check(Hit(fixture.owner, ClientPoint(
        fixture.owner, narrow_geometry.maximize_left + 24.0, 24.0)) == HTMAXBUTTON,
        "fresh narrower layout restores maximize hits");
  Check(SetWindowPos(fixture.owner, nullptr, 0, 0, outer.right - outer.left,
                    outer.bottom - outer.top,
                    SWP_NOMOVE | SWP_NOZORDER | SWP_NOACTIVATE) != FALSE,
        "restore own fixture width after stale-caption regression");
  geometry = Layout(fixture.owner);
  Check(fixture.chrome->Configure(true, geometry, &error), "refresh restored fixture geometry");

  Check(SetWindowPos(fixture.owner, nullptr, -500, -180, 0, 0,
                    SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE) != FALSE,
        "place own fixture at negative screen X/Y");
  Check(Hit(fixture.owner, ClientPoint(fixture.owner, 80.0, 24.0)) == HTCAPTION,
        "signed negative-coordinate hit testing");
  Check(SetWindowPos(fixture.owner, nullptr, outer.left, outer.top, 0, 0,
                    SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE) != FALSE,
        "return own fixture to original monitor");

  Check(fixture.chrome->ToggleMaximize(&error), "maximize owned fixture");
  Check(IsZoomed(fixture.owner) && fixture.chrome->GetState().maximized,
        "maximized state comes from Win32");
  MONITORINFO monitor{};
  monitor.cbSize = sizeof(monitor);
  Check(GetMonitorInfo(MonitorFromWindow(fixture.owner, MONITOR_DEFAULTTONEAREST),
                       &monitor) != FALSE, "read maximized monitor work area");
  RECT client{};
  Check(GetClientRect(fixture.owner, &client) != FALSE, "read maximized client");
  POINT start{client.left, client.top};
  POINT end{client.right, client.bottom};
  ClientToScreen(fixture.owner, &start);
  ClientToScreen(fixture.owner, &end);
  Check(start.x >= monitor.rcWork.left && start.y >= monitor.rcWork.top &&
        end.x <= monitor.rcWork.right && end.y <= monitor.rcWork.bottom,
        "maximized client stays inside taskbar work area");
  Check(fixture.chrome->ToggleMaximize(&error), "restore owned fixture");
  Check(!fixture.chrome->GetState().maximized, "restored system state");
  Check(fixture.chrome->SetAlwaysOnTop(true, &error), "pin owned fixture");
  Check(fixture.chrome->GetState().always_on_top, "query system topmost flag");
  const int pinned_events = fixture.state_events;
  Check(fixture.chrome->SetAlwaysOnTop(true, &error), "idempotent pin");
  Check(fixture.state_events == pinned_events, "deduplicate unchanged state");
  Check(fixture.chrome->SetAlwaysOnTop(false, &error), "unpin owned fixture");

  const int events_before_size = fixture.state_events;
  for (int index = 0; index < 100; ++index) {
    SendMessage(fixture.owner, WM_SIZE, SIZE_RESTORED, 0);
  }
  Check(fixture.state_events == events_before_size, "no state event resize flood");
  RECT child_rect{};
  Check(GetClientRect(fixture.owner, &client) != FALSE, "read resized client");
  Check(GetClientRect(fixture.child, &child_rect) != FALSE, "read resized child");
  Check(client.right == child_rect.right && client.bottom == child_rect.bottom,
        "WM_SIZE still reaches child resize handler");

  geometry = Layout(fixture.owner);
  Check(fixture.chrome->Minimize(&error), "minimize owned fixture");
  Check(IsIconic(fixture.owner) != FALSE, "system minimized fixture");
  Check(fixture.chrome->Configure(true, geometry, &error),
        "geometry update while minimized does not lose frame");
  ShowWindow(fixture.owner, SW_RESTORE);
  geometry = Layout(fixture.owner);
  geometry.maximize_width = -1.0;
  Check(!fixture.chrome->Configure(true, geometry, &error), "invalid update fails closed");
  Check(!fixture.chrome->GetState().custom_frame_enabled, "invalid layout restores stock caption");
  Check(Hit(fixture.child, ClientPoint(fixture.owner, 80.0, 24.0)) == HTCLIENT,
        "subclass removed on fallback");
  Check(fixture.chrome->Configure(true, Layout(fixture.owner), &error), "re-enable frame after fallback");
  Check(fixture.chrome->Configure(false, {}, &error), "disable custom frame");
  Check(!fixture.chrome->GetState().custom_frame_enabled, "stock frame after disable");
  Check(Hit(fixture.child, ClientPoint(fixture.owner, 80.0, 24.0)) == HTCLIENT,
        "subclass removed on explicit disable");
  std::printf("PASS: geometry, startup stock frame, owned hit testing, signed coordinates, "
              "min/max/restore, topmost, work area, deduplicated state, child resize, teardown.\n");
}

}  // namespace

int main() {
  PureGeometryChecks();
  OwnedWindowChecks();
  return EXIT_SUCCESS;
}
