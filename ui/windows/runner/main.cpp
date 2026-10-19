#include <flutter/dart_project.h>
#include <flutter/flutter_view_controller.h>
#include <windows.h>
#include <ole2.h>
#include <shellapi.h>

#include <filesystem>
#include <memory>
#include <string>
#include <utility>
#include <vector>

#include "flutter_window.h"
#include "native_launch_configuration.h"
#include "utils.h"

namespace {

// OLE 必须在拥有 Flutter child 与 IDropTarget 的同一 UI STA 线程上成对结束。
class UiOleLifetime final {
 public:
  UiOleLifetime() : result_(OleInitialize(nullptr)) {}
  ~UiOleLifetime() { if (SUCCEEDED(result_)) OleUninitialize(); }
  bool ready() const { return SUCCEEDED(result_); }
 private:
  HRESULT result_;
};

int LaunchFailure(const std::wstring& detail) {
  const std::wstring message =
      L"ChaSteady 未启动。无效的隔离配置不会回退到默认用户数据。\n"
      L"ChaSteady did not start. Invalid isolation never falls back to default user data.\n\n" + detail;
  MessageBoxW(nullptr, message.c_str(), L"ChaSteady", MB_OK | MB_ICONERROR | MB_TASKMODAL);
  return EXIT_FAILURE;
}

}  // namespace

int APIENTRY wWinMain(_In_ HINSTANCE instance, _In_opt_ HINSTANCE prev,
                      _In_ wchar_t *command_line, _In_ int show_command) {
  // 有控制台或调试器时沿用既有控制台行为。
  if (!::AttachConsole(ATTACH_PARENT_PROCESS) && ::IsDebuggerPresent()) {
    CreateAndAttachConsole();
  }
  UiOleLifetime ole;
  if (!ole.ready()) return LaunchFailure(L"The UI OLE apartment could not be initialized.");

  wchar_t executable_path[32768]{};
  const DWORD path_length = GetModuleFileNameW(nullptr, executable_path, 32768);
  if (path_length == 0 || path_length >= 32768) return LaunchFailure(L"The application path is unavailable.");
  const std::filesystem::path resource_root = std::filesystem::path(executable_path).parent_path();

  int argc = 0;
  LPWSTR* argv = CommandLineToArgvW(GetCommandLineW(), &argc);
  if (argv == nullptr || argc < 1) {
    if (argv != nullptr) LocalFree(argv);
    return LaunchFailure(L"The native command line could not be decoded.");
  }
  std::vector<std::wstring> arguments;
  for (int index = 1; index < argc; ++index) arguments.emplace_back(argv[index]);
  LocalFree(argv);
  std::vector<std::wstring> remaining;
  std::shared_ptr<const chasteady::NativeLaunchConfiguration> configuration;
  std::wstring error;
  // 在创建 Flutter、JobStore 或 Worker 之前固定配置；原生私有参数不会传给 Dart。
  if (!chasteady::NativeLaunchConfiguration::Prepare(arguments, resource_root.wstring(),
                                                    &remaining, &configuration, &error)) {
    return LaunchFailure(error);
  }
  std::vector<std::string> dart_arguments;
  for (const auto& argument : remaining) dart_arguments.push_back(Utf8FromUtf16(argument.c_str()));
  flutter::DartProject project((resource_root / L"data").wstring());
  project.set_dart_entrypoint_arguments(std::move(dart_arguments));

  // window 在 OLE RAII 对象之前析构，确保 RevokeDragDrop 和 COM 引用先完成释放。
  FlutterWindow window(project, configuration);
  Win32Window::Point origin(10, 10);
  Win32Window::Size size(1280, 720);
  if (!window.Create(L"ChaSteady", origin, size)) return EXIT_FAILURE;
  window.SetQuitOnClose(true);

  ::MSG msg{};
  BOOL message_result;
  while ((message_result = ::GetMessage(&msg, nullptr, 0, 0)) > 0) {
    ::TranslateMessage(&msg);
    ::DispatchMessage(&msg);
  }
  return message_result == -1 ? EXIT_FAILURE : EXIT_SUCCESS;
}
