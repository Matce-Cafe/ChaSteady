#ifndef CHASTEADY_UI_WINDOWS_RUNNER_MEDIA_DROP_TARGET_H_
#define CHASTEADY_UI_WINDOWS_RUNNER_MEDIA_DROP_TARGET_H_

#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>
#include <oleidl.h>

#include <cstdint>
#include <functional>
#include <string>

namespace chasteady {

// 仅在 UI OLE STA 线程使用；只为本进程直属 Flutter child 注册 documented IDropTarget。
class MediaDropTarget final {
 public:
  struct Configuration {
    std::string target_id;
    int64_t generation = 0;
    double left = 0.0;
    double top = 0.0;
    double right = 0.0;
    double bottom = 0.0;
    double client_width = 0.0;
  };
  struct FileIdentity {
    DWORD volume = 0;
    DWORD index_high = 0;
    DWORD index_low = 0;
    DWORD size_high = 0;
    DWORD size_low = 0;
    FILETIME last_write{};
    bool operator==(const FileIdentity& other) const;
  };
  using Available = std::function<bool()>;
  using Dropped = std::function<void(const std::string&, int64_t, const std::string&)>;

  MediaDropTarget(HWND owner, HWND flutter_child, Available available, Dropped dropped);
  ~MediaDropTarget();
  MediaDropTarget(const MediaDropTarget&) = delete;
  MediaDropTarget& operator=(const MediaDropTarget&) = delete;

  bool Configure(bool enabled, const Configuration& configuration, std::string* error);
  void HandleWindowMessage(UINT message, WPARAM wparam, LPARAM lparam);
  void Disable();
  static bool IsValidConfiguration(const Configuration& configuration);
  // 与 OLE 注入 fixture 共用的 CF_HDROP 验收入口，不执行文件，也不替代 Worker 流验收。
  static bool ReadSingleMediaFile(IDataObject* object, std::string* path,
                                  FileIdentity* identity = nullptr);
#ifdef CHASTEADY_NATIVE_TESTING
  // 仅编译到测试目标，返回已 AddRef 的自有接收器；不提供外部窗口注入能力。
  IDropTarget* RetainTargetForTesting();
#endif

 private:
  class Impl;
  Impl* impl_ = nullptr;
};

}  // namespace chasteady

#endif  // CHASTEADY_UI_WINDOWS_RUNNER_MEDIA_DROP_TARGET_H_
