# McRave (third_party/mcrave @ 7d1719a) as a Linux AI module for OpenBW's BWAPILauncher.
#
#   cmake -S body/mcrave_port -B build/mcrave -G Ninja -DCMAKE_BUILD_TYPE=Release
#   ninja -C build/mcrave -j4        -> build/mcrave/McRave.so
#
# Prerequisite: body/mcrave_port/apply_patches.sh (applies body/patches/mcrave/*.patch
# to third_party/mcrave; the tree is otherwise unmodified upstream source).
cmake_minimum_required(VERSION 3.16)
project(McRaveModule CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)
if(NOT CMAKE_BUILD_TYPE)
  set(CMAKE_BUILD_TYPE Release CACHE STRING "" FORCE)
endif()
set(CMAKE_CXX_FLAGS_RELEASE "-O2")

set(SC_AI_ROOT "${CMAKE_CURRENT_SOURCE_DIR}/../.." CACHE PATH "SC_AI checkout")
set(MCRAVE_ROOT "${SC_AI_ROOT}/third_party/mcrave" CACHE PATH "McRave checkout (patched)")
# BWAPI_INCLUDE_DIR: the header set to compile against. Default: the OpenBW fork's own
# headers (BWAPI 4.2 API). Override with third_party/bwapi-official/bwapi/include (4.4.0)
# if McRave needs API that the fork lacks (see README.md for what was actually required).
set(BWAPI_ROOT "${SC_AI_ROOT}/third_party/openbw-bwapi" CACHE PATH "OpenBW bwapi checkout")
set(BWAPI_INCLUDE_DIR "${BWAPI_ROOT}/bwapi/include" CACHE PATH "BWAPI headers")
set(BWAPI_LIB_DIR "${BWAPI_ROOT}/build/lib" CACHE PATH "OpenBW built libs (libBWAPILIB.so)")

set(MCRAVE_SRC "${MCRAVE_ROOT}/Source")
file(GLOB_RECURSE MCRAVE_SOURCES CONFIGURE_DEPENDS
  "${MCRAVE_SRC}/McRave/*.cpp"
  "${MCRAVE_SRC}/BWEM/*.cpp"
  "${MCRAVE_SRC}/BWEB/*.cpp"
  "${MCRAVE_SRC}/Horizon/*.cpp")
# Windows-only translation units (see body/HOOKS.md 1.3):
#   Dll.cpp      -> DllMain + __declspec exports; replaced by Dll_linux.cpp below
#   winutils.cpp -> QueryPerformanceCounter timer; BWEM_USE_WINUTILS is set to 0 by patch
list(FILTER MCRAVE_SOURCES EXCLUDE REGEX "/McRave/Main/Dll\\.cpp$")
list(FILTER MCRAVE_SOURCES EXCLUDE REGEX "/BWEM/winutils\\.cpp$")
list(APPEND MCRAVE_SOURCES "${CMAKE_CURRENT_SOURCE_DIR}/Dll_linux.cpp")
list(LENGTH MCRAVE_SOURCES _n)
message(STATUS "McRave: ${_n} translation units, BWAPI headers: ${BWAPI_INCLUDE_DIR}")

set(CMAKE_SHARED_LIBRARY_PREFIX "")   # McRave.so, not libMcRave.so (BWAPILauncher dlopens by path)
add_library(McRave SHARED ${MCRAVE_SOURCES})

target_include_directories(McRave PRIVATE
  "${BWAPI_INCLUDE_DIR}"
  "${MCRAVE_SRC}/BWEB"
  "${MCRAVE_SRC}/BWEM"
  "${MCRAVE_SRC}/Horizon"
  "${MCRAVE_SRC}/McRave")
# Mirror the vcxproj preprocessor set minus WIN32/_WINDOWS/_USRDLL.
target_compile_definitions(McRave PRIVATE NOMINMAX EXAMPLEAIMODULE_EXPORTS)
target_compile_options(McRave PRIVATE -Wall -Wno-unused-variable -Wno-unused-but-set-variable
  -Wno-sign-compare -Wno-reorder -Wno-unused-function -Wno-parentheses -Wno-misleading-indentation)

find_library(BWAPILIB_SO NAMES BWAPILIB PATHS "${BWAPI_LIB_DIR}" NO_DEFAULT_PATH)
if(NOT BWAPILIB_SO)
  message(FATAL_ERROR "libBWAPILIB.so not found in ${BWAPI_LIB_DIR}; build third_party/openbw-bwapi first (docs/setup_openbw.md)")
endif()
find_package(Threads REQUIRED)
target_link_libraries(McRave PRIVATE "${BWAPILIB_SO}" Threads::Threads)
# Fail the link on any unresolved symbol so a missing BWAPI export shows up at build time,
# not at BWAPILauncher's dlopen(RTLD_NOW).
target_link_options(McRave PRIVATE -Wl,--no-undefined)
