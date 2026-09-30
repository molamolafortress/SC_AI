// Linux replacement for third_party/mcrave/Source/McRave/Main/Dll.cpp.
// Same two-symbol ABI that OpenBW's BWAPILauncher dlopens (see
// third_party/openbw-bwapi/bwapi/ExampleAIModule/Source/Dll.cpp); no DllMain on ELF.
#include <BWAPI.h>
#include "Main/Header.h"

#if defined(_WIN32)
#define MCRAVE_EXPORT __declspec(dllexport)
#else
#define MCRAVE_EXPORT __attribute__((visibility("default")))
#endif

extern "C" MCRAVE_EXPORT void gameInit(BWAPI::Game* game) { BWAPI::BroodwarPtr = game; }

extern "C" MCRAVE_EXPORT BWAPI::AIModule* newAIModule()
{
    return new McRaveModule();
}
