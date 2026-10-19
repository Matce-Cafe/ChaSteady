cmake_minimum_required(VERSION 3.14)
project(runner LANGUAGES CXX)

# Define the application target. To change its name, change BINARY_NAME in the
# top-level CMakeLists.txt, not the value here, or `flutter run` will no longer
# work.
#
# Any new source files that you add to the application should be added here.
add_executable(${BINARY_NAME} WIN32
  "flutter_window.cpp"
  "main.cpp"
  "utils.cpp"
  "win32_window.cpp"
  "worker_supervisor.cpp"
  "native_bridge.cpp"
  "native_media.cpp"
  "window_chrome.cpp"
  "native_launch_configuration.cpp"
  "media_drop_target.cpp"
  "preview_lease_bookkeeping.cpp"
  "${FLUTTER_MANAGED_DIR}/generated_plugin_registrant.cc"
  "Runner.rc"
  "runner.exe.manifest"
)

# Apply the standard set of build settings. This can be removed for applications
# that need different build settings.
apply_standard_settings(${BINARY_NAME})
# 新增中文注释、原生错误文案与 Unicode 路径 fixture 必须使用确定的源字符集。
target_compile_options(${BINARY_NAME} PRIVATE /utf-8)

# Add preprocessor definitions for the build version.
target_compile_definitions(${BINARY_NAME} PRIVATE "FLUTTER_VERSION=\"${FLUTTER_VERSION}\"")
target_compile_definitions(${BINARY_NAME} PRIVATE "FLUTTER_VERSION_MAJOR=${FLUTTER_VERSION_MAJOR}")
target_compile_definitions(${BINARY_NAME} PRIVATE "FLUTTER_VERSION_MINOR=${FLUTTER_VERSION_MINOR}")
target_compile_definitions(${BINARY_NAME} PRIVATE "FLUTTER_VERSION_PATCH=${FLUTTER_VERSION_PATCH}")
target_compile_definitions(${BINARY_NAME} PRIVATE "FLUTTER_VERSION_BUILD=${FLUTTER_VERSION_BUILD}")

# Disable Windows macros that collide with C++ standard library functions.
target_compile_definitions(${BINARY_NAME} PRIVATE "NOMINMAX")

# Add dependency libraries and include directories. Add any application-specific
# dependencies here.
# The native bridge uses PluginRegistrarWindows from the plugin wrapper.
target_link_libraries(${BINARY_NAME} PRIVATE
  flutter flutter_wrapper_app flutter_wrapper_plugin
)
target_link_libraries(${BINARY_NAME} PRIVATE
  dwmapi comctl32 mfplat mf mfuuid d3d11 dxgi ole32 oleaut32 shell32 advapi32 uuid
)
target_include_directories(${BINARY_NAME} PRIVATE "${CMAKE_SOURCE_DIR}")

# Run the Flutter tool portions of the build. This must not be removed.
add_dependencies(${BINARY_NAME} flutter_assemble)

# Explicit opt-in only: never launch a GUI fixture as part of normal app builds
# or packaging. This standalone test owns all of its HWNDs and uses no Flutter
# engine, worker, third-party window plugin, or user-window enumeration.
option(CHASTEADY_BUILD_WINDOW_CHROME_SMOKE "Build the owned Win32 chrome smoke executable" OFF)
if(CHASTEADY_BUILD_WINDOW_CHROME_SMOKE)
  add_executable(chasteady_window_chrome_smoke
    "tests/window_chrome_smoke.cpp"
    "window_chrome.cpp"
    "runner.exe.manifest"
  )
  apply_standard_settings(chasteady_window_chrome_smoke)
  target_compile_options(chasteady_window_chrome_smoke PRIVATE /utf-8)
  # Keep the fixture and its PDB out of runner/Release and the application ZIP.
  set_target_properties(chasteady_window_chrome_smoke PROPERTIES
    RUNTIME_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/native_smoke/$<CONFIG>"
    PDB_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/native_smoke/$<CONFIG>"
  )
  target_compile_definitions(chasteady_window_chrome_smoke PRIVATE "NOMINMAX")
  target_include_directories(chasteady_window_chrome_smoke PRIVATE "${CMAKE_CURRENT_SOURCE_DIR}")
  target_link_libraries(chasteady_window_chrome_smoke PRIVATE dwmapi comctl32)
endif()

# 只有显式 Debug 诊断构建包含有界消息读取接口；发布 runner 完全不编译该接口。
option(CHASTEADY_ENABLE_WINDOW_DIAGNOSTICS "Enable bounded diagnostics in Debug runner only" OFF)
if(CHASTEADY_ENABLE_WINDOW_DIAGNOSTICS)
  target_compile_definitions(${BINARY_NAME} PRIVATE "$<$<CONFIG:Debug>:CHASTEADY_WINDOW_DIAGNOSTICS>")
endif()

# 默认不构建、不运行、不打包；原有 73-check fixture 与其 STATIC SS_NOTIFY 基线保持独立。
option(CHASTEADY_BUILD_NATIVE_SAFETY_TESTS "Build native profile and OLE data fixtures" OFF)
if(CHASTEADY_BUILD_NATIVE_SAFETY_TESTS)
  add_executable(chasteady_native_profile_test
    "tests/native_launch_configuration_test.cpp"
    "native_launch_configuration.cpp"
    "runner.exe.manifest"
  )
  add_executable(chasteady_media_drop_test
    "tests/media_drop_target_test.cpp"
    "media_drop_target.cpp"
    "runner.exe.manifest"
  )
  add_executable(chasteady_preview_lease_test
    "tests/preview_lease_bookkeeping_test.cpp"
    "preview_lease_bookkeeping.cpp"
  )
  foreach(native_test chasteady_native_profile_test chasteady_media_drop_test chasteady_preview_lease_test)
    apply_standard_settings(${native_test})
    target_compile_options(${native_test} PRIVATE /utf-8)
    set_target_properties(${native_test} PROPERTIES
      RUNTIME_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/native_smoke/$<CONFIG>"
      PDB_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/native_smoke/$<CONFIG>"
    )
    target_compile_definitions(${native_test} PRIVATE NOMINMAX UNICODE _UNICODE CHASTEADY_NATIVE_TESTING)
    target_include_directories(${native_test} PRIVATE "${CMAKE_CURRENT_SOURCE_DIR}")
    target_link_libraries(${native_test} PRIVATE ole32 shell32 advapi32 uuid comctl32)
  endforeach()
endif()

# 本目标会发送真实输入，必须另获有界运行预算；正常构建和 CI 不能自动运行。
option(CHASTEADY_BUILD_OWNED_INPUT_PROBE "Build the separately authorized owned real-input probe" OFF)
if(CHASTEADY_BUILD_OWNED_INPUT_PROBE)
  add_executable(chasteady_owned_input_probe
    "tests/window_chrome_input_probe.cpp"
    "window_chrome.cpp"
    "runner.exe.manifest"
  )
  apply_standard_settings(chasteady_owned_input_probe)
  target_compile_options(chasteady_owned_input_probe PRIVATE /utf-8)
  set_target_properties(chasteady_owned_input_probe PROPERTIES
    RUNTIME_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/native_smoke/$<CONFIG>"
    PDB_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/native_smoke/$<CONFIG>"
  )
  target_compile_definitions(chasteady_owned_input_probe PRIVATE NOMINMAX CHASTEADY_WINDOW_DIAGNOSTICS)
  target_include_directories(chasteady_owned_input_probe PRIVATE "${CMAKE_CURRENT_SOURCE_DIR}")
  target_link_libraries(chasteady_owned_input_probe PRIVATE dwmapi comctl32)
endif()
