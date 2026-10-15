#ifndef CHASTEADY_UI_WINDOWS_RUNNER_NATIVE_MEDIA_H_
#define CHASTEADY_UI_WINDOWS_RUNNER_NATIVE_MEDIA_H_

#include <windows.h>

#include <cstdint>
#include <functional>
#include <memory>
#include <string>

#include <flutter/texture_registrar.h>

namespace chasteady {

// Typed native event/state shared with the Windows MethodChannel bridge.
// The bridge can encode these fields as a flutter::EncodableMap using the
// snake_case names below; this class deliberately does not depend on a channel
// codec or on the runner's window/messenger implementation.
struct NativeMediaEvent {
  std::string player_id;
  // Source can accept Play() before the first video frame is available.
  bool can_play = false;
  // True only after a real BGRA frame has transferred and been published.
  bool ready = false;
  bool playing = false;
  double position_seconds = 0.0;
  double duration_seconds = 0.0;
  double volume = 1.0;
  bool muted = true;
  bool ended = false;
  std::string error_code;
};

struct NativeMediaCreateResult {
  std::string player_id;
  int64_t texture_id = -1;
  bool can_play = false;
  std::string error_code;

  bool ok() const {
    return !player_id.empty() && texture_id >= 0 && error_code.empty();
  }
};

class NativeMediaManager final {
 public:
  // Event callbacks run on the manager's serialized media thread, not the
  // Flutter platform thread. A runner bridge must copy the borrowed event value
  // and marshal channel/UI work to its platform task runner. Callback
  // implementations should not block media processing or destroy this manager
  // reentrantly. The texture registrar must outlive this manager and all pending
  // asynchronous texture-unregistration callbacks.
  using EventCallback = std::function<void(const NativeMediaEvent&)>;

  explicit NativeMediaManager(flutter::TextureRegistrar* texture_registrar,
                              EventCallback event_callback);
  ~NativeMediaManager();

  NativeMediaManager(const NativeMediaManager&) = delete;
  NativeMediaManager& operator=(const NativeMediaManager&) = delete;
  NativeMediaManager(NativeMediaManager&&) = delete;
  NativeMediaManager& operator=(NativeMediaManager&&) = delete;

  // Takes ownership of owned_read_handle immediately, including on failure.
  // The caller must pass only the already-validated, duplicated, read-only
  // worker lease handle. This method never opens or resolves a path or URL.
  // The video output and Flutter texture retain the supplied native dimensions
  // (the UI should display the texture with contain/aspect-preserving fit).
  NativeMediaCreateResult Create(HANDLE owned_read_handle,
                                 int width,
                                 int height);

  bool Play(const std::string& player_id,
            std::string* error_code = nullptr);
  bool Pause(const std::string& player_id,
             std::string* error_code = nullptr);
  bool Seek(const std::string& player_id,
            double position_seconds,
            std::string* error_code = nullptr);
  bool SetVolume(const std::string& player_id,
                 double volume,
                 std::string* error_code = nullptr);
  bool SetMuted(const std::string& player_id,
                bool muted,
                std::string* error_code = nullptr);

  // Returns the latest serialized state snapshot. A false return indicates an
  // invalid argument, stopped manager, or unknown/disposed player; error_code
  // contains the corresponding stable native code.
  bool State(const std::string& player_id,
             NativeMediaEvent* state,
             std::string* error_code = nullptr);

  bool Dispose(const std::string& player_id,
               std::string* error_code = nullptr);
  void DisposeAll();

 private:
  class Core;
  std::shared_ptr<Core> core_;
};

}  // namespace chasteady

#endif  // CHASTEADY_UI_WINDOWS_RUNNER_NATIVE_MEDIA_H_
