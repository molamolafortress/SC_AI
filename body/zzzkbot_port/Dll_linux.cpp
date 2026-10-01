// Linux replacement for third_party/zzzkbot/ZZZKBot/Source/Dll.cpp (which needs <Windows.h>
// for DllMain). Same two-symbol ABI that OpenBW's BWAPILauncher dlopens.
#include <BWAPI.h>
#include "ZZZKBotAIModule.h"

#if defined(_WIN32)
#define ZZZK_EXPORT __declspec(dllexport)
#else
#define ZZZK_EXPORT __attribute__((visibility("default")))
#endif

extern "C" ZZZK_EXPORT void gameInit(BWAPI::Game* game) { BWAPI::BroodwarPtr = game; }

extern "C" ZZZK_EXPORT BWAPI::AIModule* newAIModule()
{
    return new ZZZKBotAIModule();
}
