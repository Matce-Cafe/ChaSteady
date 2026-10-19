#ifndef CHASTEADY_UI_WINDOWS_RUNNER_NATIVE_LAUNCH_CONFIGURATION_H_
#define CHASTEADY_UI_WINDOWS_RUNNER_NATIVE_LAUNCH_CONFIGURATION_H_

#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>

#include <memory>
#include <string>
#include <vector>

namespace chasteady {

// 仅原生入口能创建启动配置；Dart、HTTP 与窗口消息均不能选择数据根。
class NativeLaunchConfiguration final {
 public:
  ~NativeLaunchConfiguration();
  NativeLaunchConfiguration(const NativeLaunchConfiguration&) = delete;
  NativeLaunchConfiguration& operator=(const NativeLaunchConfiguration&) = delete;

  // 无隔离参数时不解析、创建或修改默认数据目录，保持普通启动行为。
  static bool Prepare(const std::vector<std::wstring>& arguments,
                      const std::wstring& resource_root,
                      std::vector<std::wstring>* remaining_arguments,
                      std::shared_ptr<const NativeLaunchConfiguration>* configuration,
                      std::wstring* error);

  bool has_new_profile() const;
  const std::wstring& profile_root() const;
  // Worker 启动前再次核对 SID、目录身份、整条路径与保护 ACL，失败绝不回退。
  bool Revalidate(const std::wstring& resource_root) const;

 private:
  NativeLaunchConfiguration();
  class Impl;
  std::unique_ptr<Impl> impl_;
};

}  // namespace chasteady

#endif  // CHASTEADY_UI_WINDOWS_RUNNER_NATIVE_LAUNCH_CONFIGURATION_H_
