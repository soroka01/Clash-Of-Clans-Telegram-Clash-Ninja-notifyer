"""Names for identifiers used in the Clash of Clans village export JSON."""

BUILDINGS = {
    1000000: "Cannon", 1000001: "Archer Tower", 1000002: "Wizard Tower",
    1000003: "Air Defense", 1000004: "Mortar", 1000005: "Barracks",
    1000006: "Elixir Storage", 1000007: "Gold Storage", 1000009: "Town Hall",
    1000010: "Wall", 1000011: "Laboratory", 1000012: "Clan Castle",
    1000013: "Builder Hut", 1000014: "Spell Factory", 1000015: "Dark Elixir Storage",
    1000019: "X-Bow", 1000020: "Inferno Tower", 1000021: "Dark Barracks",
    1000023: "Bomb Tower", 1000024: "Elixir Collector", 1000026: "Gold Mine",
    1000027: "Dark Elixir Drill", 1000028: "Air Sweeper", 1000029: "Hidden Tesla",
    1000032: "Giga Tesla", 1000059: "Bomb Tower", 1000064: "Pet House",
    1000067: "Blacksmith", 1000068: "Spell Tower", 1000070: "Monolith",
    1000071: "Army Camp", 1000072: "Barracks", 1000077: "Multi-Archer Tower",
    1000084: "Ricochet Cannon", 1000085: "Firespitter", 1000086: "Hero Hall",
    1000089: "Super Wizard Tower", 1000093: "Workshop", 1000102: "Giga Bomb",
}

TRAPS = {
    12000000: "Bomb", 12000001: "Spring Trap", 12000002: "Air Bomb",
    12000005: "Giant Bomb", 12000006: "Skeleton Trap", 12000008: "Seeking Air Mine",
    12000016: "Tornado Trap", 12000020: "Push Trap", 12000010: "Bomb",
    12000011: "Spring Trap", 12000013: "Mega Mine", 12000014: "Giga Bomb",
}

TROOPS = {
    4000000: "Barbarian", 4000001: "Archer", 4000002: "Giant", 4000003: "Goblin",
    4000004: "Wall Breaker", 4000005: "Balloon", 4000006: "Wizard", 4000007: "Healer",
    4000008: "Dragon", 4000009: "P.E.K.K.A", 4000010: "Minion", 4000011: "Hog Rider",
    4000012: "Valkyrie", 4000013: "Golem", 4000015: "Witch", 4000017: "Lava Hound",
    4000022: "Bowler", 4000023: "Baby Dragon", 4000024: "Miner", 4000053: "Electro Dragon",
    4000058: "Yeti", 4000059: "Ice Golem", 4000065: "Dragon Rider", 4000082: "Electro Titan",
    4000095: "Apprentice Warden", 4000097: "Super Miner", 4000110: "Root Rider",
    4000123: "Druid", 4000132: "Spirit Fox", 4000150: "Apprentice Warden", 4000177: "Thrower",
}

SPELLS = {
    26000000: "Lightning Spell", 26000001: "Healing Spell", 26000002: "Rage Spell",
    26000003: "Jump Spell", 26000005: "Freeze Spell", 26000009: "Poison Spell",
    26000010: "Earthquake Spell", 26000011: "Haste Spell", 26000016: "Clone Spell",
    26000017: "Skeleton Spell", 26000028: "Bat Spell", 26000035: "Invisibility Spell",
    26000053: "Recall Spell", 26000070: "Overgrowth Spell", 26000098: "Frostmine Spell",
    26000109: "Revive Spell", 26000120: "Totem Spell",
}

PETS = {
    73000000: "L.A.S.S.I", 73000001: "Mighty Yak", 73000002: "Electro Owl",
    73000003: "Unicorn", 73000004: "Frosty", 73000007: "Diggy", 73000008: "Poison Lizard",
    73000009: "Phoenix", 73000010: "Mighty Yak", 73000011: "Spirit Fox", 73000016: "Angry Jelly",
}

HEROES = {
    28000000: "Barbarian King", 28000001: "Archer Queen", 28000002: "Grand Warden",
    28000004: "Royal Champion", 28000006: "Minion Prince", 28000007: "Dragon Duke",
}

# Maximum levels in the export identify the three supported helpers: Builder's
# Apprentice (8), Lab Assistant (12), and Alchemist (7). ID 93000003 is an
# internal helper slot and is intentionally ignored.
HELPERS = {93000000: "Builder's Apprentice", 93000001: "Lab Assistant", 93000002: "Alchemist"}
