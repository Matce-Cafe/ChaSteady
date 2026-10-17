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
  "${FLUTTER_MANAGED_DIR}/generated_plugin_registrant.cc"
  "Runner.rc"
  "runner.exe.manifest"
)

# Apply the standard set of build settings. This can be removed for applications
# that need different build settings.
apply_standard_settings(${BINARY_NAME})

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
  # Keep the fixture and its PDB out of runner/Release and the application ZIP.
  set_target_properties(chasteady_window_chrome_smoke PROPERTIES
    RUNTIME_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/native_smoke/$<CONFIG>"
    PDB_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/native_smoke/$<CONFIG>"
  )
  target_compile_definitions(chasteady_window_chrome_smoke PRIVATE "NOMINMAX")
  target_include_directories(chasteady_window_chrome_smoke PRIVATE "${CMAKE_CURRENT_SOURCE_DIR}")
  target_link_libraries(chasteady_window_chrome_smoke PRIVATE dwmapi comctl32)
endif()
