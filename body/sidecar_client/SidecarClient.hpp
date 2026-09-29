// SidecarClient: hook 2 (state emission) and the receiving side of hook 1 (directives) for any BWAPI AI module.
// Header-only. Requires third_party/httplib.h and third_party/json.hpp (both header-only, MIT).
//
// Usage inside an AIModule:
//   SidecarClient sidecar("127.0.0.1", 8770);      // construct in onStart
//   sidecar.onFrame(tracker);                       // every frame; posts every 24 frames in a background thread
//   auto d = sidecar.directive();                   // latest validated directive (may be empty) - never blocks
//   sidecar.onEnd(isWinner);                        // posts /game/end and joins the thread
//
// Design rules (design_v0.5.md 2/3.1): the game thread never waits on HTTP; if the sidecar is down the body
// plays with its own defaults; only the newest state is sent (older pending states are dropped).
#pragma once

#include <BWAPI.h>

#include <atomic>
#include <chrono>
#include <condition_variable>
#include <mutex>
#include <optional>
#include <string>
#include <thread>

#define CPPHTTPLIB_NO_EXCEPTIONS
#include "third_party/httplib.h"
#include "third_party/json.hpp"

#include "StateTracker.hpp"

struct Directive {
    std::string directive_id;
    int issued_frame = 0;
    int expires_frame = 0;
    bool keep_current_plan = false;
    std::string opening;
    std::map<std::string, double> unit_mix_target;
    std::vector<std::string> tech_priority;
    std::string stance = "defensive";
    std::string expand_policy = "allow_when_safe";
    std::string objective_type = "defend";
    std::string objective_location = "natural";
    std::string wall_natural = "none";
    std::map<std::string, int> static_defense;
    std::string scout_policy;
    double confidence = 0.0;
    std::string change_reason;

    bool valid(int frame) const { return !directive_id.empty() && frame <= expires_frame; }

    static std::optional<Directive> fromJson(const nlohmann::json& j) {
        if (j.is_null() || !j.is_object()) return std::nullopt;
        Directive d;
        d.directive_id = j.value("directive_id", "");
        d.issued_frame = j.value("issued_frame", 0);
        d.expires_frame = j.value("expires_frame", 0);
        d.keep_current_plan = j.value("keep_current_plan", false);
        d.opening = j.value("opening", "");
        if (j.contains("unit_mix_target")) d.unit_mix_target = j["unit_mix_target"].get<std::map<std::string, double>>();
        if (j.contains("tech_priority")) d.tech_priority = j["tech_priority"].get<std::vector<std::string>>();
        d.stance = j.value("stance", "defensive");
        d.expand_policy = j.value("expand_policy", "allow_when_safe");
        if (j.contains("army_objective")) {
            d.objective_type = j["army_objective"].value("type", "defend");
            d.objective_location = j["army_objective"].value("location", "natural");
        }
        d.wall_natural = j.value("wall_natural", "none");
        if (j.contains("static_defense")) d.static_defense = j["static_defense"].get<std::map<std::string, int>>();
        d.scout_policy = j.value("scout_policy", "");
        d.confidence = j.value("confidence", 0.0);
        d.change_reason = j.value("change_reason", "");
        return d;
    }
};

class SidecarClient {
public:
    SidecarClient(std::string host, int port, int postEveryFrames = 24, int timeoutMs = 2000)
        : host_(std::move(host)), port_(port), every_(postEveryFrames), timeoutMs_(timeoutMs) {
        gameId_ = makeGameId();
        worker_ = std::thread([this] { loop(); });
    }
    ~SidecarClient() { stop(); }

    const std::string& gameId() const { return gameId_; }

    // Call every frame from onFrame. Cheap: serializes only every `every_` frames or when the tracker has events.
    void onFrame(StateTracker& tracker) {
        const int frame = BWAPI::Broodwar->getFrameCount();
        if (frame % every_ != 0 && !tracker.hasPendingEvents()) return;
        nlohmann::json state = tracker.toStateSummary(gameId_, lastDirectiveId());
        {
            std::lock_guard<std::mutex> lk(mu_);
            pending_ = state.dump();   // newest only
            pendingFrame_ = frame;
        }
        cv_.notify_one();
    }

    std::optional<Directive> directive() const {
        std::lock_guard<std::mutex> lk(mu_);
        return directive_;
    }

    std::string lastDirectiveId() const {
        std::lock_guard<std::mutex> lk(mu_);
        return directive_ ? directive_->directive_id : "";
    }

    bool connected() const { return connected_.load(); }
    int postsSent() const { return posts_.load(); }
    int postsFailed() const { return failed_.load(); }

    void onEnd(bool isWinner) {
        stop();
        httplib::Client cli(host_, port_);
        cli.set_connection_timeout(0, timeoutMs_ * 1000);
        cli.set_read_timeout(timeoutMs_ / 1000 + 1, 0);
        nlohmann::json body = {{"result", isWinner ? "win" : "loss"}, {"frame", BWAPI::Broodwar->getFrameCount()}};
        cli.Post("/game/end?game_id=" + gameId_, body.dump(), "application/json");
    }

private:
    void loop() {
        httplib::Client cli(host_, port_);
        cli.set_connection_timeout(0, timeoutMs_ * 1000);
        cli.set_read_timeout(timeoutMs_ / 1000 + 1, 0);
        cli.set_keep_alive(true);
        while (true) {
            std::string payload;
            {
                std::unique_lock<std::mutex> lk(mu_);
                cv_.wait(lk, [this] { return stop_ || !pending_.empty(); });
                if (stop_ && pending_.empty()) return;
                payload.swap(pending_);
            }
            auto res = cli.Post("/state", payload, "application/json");
            if (!res || res->status != 200) {
                failed_++;
                connected_ = false;
                continue;
            }
            posts_++;
            connected_ = true;
            auto j = nlohmann::json::parse(res->body, nullptr, false);
            if (j.is_discarded()) continue;
            auto d = Directive::fromJson(j.value("directive", nlohmann::json()));
            std::lock_guard<std::mutex> lk(mu_);
            if (d) directive_ = d;
        }
    }

    void stop() {
        {
            std::lock_guard<std::mutex> lk(mu_);
            if (stop_) return;
            stop_ = true;
        }
        cv_.notify_all();
        if (worker_.joinable()) worker_.join();
    }

    static std::string makeGameId() {
        auto now = std::chrono::system_clock::to_time_t(std::chrono::system_clock::now());
        char buf[32];
        std::strftime(buf, sizeof buf, "%Y%m%dT%H%M%S", std::localtime(&now));
        std::string map = BWAPI::Broodwar->mapFileName();
        for (auto& c : map) if (!isalnum(static_cast<unsigned char>(c))) c = '_';
        return std::string(buf) + "_" + map + "_" + std::to_string(BWAPI::Broodwar->getRandomSeed());
    }

    std::string host_;
    int port_, every_, timeoutMs_;
    std::string gameId_;
    mutable std::mutex mu_;
    std::condition_variable cv_;
    std::string pending_;
    int pendingFrame_ = 0;
    bool stop_ = false;
    std::optional<Directive> directive_;
    std::atomic<bool> connected_{false};
    std::atomic<int> posts_{0}, failed_{0};
    std::thread worker_;
};
