// SidecarProbeModule: the smallest possible AI module that exercises SidecarClient + StateTracker.
// It does not play (workers mine by default). Purpose: prove the body<->sidecar pipeline on OpenBW/1.16.1.
#include <BWAPI.h>
#include "../SidecarClient.hpp"
#include "../StateTracker.hpp"
#include <memory>
#include <cstdlib>

class SidecarProbeModule : public BWAPI::AIModule {
public:
    void onStart() override {
        const char* host = std::getenv("SIDECAR_HOST");
        const char* port = std::getenv("SIDECAR_PORT");
        if (!host && !port) { BWAPI::Broodwar->sendText("SidecarProbe: no SIDECAR_HOST/PORT, idle opponent mode"); return; }
        client_ = std::make_unique<SidecarClient>(host ? host : "127.0.0.1", port ? std::atoi(port) : 8770);
        BWAPI::Broodwar->sendText("SidecarProbe game %s", client_->gameId().c_str());
    }
    void onFrame() override {
        if (!client_) return;
        tracker_.update();
        client_->onFrame(tracker_);
        if (BWAPI::Broodwar->getFrameCount() % 240 == 0) {
            auto d = client_->directive();
            BWAPI::Broodwar->drawTextScreen(10, 10, "sidecar %s posts=%d failed=%d directive=%s stance=%s",
                client_->connected() ? "up" : "down", client_->postsSent(), client_->postsFailed(),
                d ? d->directive_id.c_str() : "-", d ? d->stance.c_str() : "-");
        }
    }
    void onUnitDestroy(BWAPI::Unit u) override { tracker_.onUnitDestroy(u); }
    void onEnd(bool isWinner) override { if (client_) client_->onEnd(isWinner); }

private:
    StateTracker tracker_;
    std::unique_ptr<SidecarClient> client_;
};

extern "C" void gameInit(BWAPI::Game* game) { BWAPI::BroodwarPtr = game; }
extern "C" BWAPI::AIModule* newAIModule() { return new SidecarProbeModule(); }
