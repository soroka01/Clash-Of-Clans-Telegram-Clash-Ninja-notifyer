"""Names for the numeric ids used in the Clash of Clans village export JSON (home village only).

The tables follow the game's own static data (ClashKing's ClashKingAssets and coc.py list identical
ids) and were cross-checked against a real export: building counts and levels (for example five
Builder's Huts, one Town Hall) only make sense with these names. An id that is missing here is shown
as "ID <number>" in the bot and written once to the log, so adding a row is all it takes.
"""

BUILDINGS = {
    1000000: "Army Camp", 1000001: "Town Hall", 1000002: "Elixir Collector",
    1000003: "Elixir Storage", 1000004: "Gold Mine", 1000005: "Gold Storage",
    1000006: "Barracks", 1000007: "Laboratory", 1000008: "Cannon",
    1000009: "Archer Tower", 1000010: "Wall", 1000011: "Wizard Tower",
    1000012: "Air Defense", 1000013: "Mortar", 1000014: "Clan Castle",
    1000015: "Builder's Hut", 1000019: "Hidden Tesla", 1000020: "Spell Factory",
    1000021: "X-Bow", 1000023: "Dark Elixir Drill", 1000024: "Dark Elixir Storage",
    1000026: "Dark Barracks", 1000027: "Inferno Tower", 1000028: "Air Sweeper",
    1000029: "Dark Spell Factory", 1000031: "Eagle Artillery", 1000032: "Bomb Tower",
    1000059: "Workshop", 1000064: "B.O.B's Hut", 1000067: "Scattershot",
    1000068: "Pet House", 1000070: "Blacksmith", 1000071: "Hero Hall",
    1000072: "Spell Tower", 1000077: "Monolith", 1000079: "Multi-Gear Tower",
    1000083: "Sour Elixir Cauldron", 1000084: "Multi-Archer Tower", 1000085: "Ricochet Cannon",
    1000086: "Revenge Tower", 1000089: "Firespitter", 1000093: "Helper Hut",
    1000097: "Crafting Station", 1000102: "Super Wizard Tower",
}

TRAPS = {
    12000000: "Bomb", 12000001: "Spring Trap", 12000002: "Giant Bomb",
    12000005: "Air Bomb", 12000006: "Seeking Air Mine", 12000008: "Skeleton Trap",
    12000016: "Tornado Trap", 12000020: "Giga Bomb",
}

TROOPS = {
    4000000: "Barbarian", 4000001: "Archer", 4000002: "Goblin", 4000003: "Giant",
    4000004: "Wall Breaker", 4000005: "Balloon", 4000006: "Wizard", 4000007: "Healer",
    4000008: "Dragon", 4000009: "P.E.K.K.A", 4000010: "Minion", 4000011: "Hog Rider",
    4000012: "Valkyrie", 4000013: "Golem", 4000015: "Witch", 4000017: "Lava Hound",
    4000022: "Bowler", 4000023: "Baby Dragon", 4000024: "Miner", 4000053: "Yeti",
    4000058: "Ice Golem", 4000059: "Electro Dragon", 4000065: "Dragon Rider",
    4000082: "Headhunter", 4000094: "Ram Rider", 4000095: "Electro Titan",
    4000097: "Apprentice Warden", 4000110: "Root Rider", 4000123: "Druid",
    4000132: "Thrower", 4000150: "Furnace", 4000167: "Meteor Golem", 4000177: "Meteor Golem",
}

SIEGE_MACHINES = {
    4000051: "Wall Wrecker", 4000052: "Battle Blimp", 4000062: "Stone Slammer",
    4000075: "Siege Barracks", 4000087: "Log Launcher", 4000091: "Flame Flinger",
    4000092: "Battle Drill", 4000135: "Troop Launcher", 4000188: "Sky Wagon",
}

SPELLS = {
    26000000: "Lightning Spell", 26000001: "Healing Spell", 26000002: "Rage Spell",
    26000003: "Jump Spell", 26000005: "Freeze Spell", 26000009: "Poison Spell",
    26000010: "Earthquake Spell", 26000011: "Haste Spell", 26000016: "Clone Spell",
    26000017: "Skeleton Spell", 26000028: "Bat Spell", 26000035: "Invisibility Spell",
    26000053: "Recall Spell", 26000070: "Overgrowth Spell", 26000073: "Bag of Frostmites",
    26000098: "Revive Spell", 26000109: "Ice Block Spell", 26000120: "Totem Spell",
    26000123: "Angry Spell",
}

PETS = {
    73000000: "L.A.S.S.I", 73000001: "Mighty Yak", 73000002: "Electro Owl",
    73000003: "Unicorn", 73000004: "Phoenix", 73000007: "Poison Lizard",
    73000008: "Diggy", 73000009: "Frosty", 73000010: "Spirit Fox",
    73000011: "Angry Jelly", 73000016: "Sneezy", 73000017: "Greedy Raven",
}

HEROES = {
    28000000: "Barbarian King", 28000001: "Archer Queen", 28000002: "Grand Warden",
    28000004: "Royal Champion", 28000006: "Minion Prince", 28000007: "Dragon Duke",
}

# The three helpers the bot follows. 93000003 (Prospector) is intentionally ignored.
HELPERS = {93000000: "Builder's Apprentice", 93000001: "Lab Assistant", 93000002: "Alchemist"}

# Export list name -> id table.
TABLES = {
    "buildings": BUILDINGS,
    "traps": TRAPS,
    "heroes": HEROES,
    "units": TROOPS,
    "siege_machines": SIEGE_MACHINES,
    "spells": SPELLS,
    "pets": PETS,
}
