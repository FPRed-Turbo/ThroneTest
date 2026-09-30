"""Registry of every Throne and Liberty dataset exposed by questlog.gg."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Dataset:
    name: str          # folder / file name
    list_proc: str     # paginated list procedure
    detail_proc: str   # single-entity procedure (input: {"id", "language"})
    build_relevant: bool = False  # fetch details by default & feature in the build pack


DATABASES = [
    Dataset("items", "database.getItems", "database.getItem", True),
    Dataset("item-sets", "database.getItemSets", "database.getItemSet", True),
    Dataset("skill-sets", "database.getSkillSets", "database.getSkillSet", True),
    Dataset("skill-traits", "database.getSkillTraits", "database.getSkillTrait", True),
    Dataset("weapon-specializations", "database.getWeaponSpecializations", "database.getWeaponSpecialization", True),
    Dataset("potential-abilities", "database.getPotentialAbilities", "database.getPotentialAbility", True),
    Dataset("litographs", "database.getLitographs", "database.getLitograph", True),
    Dataset("polymorphs", "database.getPolymorphs", "database.getPolymorph", True),
    Dataset("amitois", "database.getAmitois", "database.getAmitoi"),
    Dataset("amitoi-sets", "database.getAmitoiSets", "database.getAmitoiSet"),
    Dataset("amitoi-expeditions", "database.getAmitoiExpeditions", "database.getAmitoiExpedition"),
    Dataset("achievements", "database.getAchievements", "database.getAchievement"),
    Dataset("codex-chapters", "database.getCodexChapters", "database.getCodexChapter"),
    Dataset("codex-pages", "database.getCodexPages", "database.getCodexPage"),
    Dataset("contracts", "database.getContracts", "database.getContract"),
    Dataset("cooking-recipes", "database.getCookingRecipes", "database.getCookingRecipe"),
    Dataset("recipes", "database.getRecipes", "database.getRecipe"),
    Dataset("dungeons", "database.getDungeons", "database.getDungeon"),
    Dataset("guild-dungeons", "database.getGuildDungeons", "database.getGuildDungeon"),
    Dataset("solo-dungeons", "database.getSoloDungeons", "database.getSoloDungeon"),
    Dataset("towers", "database.getTowers", "database.getTower"),
    Dataset("events", "database.getEvents", "database.getEvent"),
    Dataset("npcs", "database.getNpcs", "database.getNpc"),
    Dataset("occupations", "database.getOccupations", "database.getOccupation"),
    Dataset("resources", "database.getResources", "database.getResource"),
]

# Only these item categories matter for builds; other items (materials,
# consumables, quest items...) are listed but not fetched in detail by default.
BUILD_ITEM_CATEGORIES = {"weapons", "armor", "accessories", "equipment", "rune"}

# Whole-game datasets used by questlog's character & skill builders.
# They are returned in one call each and are the core of build math.
BUILDER_DATASETS = {
    "attribute-stats": "characterBuilder.getAttributeStats",
    "equipment-items": "characterBuilder.getEquipmentItems",
    "equipment-item-sets": "characterBuilder.getEquipmentItemSets",
    "equipment-runes": "characterBuilder.getEquipmentRunes",
    "rune-synergies": "characterBuilder.getRuneSynergies",
    "builder-skill-sets": "skillBuilder.getSkillSets",
    "builder-skill-traits": "skillBuilder.getSkillTraits",
}

BY_NAME = {d.name: d for d in DATABASES}

# Extra reference tables (called with {"language": ...}).
REFERENCE_DATASETS = {
    "stat-format": "statFormat.getStatFormat",            # stat id -> display name, multiplier, tooltip
    "weapon-mastery-levels": "dataTable.getWeaponMasteryLevels",
}

# Weapon combinations ("classes") and the role questlog assigns them.
# Used to pull the most-liked public community builds for every combo.
CLASS_COMBOS = {
    "bow-crossbow": "dps", "bow-dagger": "dps", "bow-staff": "dps", "bow-sword2h": "dps",
    "bow-wand": "healer", "crossbow-dagger": "dps", "crossbow-staff": "dps", "crossbow-sword": "tank",
    "crossbow-sword2h": "dps", "crossbow-wand": "healer", "dagger-wand": "healer",
    "gauntlet-bow": "dps", "gauntlet-crossbow": "dps", "gauntlet-dagger": "dps", "gauntlet-orb": "tank",
    "gauntlet-spear": "dps", "gauntlet-staff": "dps", "gauntlet-sword": "tank", "gauntlet-sword2h": "tank",
    "gauntlet-wand": "healer", "orb-bow": "dps", "orb-crossbow": "dps", "orb-dagger": "dps",
    "orb-spear": "dps", "orb-staff": "dps", "orb-sword": "tank", "orb-sword2h": "tank", "orb-wand": "healer",
    "spear-bow": "dps", "spear-crossbow": "dps", "spear-dagger": "dps", "spear-staff": "dps",
    "spear-sword": "tank", "spear-sword2h": "dps", "spear-wand": "healer", "staff-dagger": "dps",
    "staff-sword2h": "dps", "staff-wand": "healer", "sword-bow": "tank", "sword-dagger": "tank",
    "sword-staff": "tank", "sword-wand": "tank", "sword2h-dagger": "dps", "sword2h-sword": "tank",
    "sword2h-wand": "healer",
}

# Editorial content on questlog's shared ("core") API. Throne and Liberty is game 2.
CORE_BASE_URL = "https://questlog.gg/api/core/trpc"
TL_GAME_ID = 2
CONTENT_CATEGORIES = ["guide", "build_guide", "patch_note"]
