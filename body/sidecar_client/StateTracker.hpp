// StateTracker: the "facts only" part of the State Manager that must live in the body because it needs
// BWAPI every frame: enemy memory (first/last seen), undetected cloaked units, events, and the StateSummary JSON.
#pragma once

#include <BWAPI.h>

#include <map>
#include <set>
#include <string>
#include <vector>

#include "third_party/json.hpp"

class StateTracker {
public:
    struct SeenBuilding { int count = 0; int firstFrame = 0; };
    struct SeenUnit { int count = 0; int lastFrame = 0; };

    // Call every frame.
    void update() {
        auto& bw = BWAPI::Broodwar;
        const int frame = bw->getFrameCount();
        std::map<std::string, int> buildingNow, unitNow;
        cloaked_.clear();
        for (auto u : bw->enemy()->getUnits()) {
            if (!u->exists()) continue;
            const auto type = u->getType();
            const std::string name = norm(type.getName());
            if (type.isBuilding()) {
                buildingNow[name]++;
                if (!buildings_.count(name)) {
                    buildings_[name].firstFrame = frame;
                    events_.push_back({"enemy_building_spotted", name, frame});
                }
            } else {
                unitNow[name]++;
                units_[name].lastFrame = frame;
            }
            if ((u->isCloaked() || u->isBurrowed() || type.hasPermanentCloak()) && !u->isDetected()) {
                cloaked_.push_back({{"type", name}, {"x", u->getPosition().x}, {"y", u->getPosition().y},
                                    {"frame", frame}, {"source", "bwapi_undetected"}});
                if (!cloakedWarned_) { events_.push_back({"cloaked", name, frame}); cloakedWarned_ = true; }
            }
        }
        for (auto& [name, n] : buildingNow) buildings_[name].count = std::max(buildings_[name].count, n);
        for (auto& [name, n] : unitNow) units_[name].count = std::max(units_[name].count, n);
        if (bw->enemy()->getRace() != BWAPI::Races::Unknown) enemyRace_ = norm(bw->enemy()->getRace().getName());
    }

    void onUnitDestroy(BWAPI::Unit u) {
        if (u->getPlayer() == BWAPI::Broodwar->enemy() && u->getType().isBuilding()) {
            auto& b = buildings_[norm(u->getType().getName())];
            if (b.count > 0) b.count--;
        }
    }

    void pushEvent(const std::string& type, const std::string& what) {
        events_.push_back({type, what, BWAPI::Broodwar->getFrameCount()});
    }
    bool hasPendingEvents() const { return !events_.empty(); }

    // Filled by the body each frame (optional): Horizon/strength numbers, McRave's own choices, command metering.
    nlohmann::json combatSim = nlohmann::json::object();
    nlohmann::json bodyDefaults = nlohmann::json::object();
    nlohmann::json metrics = nlohmann::json::object();

    nlohmann::json toStateSummary(const std::string& gameId, const std::string& directiveId) {
        auto& bw = BWAPI::Broodwar;
        auto* me = bw->self();
        const int frame = bw->getFrameCount();
        nlohmann::json myUnits = nlohmann::json::object(), myBuildings = nlohmann::json::object();
        int larva = 0, armyValue = 0; long long ax = 0, ay = 0; int armyN = 0;
        for (auto u : me->getUnits()) {
            const auto t = u->getType();
            if (t == BWAPI::UnitTypes::Zerg_Larva) { larva++; continue; }
            if (t == BWAPI::UnitTypes::Zerg_Egg) continue;
            const std::string name = norm(t.getName());
            if (t.isBuilding()) { myBuildings[name] = myBuildings.value(name, 0) + 1; continue; }
            myUnits[name] = myUnits.value(name, 0) + 1;
            if (!t.isWorker() && t.canAttack()) {
                armyValue += t.mineralPrice() + t.gasPrice();
                ax += u->getPosition().x; ay += u->getPosition().y; armyN++;
            }
        }
        nlohmann::json tech = nlohmann::json::object();
        for (auto up : BWAPI::UpgradeTypes::allUpgradeTypes())
            if (up.getRace() == BWAPI::Races::Zerg && me->getUpgradeLevel(up) > 0) tech[norm(up.getName())] = "done";
        for (auto tt : BWAPI::TechTypes::allTechTypes())
            if (tt.getRace() == BWAPI::Races::Zerg && me->hasResearched(tt)) tech[norm(tt.getName())] = "done";
        for (auto u : me->getUnits()) {
            if (u->isUpgrading()) tech[norm(u->getUpgrade().getName())] = "researching";
            if (u->isResearching()) tech[norm(u->getTech().getName())] = "researching";
        }
        nlohmann::json enemyUnits = nlohmann::json::object(), enemyBuildings = nlohmann::json::object();
        for (auto& [n, s] : units_) enemyUnits[n] = {{"count", s.count}, {"last_frame", s.lastFrame}};
        for (auto& [n, s] : buildings_) if (s.count > 0) enemyBuildings[n] = {{"count", s.count}, {"first_frame", s.firstFrame}};
        int enemyArmy = 0;
        for (auto& [n, s] : units_) enemyArmy += s.count * priceOf(n);

        nlohmann::json events = nlohmann::json::array();
        for (auto& e : events_) events.push_back({{"type", e.type}, {"what", e.what}, {"frame", e.frame}});
        events_.clear();

        const int secs = frame * 42 / 1000;  // ~23.81 fps
        char gt[16]; std::snprintf(gt, sizeof gt, "%d:%02d", secs / 60, secs % 60);
        const std::string matchup = std::string("Zv") + (enemyRace_.empty() ? "X" : std::string(1, static_cast<char>(toupper(enemyRace_[0]))));

        return {
            {"game_id", gameId}, {"frame", frame}, {"game_time", gt}, {"matchup", matchup}, {"map", bw->mapName()},
            {"me", {{"minerals", me->minerals()}, {"gas", me->gas()}, {"supply", {me->supplyUsed() / 2, me->supplyTotal() / 2}},
                    {"larva", larva}, {"units", myUnits}, {"buildings", myBuildings}, {"tech", tech}, {"army_value", armyValue},
                    {"army_pos", armyN ? nlohmann::json({ax / armyN, ay / armyN}) : nlohmann::json(nullptr)}}},
            {"enemy", {{"race", enemyRace_.empty() ? "unknown" : enemyRace_}, {"units_seen", enemyUnits},
                       {"buildings_seen", enemyBuildings}, {"expansions", expansions()}, {"army_value_seen", enemyArmy},
                       {"army_pos_seen", nullptr}, {"suspected_cloaked", cloaked_}}},
            {"combat_sim", combatSim},
            {"events", events},
            {"execution", {{"directive_id", directiveId.empty() ? nlohmann::json(nullptr) : nlohmann::json(directiveId)}, {"goals", nlohmann::json::array()}}},
            {"body_defaults", bodyDefaults},
            {"metrics", metrics},
        };
    }

private:
    struct Event { std::string type, what; int frame; };

    static std::string norm(std::string s) {
        // "Terran_Barracks" -> "barracks", "Zerg_Spawning_Pool" -> "spawning_pool", "Metabolic Boost" -> "metabolic_boost"
        auto us = s.find('_');
        if (us != std::string::npos && (s.rfind("Terran_", 0) == 0 || s.rfind("Zerg_", 0) == 0 || s.rfind("Protoss_", 0) == 0)) s = s.substr(us + 1);
        for (auto& c : s) c = (c == ' ') ? '_' : static_cast<char>(tolower(static_cast<unsigned char>(c)));
        return s;
    }
    static int priceOf(const std::string& n) {
        for (auto t : BWAPI::UnitTypes::allUnitTypes())
            if (norm(t.getName()) == n) return t.mineralPrice() + t.gasPrice();
        return 0;
    }
    int expansions() const {
        int n = 0;
        for (auto& [name, b] : buildings_)
            if (name == "command_center" || name == "hatchery" || name == "lair" || name == "hive" || name == "nexus") n += b.count;
        return n;
    }

    std::map<std::string, SeenBuilding> buildings_;
    std::map<std::string, SeenUnit> units_;
    std::vector<Event> events_;
    nlohmann::json cloaked_ = nlohmann::json::array();
    bool cloakedWarned_ = false;
    std::string enemyRace_;
};
