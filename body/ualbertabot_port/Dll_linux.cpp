// Linux AI-module entry for UAlbertaBot. Upstream master is a BWAPI *client* executable
// (UAlbertaBot/Source/main.cpp pumps BWAPIClient events into UAlbertaBotModule, which is
// not a BWAPI::AIModule). OpenBW's BWAPILauncher instead dlopens a module exporting
// gameInit/newAIModule, so this file adapts UAlbertaBotModule to BWAPI::AIModule and does
// the one-time SparCraft::init()/BOSS::init() that main() used to do.
#include <BWAPI.h>
#include "UAlbertaBotModule.h"
#include "../../SparCraft/source/SparCraft.h"
#include "../../BOSS/source/BOSS.h"

#if defined(_WIN32)
#define UAB_EXPORT __declspec(dllexport)
#else
#define UAB_EXPORT __attribute__((visibility("default")))
#endif

namespace
{
class UAlbertaBotAIModule : public BWAPI::AIModule
{
    UAlbertaBot::UAlbertaBotModule m_bot;

public:
    void onStart() override { m_bot.onStart(); }
    void onEnd(bool isWinner) override { m_bot.onEnd(isWinner); }
    void onFrame() override { m_bot.onFrame(); }
    void onSendText(std::string text) override { m_bot.onSendText(text); }
    void onUnitDiscover(BWAPI::Unit) override {}
    void onUnitEvade(BWAPI::Unit) override {}
    void onUnitShow(BWAPI::Unit unit) override { m_bot.onUnitShow(unit); }
    void onUnitHide(BWAPI::Unit unit) override { m_bot.onUnitHide(unit); }
    void onUnitCreate(BWAPI::Unit unit) override { m_bot.onUnitCreate(unit); }
    void onUnitDestroy(BWAPI::Unit unit) override { m_bot.onUnitDestroy(unit); }
    void onUnitMorph(BWAPI::Unit unit) override { m_bot.onUnitMorph(unit); }
    void onUnitRenegade(BWAPI::Unit unit) override { m_bot.onUnitRenegade(unit); }
    void onUnitComplete(BWAPI::Unit unit) override { m_bot.onUnitComplete(unit); }
};
}  // namespace

extern "C" UAB_EXPORT void gameInit(BWAPI::Game* game) { BWAPI::BroodwarPtr = game; }

extern "C" UAB_EXPORT BWAPI::AIModule* newAIModule()
{
    static bool initialised = false;
    if (!initialised)
    {
        SparCraft::init();  // combat simulation tables
        BOSS::init();       // build-order search tables
        initialised = true;
    }
    return new UAlbertaBotAIModule();
}
