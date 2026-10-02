// StateTracker: the "facts only" part of the State Manager that must live in the body because it needs
// BWAPI every frame: enemy memory (first/last seen), undetected cloaked units, events, and the StateSummary JSON.
#pragma once

#include <BWAPI.h>

#include <functional>
#include <map>
#include <set>
#include <string>
#include <vector>

#include "third_party/json.hpp"

class StateTracker {
public:
    struct SeenBuilding { int count = 0; int firstFrame = 0; };
    struct SeenUnit { int count = 0; int lastFrame = 0; int firstFrame = -1; };

    // Call every frame.
    void update() {
        auto& bw = BWAPI::Broodwar;
        const int frame = bw->getFrameCount();
        std::map<std::string, int> buildingNow, unitNow;
        cloaked_.clear();
        long long ex = 0, ey = 0; int en = 0;
        for (auto u : bw->enemy()->getUnits()) {
            if (!u->exists()) continue;
            const auto type = u->getType();
            const std::string name = norm(type.getName());
            if (!type.isBuilding() && !type.isWorker() && type.canAttack() && type != BWAPI::UnitTypes::Zerg_Larva) {
                ex += u->getPosition().x; ey += u->getPosition().y; en++;
            }
            if (type.isBuilding()) {
                buildingNow[name]++;
                if (!buildings_.count(name)) {
                    buildings_[name].firstFrame = frame;
                    events_.push_back({"enemy_building_spotted", name, frame});
                }
            } else {
                unitNow[name]++;
                auto& su = units_[name];
                su.lastFrame = frame;
                if (su.firstFrame < 0) su.firstFrame = frame;
            }
            if ((u->isCloaked() || u->isBurrowed() || type.hasPermanentCloak()) && !u->isDetected()) {
                cloaked_.push_back({{"type", name}, {"x", u->getPosition().x}, {"y", u->getPosition().y},
                                    {"frame", frame}, {"source", "bwapi_undetected"}});
                if (!cloakedWarned_) { events_.push_back({"cloaked", name, frame}); cloakedWarned_ = true; }
            }
        }
        if (en > 0) { enemyArmyPos_ = BWAPI::Position(int(ex / en), int(ey / en)); enemyArmyFrame_ = frame; }
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

    // `detail` (optional) is emitted as the event's "detail" object (engagement losses, ...).
    void pushEvent(const std::string& type, const std::string& what, nlohmann::json detail = nlohmann::json()) {
        events_.push_back({type, what, BWAPI::Broodwar->getFrameCount(), std::move(detail)});
    }
    bool hasPendingEvents() const { return !events_.empty(); }

    // Filled by the body each frame (optional): Horizon/strength numbers, McRave's own choices, command metering.
    nlohmann::json combatSim = nlohmann::json::object();
    nlohmann::json bodyDefaults = nlohmann::json::object();
    nlohmann::json metrics = nlohmann::json::object();
    // Intel brief (scouting intelligence organised for the Strategy LLM), filled by the body every emit. See Sidecar::fillIntel().
    nlohmann::json intel = nlohmann::json::object();
    // Named regions {name: {tile:[x,y], owner}} (Sidecar::buildRegions), emitted top-level as "regions".
    nlohmann::json regions = nlohmann::json::object();
    // Extra keys merged into "me" (bases, production), "enemy" and "execution" (overrides, results). Filled by the body on emit frames.
    nlohmann::json meExtra = nlohmann::json::object();
    nlohmann::json enemyExtra = nlohmann::json::object();
    nlohmann::json executionExtra = nlohmann::json::object();
    // Position -> named region ("main", "enemy_natural", "unknown_area_12"); set by the body (Sidecar::regionNameFor).
    std::function<std::string(BWAPI::Position)> regionNamer;

    static std::string gameTime(int frame) {
        if (frame < 0) return "?";
        const int secs = frame * 42 / 1000;  // ~23.81 fps
        char gt[16]; std::snprintf(gt, sizeof gt, "%d:%02d", secs / 60, secs % 60);
        return gt;
    }
    BWAPI::Position enemyArmyPosSeen() const { return enemyArmyPos_; }
    int enemyArmyFrameSeen() const { return enemyArmyFrame_; }

    // Read-only views for the body's intel assembly.
    const std::map<std::string, SeenBuilding>& buildingsSeen() const { return buildings_; }
    const std::map<std::string, SeenUnit>& unitsSeen() const { return units_; }
    int expansionsSeen() const { return expansions(); }

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
            if (tt.getRace() == BWAPI::Races::Zerg && tt.mineralPrice() > 0 && me->hasResearched(tt)) tech[norm(tt.getName())] = "done";
        for (auto u : me->getUnits()) {
            if (u->isUpgrading()) tech[norm(u->getUpgrade().getName())] = "researching";
            if (u->isResearching()) tech[norm(u->getTech().getName())] = "researching";
        }
        nlohmann::json enemyUnits = nlohmann::json::object(), enemyBuildings = nlohmann::json::object();
        for (auto& [n, s] : units_) enemyUnits[n] = {{"count", s.count}, {"last_frame", s.lastFrame}};
        for (auto& [n, s] : buildings_) if (s.count > 0) enemyBuildings[n] = {{"count", s.count}, {"first_frame", s.firstFrame}};
        // army_value_seen = value of enemy units seen in the last 25 s (current picture); army_value_max_seen = all-time max counts.
        int enemyArmy = 0, enemyArmyMax = 0;
        for (auto& [n, s] : units_) {
            const int v = s.count * priceOf(n);
            enemyArmyMax += v;
            if (frame - s.lastFrame <= 600) enemyArmy += v;
        }

        nlohmann::json events = nlohmann::json::array();
        for (auto& e : events_) {
            nlohmann::json ev = {{"type", e.type}, {"what", e.what}, {"frame", e.frame}};
            if (!e.detail.is_null()) ev["detail"] = e.detail;
            events.push_back(ev);
        }
        events_.clear();

        const int secs = frame * 42 / 1000;  // ~23.81 fps
        char gt[16]; std::snprintf(gt, sizeof gt, "%d:%02d", secs / 60, secs % 60);
        const std::string matchup = std::string("Zv") + (enemyRace_.empty() ? "X" : std::string(1, static_cast<char>(toupper(enemyRace_[0]))));

        nlohmann::json meJ = {{"minerals", me->minerals()}, {"gas", me->gas()}, {"supply", {me->supplyUsed() / 2, me->supplyTotal() / 2}},
                              {"larva", larva}, {"units", myUnits}, {"buildings", myBuildings}, {"tech", tech}, {"army_value", armyValue},
                              {"army_pos", armyN ? nlohmann::json({ax / armyN, ay / armyN}) : nlohmann::json(nullptr)}};
        meJ["army_region"] = (armyN && regionNamer) ? regionNamer(BWAPI::Position(int(ax / armyN), int(ay / armyN))) : std::string();   // "" = no army
        for (auto& [k, v] : meExtra.items()) meJ[k] = v;
        nlohmann::json enemyJ = {{"race", enemyRace_.empty() ? "unknown" : enemyRace_}, {"units_seen", enemyUnits},
                                 {"buildings_seen", enemyBuildings}, {"expansions", expansions()}, {"army_value_seen", enemyArmy}, {"army_value_max_seen", enemyArmyMax},
                                 {"army_pos_seen", nullptr}, {"suspected_cloaked", cloaked_}};
        enemyJ["army_region_seen"] = (enemyArmyFrame_ >= 0 && regionNamer) ? regionNamer(enemyArmyPos_) : std::string();   // "" = never seen
        enemyJ["army_last_seen_time"] = enemyArmyFrame_ >= 0 ? gameTime(enemyArmyFrame_) : std::string();
        for (auto& [k, v] : enemyExtra.items()) enemyJ[k] = v;
        nlohmann::json execJ = {{"directive_id", directiveId.empty() ? nlohmann::json(nullptr) : nlohmann::json(directiveId)}, {"goals", nlohmann::json::array()}};
        for (auto& [k, v] : executionExtra.items()) execJ[k] = v;

        return {
            {"game_id", gameId}, {"frame", frame}, {"game_time", gt}, {"matchup", matchup}, {"map", cleanName(bw->mapName())},
            {"me", meJ},
            {"enemy", enemyJ},
            {"regions", regions},
            {"combat_sim", combatSim},
            {"events", events},
            {"execution", execJ},
            {"body_defaults", bodyDefaults},
            {"metrics", metrics},
            {"intel", intel},
        };
    }

private:
    struct Event { std::string type, what; int frame; nlohmann::json detail; };

    static std::string cleanName(const std::string& s) {
        std::string out;
        for (unsigned char c : s) if (c >= 0x20) out += static_cast<char>(c);
        return out;
    }
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
    BWAPI::Position enemyArmyPos_ = BWAPI::Positions::Invalid;
    int enemyArmyFrame_ = -1;
};
