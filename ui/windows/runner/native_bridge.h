#ifndef CHASTEADY_UI_WINDOWS_RUNNER_NATIVE_BRIDGE_H_
#define CHASTEADY_UI_WINDOWS_RUNNER_NATIVE_BRIDGE_H_

#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>

#include <memory>

namespace flutter {
class BinaryMessenger;
class TextureRegistrar;
}  // namespace flutter

namespace chasteady {

class NativeLaunchConfiguration;

// Windows MethodChannel bridge for chasteady/native. Construct it on the
// Flutter/platform thread after the owned HWND, parented Flutter child,
// BinaryMessenger, and texture registrar exist; destroy it before those runner
// objects. Custom chrome is opt-in and independent of managed worker shutdown.
class NativeBridge final {
 public:
  NativeBridge(HWND owner_window,
               HWND flutter_child,
               flutter::BinaryMessenger* messenger,
               flutter::TextureRegistrar* texture_registrar,
               std::shared_ptr<const NativeLaunchConfiguration> launch_configuration);
  ~NativeBridge();

  NativeBridge(const NativeBridge&) = delete;
  NativeBridge& operator=(const NativeBridge&) = delete;
  NativeBridge(NativeBridge&&) = delete;
  NativeBridge& operator=(NativeBridge&&) = delete;

  // Route this before the runner's default window procedure. Returns true when
  // the message was consumed and writes the corresponding LRESULT. This handles
  // the bridge's private PostMessage notifications and intercepts WM_CLOSE
  // until Dart confirms it has requested orderly worker shutdown.
  bool HandleWindowMessage(HWND window,
                           UINT message,
                           WPARAM wparam,
                           LPARAM lparam,
                           LRESULT* result);

  // Returns true when a close is pending/consumed; false only after Dart's
  // requestClose callback returned true following a successful requestShutdown.
  // MainWindow may call this from its close lifecycle instead of forwarding
  // WM_CLOSE through HandleWindowMessage.
  bool CloseRequest();

 private:
  class Impl;
  std::unique_ptr<Impl> impl_;
};

}  // namespace chasteady

#endif  // CHASTEADY_UI_WINDOWS_RUNNER_NATIVE_BRIDGE_H_
