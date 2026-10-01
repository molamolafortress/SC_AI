# ZZZKBot (third_party/zzzkbot @ 7183e37) as a Linux AI module for OpenBW's BWAPILauncher.
#
#   cmake -S body/zzzkbot_port -B build/zzzkbot -G Ninja -DCMAKE_BUILD_TYPE=Release
#   ninja -C build/zzzkbot -j4        -> build/zzzkbot/ZZZKBot.so
#
# Prerequisite: body/zzzkbot_port/apply_patches.sh (applies body/patches/zzzkbot/*.patch
# to third_party/zzzkbot; the tree is otherwise unmodified upstream source).
# Same pattern as body/mcrave_port/CMakeLists.txt.
cmake_minimum_required(VERSION 3.16)
project(ZZZKBotModule CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)
if(NOT CMAKE_BUILD_TYPE)
  set(CMAKE_BUILD_TYPE Release CACHE STRING "" FORCE)
endif()
set(CMAKE_CXX_FLAGS_RELEASE "-O2")

set(SC_AI_ROOT "${CMAKE_CURRENT_SOURCE_DIR}/../.." CACHE PATH "SC_AI checkout")
set(ZZZKBOT_ROOT "${SC_AI_ROOT}/third_party/zzzkbot" CACHE PATH "ZZZKBot checkout (patched)")
set(BWAPI_ROOT "${SC_AI_ROOT}/third_party/openbw-bwapi" CACHE PATH "OpenBW bwapi checkout")
set(BWAPI_INCLUDE_DIR "${BWAPI_ROOT}/bwapi/include" CACHE PATH "BWAPI headers")
set(BWAPI_LIB_DIR "${BWAPI_ROOT}/build/lib" CACHE PATH "OpenBW built libs (libBWAPILIB.so)")

set(ZZZKBOT_SRC "${ZZZKBOT_ROOT}/ZZZKBot/Source")
# The vcxproj compiles Dll.cpp + ZZZKBotAIModule.cpp. Dll.cpp needs <Windows.h> (DllMain);
# it is replaced by Dll_linux.cpp.
set(ZZZKBOT_SOURCES
  "${ZZZKBOT_SRC}/ZZZKBotAIModule.cpp"
  "${CMAKE_CURRENT_SOURCE_DIR}/Dll_linux.cpp")

set(CMAKE_SHARED_LIBRARY_PREFIX "")   # ZZZKBot.so, not libZZZKBot.so
add_library(ZZZKBot SHARED ${ZZZKBOT_SOURCES})
target_include_directories(ZZZKBot PRIVATE "${BWAPI_INCLUDE_DIR}" "${ZZZKBOT_SRC}")
# vcxproj: NOMINMAX;WIN32;NDEBUG;_WINDOWS;_USRDLL;ZZZKBOT_EXPORTS -> keep the portable ones.
target_compile_definitions(ZZZKBot PRIVATE NOMINMAX NDEBUG ZZZKBOT_EXPORTS)
target_compile_options(ZZZKBot PRIVATE -Wall -Wno-unused-variable -Wno-unused-but-set-variable
  -Wno-sign-compare -Wno-reorder -Wno-unused-function -Wno-parentheses -Wno-misleading-indentation)

find_library(BWAPILIB_SO NAMES BWAPILIB PATHS "${BWAPI_LIB_DIR}" NO_DEFAULT_PATH)
if(NOT BWAPILIB_SO)
  message(FATAL_ERROR "libBWAPILIB.so not found in ${BWAPI_LIB_DIR}; build third_party/openbw-bwapi first (docs/setup_openbw.md)")
endif()
find_package(Threads REQUIRED)
target_link_libraries(ZZZKBot PRIVATE "${BWAPILIB_SO}" Threads::Threads)
target_link_options(ZZZKBot PRIVATE -Wl,--no-undefined)
