# Project-level configuration.
cmake_minimum_required(VERSION 3.14)

# CI must select its audited SDK before project() initializes the VS generator.
# Explicit selection also avoids CMP0149 OLD preferring an older host-OS SDK.
if(DEFINED ENV{CHASTEADY_WINDOWS_SDK_VERSION})
  set(_chasteady_ci_windows_sdk "$ENV{CHASTEADY_WINDOWS_SDK_VERSION}")
  if(NOT _chasteady_ci_windows_sdk MATCHES "^[0-9]+\\.[0-9]+\\.[0-9]+\\.[0-9]+$"
      OR _chasteady_ci_windows_sdk VERSION_LESS "10.0.28000.0")
    message(FATAL_ERROR "CI Windows SDK must be an audited four-part version >= 10.0.28000.0")
  endif()
  set(CMAKE_SYSTEM_VERSION "${_chasteady_ci_windows_sdk}"
    CACHE STRING "Explicitly audited CI Windows SDK target" FORCE)
endif()

project(cha_stabilizer_ui LANGUAGES CXX)

if(DEFINED _chasteady_ci_windows_sdk)
  if(NOT CMAKE_VS_WINDOWS_TARGET_PLATFORM_VERSION STREQUAL _chasteady_ci_windows_sdk)
    message(FATAL_ERROR "Visual Studio did not select the explicitly audited CI Windows SDK")
  endif()
  # Ordinary project variables are not automatically cache entries. Persist only
  # actual post-project toolchain facts for the CI helper to verify.
  set(CHASTEADY_CMAKE_COMMAND "${CMAKE_COMMAND}" CACHE INTERNAL "Actual CMake executable" FORCE)
  set(CHASTEADY_CMAKE_VERSION "${CMAKE_VERSION}" CACHE INTERNAL "Actual CMake version" FORCE)
  set(CHASTEADY_CMAKE_GENERATOR "${CMAKE_GENERATOR}" CACHE INTERNAL "Actual generator" FORCE)
  set(CHASTEADY_CMAKE_GENERATOR_INSTANCE "${CMAKE_GENERATOR_INSTANCE}" CACHE INTERNAL "Actual VS instance" FORCE)
  set(CHASTEADY_CMAKE_GENERATOR_PLATFORM "${CMAKE_GENERATOR_PLATFORM}" CACHE INTERNAL "Actual target architecture" FORCE)
  set(CHASTEADY_CXX_COMPILER "${CMAKE_CXX_COMPILER}" CACHE INTERNAL "Actual C++ compiler" FORCE)
  set(CHASTEADY_CXX_COMPILER_VERSION "${CMAKE_CXX_COMPILER_VERSION}" CACHE INTERNAL "Actual compiler version" FORCE)
  set(CHASTEADY_WINDOWS_SDK_VERSION "${CMAKE_VS_WINDOWS_TARGET_PLATFORM_VERSION}" CACHE INTERNAL "Actual Windows SDK target" FORCE)
endif()

# The name of the executable created for the application. Change this to change
# the on-disk name of your application.
set(BINARY_NAME "ChaSteady")

# Explicitly opt in to modern CMake behaviors to avoid warnings with recent
# versions of CMake.
cmake_policy(VERSION 3.14...3.25)

# Define build configuration option.
get_property(IS_MULTICONFIG GLOBAL PROPERTY GENERATOR_IS_MULTI_CONFIG)
if(IS_MULTICONFIG)
  set(CMAKE_CONFIGURATION_TYPES "Debug;Profile;Release"
    CACHE STRING "" FORCE)
else()
  if(NOT CMAKE_BUILD_TYPE AND NOT CMAKE_CONFIGURATION_TYPES)
    set(CMAKE_BUILD_TYPE "Debug" CACHE
      STRING "Flutter build mode" FORCE)
    set_property(CACHE CMAKE_BUILD_TYPE PROPERTY STRINGS
      "Debug" "Profile" "Release")
  endif()
endif()
# Define settings for the Profile build mode.
set(CMAKE_EXE_LINKER_FLAGS_PROFILE "${CMAKE_EXE_LINKER_FLAGS_RELEASE}")
set(CMAKE_SHARED_LINKER_FLAGS_PROFILE "${CMAKE_SHARED_LINKER_FLAGS_RELEASE}")
set(CMAKE_C_FLAGS_PROFILE "${CMAKE_C_FLAGS_RELEASE}")
set(CMAKE_CXX_FLAGS_PROFILE "${CMAKE_CXX_FLAGS_RELEASE}")

# Use Unicode for all projects.
add_definitions(-DUNICODE -D_UNICODE)

# Compilation settings that should be applied to most targets.
#
# Be cautious about adding new options here, as plugins use this function by
# default. In most cases, you should add new options to specific targets instead
# of modifying this function.
function(APPLY_STANDARD_SETTINGS TARGET)
  target_compile_features(${TARGET} PUBLIC cxx_std_17)
  target_compile_options(${TARGET} PRIVATE /W4 /WX /wd"4100")
  target_compile_options(${TARGET} PRIVATE /EHsc)
  target_compile_definitions(${TARGET} PRIVATE "$<$<CONFIG:Debug>:_DEBUG>")
endfunction()

# Flutter library and tool build rules.
set(FLUTTER_MANAGED_DIR "${CMAKE_CURRENT_SOURCE_DIR}/flutter")
add_subdirectory(${FLUTTER_MANAGED_DIR})

# Application build; see runner/CMakeLists.txt.
add_subdirectory("runner")


# Generated plugin build rules, which manage building the plugins and adding
# them to the application.
include(flutter/generated_plugins.cmake)


# === Installation ===
# Support files are copied into place next to the executable, so that it can
# run in place. This is done instead of making a separate bundle (as on Linux)
# so that building and running from within Visual Studio will work.
set(BUILD_BUNDLE_DIR "$<TARGET_FILE_DIR:${BINARY_NAME}>")
# Make the "install" step default, as it's required to run.
set(CMAKE_VS_INCLUDE_INSTALL_TO_DEFAULT_BUILD 1)
if(CMAKE_INSTALL_PREFIX_INITIALIZED_TO_DEFAULT)
  set(CMAKE_INSTALL_PREFIX "${BUILD_BUNDLE_DIR}" CACHE PATH "..." FORCE)
endif()

set(INSTALL_BUNDLE_DATA_DIR "${CMAKE_INSTALL_PREFIX}/data")
set(INSTALL_BUNDLE_LIB_DIR "${CMAKE_INSTALL_PREFIX}")

install(TARGETS ${BINARY_NAME} RUNTIME DESTINATION "${CMAKE_INSTALL_PREFIX}"
  COMPONENT Runtime)

install(FILES "${FLUTTER_ICU_DATA_FILE}" DESTINATION "${INSTALL_BUNDLE_DATA_DIR}"
  COMPONENT Runtime)

install(FILES "${FLUTTER_LIBRARY}" DESTINATION "${INSTALL_BUNDLE_LIB_DIR}"
  COMPONENT Runtime)

if(PLUGIN_BUNDLED_LIBRARIES)
  install(FILES "${PLUGIN_BUNDLED_LIBRARIES}"
    DESTINATION "${INSTALL_BUNDLE_LIB_DIR}"
    COMPONENT Runtime)
endif()

# Copy the native assets provided by the build.dart from all packages.
set(NATIVE_ASSETS_DIR "${PROJECT_BUILD_DIR}native_assets/windows/")
install(DIRECTORY "${NATIVE_ASSETS_DIR}"
   DESTINATION "${INSTALL_BUNDLE_LIB_DIR}"
   COMPONENT Runtime)

# Fully re-copy the assets directory on each build to avoid having stale files
# from a previous install.
set(FLUTTER_ASSET_DIR_NAME "flutter_assets")
install(CODE "
  file(REMOVE_RECURSE \"${INSTALL_BUNDLE_DATA_DIR}/${FLUTTER_ASSET_DIR_NAME}\")
  " COMPONENT Runtime)
install(DIRECTORY "${PROJECT_BUILD_DIR}/${FLUTTER_ASSET_DIR_NAME}"
  DESTINATION "${INSTALL_BUNDLE_DATA_DIR}" COMPONENT Runtime)

# Install the AOT library on non-Debug builds only.
install(FILES "${AOT_LIBRARY}" DESTINATION "${INSTALL_BUNDLE_DATA_DIR}"
  CONFIGURATIONS Profile;Release
  COMPONENT Runtime)
