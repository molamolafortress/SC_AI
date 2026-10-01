# UAlbertaBot (third_party/ualbertabot @ 558899d) as a Linux AI module for OpenBW's BWAPILauncher.
#
#   cmake -S body/ualbertabot_port -B build/ualbertabot -G Ninja -DCMAKE_BUILD_TYPE=Release
#   ninja -C build/ualbertabot -j4        -> build/ualbertabot/UAlbertaBot.so
#
# Prerequisite: body/ualbertabot_port/apply_patches.sh (applies body/patches/ualbertabot/*.patch
# to third_party/ualbertabot; the tree is otherwise unmodified upstream source).
# Same pattern as body/mcrave_port/CMakeLists.txt. Upstream builds three VS projects
# (BOSS lib, SparCraft lib, UAlbertaBot client exe); here all three source sets go into one .so.
cmake_minimum_required(VERSION 3.16)
project(UAlbertaBotModule CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)
if(NOT CMAKE_BUILD_TYPE)
  set(CMAKE_BUILD_TYPE Release CACHE STRING "" FORCE)
endif()
set(CMAKE_CXX_FLAGS_RELEASE "-O2")

set(SC_AI_ROOT "${CMAKE_CURRENT_SOURCE_DIR}/../.." CACHE PATH "SC_AI checkout")
set(UAB_ROOT "${SC_AI_ROOT}/third_party/ualbertabot" CACHE PATH "UAlbertaBot checkout (patched)")
set(BWAPI_ROOT "${SC_AI_ROOT}/third_party/openbw-bwapi" CACHE PATH "OpenBW bwapi checkout")
set(BWAPI_INCLUDE_DIR "${BWAPI_ROOT}/bwapi/include" CACHE PATH "BWAPI headers")
set(BWAPI_LIB_DIR "${BWAPI_ROOT}/build/lib" CACHE PATH "OpenBW built libs (libBWAPILIB.so)")

set(UAB_SRC "${UAB_ROOT}/UAlbertaBot/Source")
set(BOSS_SRC "${UAB_ROOT}/BOSS/source")
set(SPARCRAFT_SRC "${UAB_ROOT}/SparCraft/source")

# UAlbertaBot/VisualStudio/UAlbertaBot.vcxproj source list minus main.cpp (client-mode main
# loop; replaced by Dll_linux.cpp). Not a glob: Source/UnitInfoManager.cpp is a stale file that
# is not in the vcxproj and includes a non-existent Util.h.
set(UAB_SOURCES)
foreach(f AutoObserver BaseLocation BaseLocationManager BOSSManager BuildingData BuildingManager
          BuildingPlacerManager BuildOrder BuildOrderQueue CombatSimulation CombatCommander Common
          DetectorManager DistanceMap Global GameCommander InformationManager JSONTools Logger MapTools
          MedicManager MeleeManager MetaType MicroManager Config Micro ParseUtils ProductionManager
          RangedManager ScoutManager Squad SquadData StrategyManager TankManager TimerManager
          TransportManager UABAssert UAlbertaBotModule UnitData UnitUtil WorkerData WorkerManager)
  list(APPEND UAB_SOURCES "${UAB_SRC}/${f}.cpp")
endforeach()
# BOSS/VisualStudio/BOSS.vcxproj (the library project; BOSS_main / experiments / plot / GUI excluded)
set(BOSS_SOURCES)
foreach(f ActionInProgress ActionSet ActionType ActionTypeData BOSSAssert BOSSException BuildOrder
          BuildOrderPlot CombatSearch BOSS BuildingData CombatSearch_BestResponse
          CombatSearch_BestResponseData CombatSearch_Bucket CombatSearch_BucketData
          CombatSearch_IntegralData CombatSearchParameters CombatSearchResults CombatSearch_Integral
          Constants BuildOrderSearchGoal DFBB_BuildOrderSearchParameters DFBB_BuildOrderSearchResults
          DFBB_BuildOrderSmartSearch DFBB_BuildOrderStackSearch Eval GameState HatcheryData BOSSLogger
          JSONTools NaiveBuildOrderSearch PrerequisiteSet Tools UnitData)
  list(APPEND BOSS_SOURCES "${BOSS_SRC}/${f}.cpp")
endforeach()
# SparCraft/VisualStudio/SparCraft.vcxproj (the library project; gui/ and SparCraft_main excluded)
set(SPARCRAFT_SOURCES)
foreach(f Action AllPlayers AlphaBetaMove AlphaBetaSearch AnimationFrameData Common EnumData Game
          GameState Hash Logger MoveArray Player PlayerProperties Player_AlphaBeta Player_AttackClosest
          Player_AttackDPS Player_AttackWeakest Player_Cluster Player_Kiter Player_KiterDPS
          Player_Kiter_NOKDPS Player_NOKDPS Player_PortfolioGreedySearch Player_Random Player_UCT
          PortfolioGreedySearch SparCraft SparCraftAssert SparCraftException Timer TranspositionTable
          UCTSearch Unit UnitProperties UnitScriptData WeaponProperties)
  list(APPEND SPARCRAFT_SOURCES "${SPARCRAFT_SRC}/${f}.cpp")
endforeach()

set(UAB_ALL_SOURCES ${UAB_SOURCES} ${BOSS_SOURCES} ${SPARCRAFT_SOURCES} "${CMAKE_CURRENT_SOURCE_DIR}/Dll_linux.cpp")
list(LENGTH UAB_ALL_SOURCES _n)
message(STATUS "UAlbertaBot: ${_n} translation units, BWAPI headers: ${BWAPI_INCLUDE_DIR}")

set(CMAKE_SHARED_LIBRARY_PREFIX "")   # UAlbertaBot.so, not libUAlbertaBot.so
add_library(UAlbertaBot SHARED ${UAB_ALL_SOURCES})
# vcxproj include dirs: ../BOSS/source;../SparCraft/source;../source;$(BWAPI_DIR)/include
target_include_directories(UAlbertaBot PRIVATE "${BWAPI_INCLUDE_DIR}" "${UAB_SRC}" "${BOSS_SRC}" "${SPARCRAFT_SRC}")
# vcxproj: WIN32;NDEBUG;_WINDOWS;_USRDLL;EXAMPLEAIMODULE_EXPORTS;NOMINMAX -> keep the portable ones.
# BOSS_USE_BWAPI_GAMESTATE: enable BOSS::GameState(BWAPI::GameWrapper&, ...) which upstream guards with
# _MSC_VER (patch 0001 adds this alternative macro); BOSSManager.cpp needs that constructor.
target_compile_definitions(UAlbertaBot PRIVATE NOMINMAX NDEBUG EXAMPLEAIMODULE_EXPORTS BOSS_USE_BWAPI_GAMESTATE)
target_compile_options(UAlbertaBot PRIVATE -Wall -Wno-unused-variable -Wno-unused-but-set-variable
  -Wno-sign-compare -Wno-reorder -Wno-unused-function -Wno-parentheses -Wno-misleading-indentation)

find_library(BWAPILIB_SO NAMES BWAPILIB PATHS "${BWAPI_LIB_DIR}" NO_DEFAULT_PATH)
if(NOT BWAPILIB_SO)
  message(FATAL_ERROR "libBWAPILIB.so not found in ${BWAPI_LIB_DIR}; build third_party/openbw-bwapi first (docs/setup_openbw.md)")
endif()
find_package(Threads REQUIRED)
target_link_libraries(UAlbertaBot PRIVATE "${BWAPILIB_SO}" Threads::Threads)
target_link_options(UAlbertaBot PRIVATE -Wl,--no-undefined)
