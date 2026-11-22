"""Bot policy constants. Balance numbers belong in config.py, not here."""
from __future__ import annotations

# --- perception -------------------------------------------------------------
MEMORY_GRACE_S = 0.5
LOST_KEEP_S = 20.0
MAX_TRACKS = 32
CONTACT_TTL_S = 6.0
MAX_CONTACTS = 24
ATTR_DEG = 12.0
SOUND_MATCH_DEG = 14.0
ID_JUMP_M = 40.0
LOS_CANDIDATES = 8
CONFIDENCE_HALF_LIFE_S = 3.0

# --- mode priorities --------------------------------------------------------
ZONE_RECOVERY_PRIORITY = 40
ZONE_MOVE_PRIORITY = 30
ENCOUNTER_PRIORITY = 20
ZONE_HOLD_PRIORITY = 10
STICKY_BONUS = 5
PREEMPT_GAP = 10

# --- encounter --------------------------------------------------------------
# The first practice score (0.92 vs 1.15 starter) says the v1 fight loop is
# losing placement.  Keep the code, but default to zone-only until a practice
# comparison shows Encounter helps.
ENABLE_ENCOUNTER = False
# Zone keeps moving; this overlay only takes aim/fire at a nearby visible mech.
ENABLE_DEFENSE = True
DEFEND_ATTACKER_S = 2.0
DEFEND_RADIUS_M = 200.0
DEFEND_AIM_FRAC = 1.0
# Published practice deltas: 3-5 s strafe reversals while engaged, +0.35.
STRAFE_FRAC = 0.5
STRAFE_FLIP_S = 4.0
STRAFE_EDGE_MARGIN_M = 10.0
ENGAGE_RADIUS_M = 120.0
DISENGAGE_RADIUS_M = 170.0
TARGET_LOST_S = 2.0
TARGET_DWELL_S = 1.0
ENCOUNTER_MIN_DWELL_S = 1.0
SEARCH_S = 2.0
BAND_LO_M = 50.0
BAND_HI_M = 120.0
BAND_DEADBAND_M = 10.0
RANGE_KP = 1.5
ORBIT_FRAC = 0.7
ORBIT_FLIP_S = 4.0
BOOST_GAP_M = 40.0
ZONE_EDGE_MARGIN_M = 10.0
PROBE_M = 4.0
AIM_GATE_FRAC = 0.5
AIM_GATE_MAX_DEG = 3.0
ACTION_LATENCY_S = 0.1
DODGE_HORIZON_S = 1.2
DODGE_RADIUS_M = 6.0
STUCK_S = 1.0

# --- attack primitive -------------------------------------------------------
# Pick and keep one rival; spend ammo only when the round can hit; hide during
# reload/cooldown instead of standing in the target's line.
ATTACK_ATTACKER_S = 3.0
ATTACK_ACQUIRE_FRAC = 0.95
ATTACK_KEEP_FRAC = 1.0
ATTACK_SWITCH_FRAC = 0.75
ATTACK_SWITCH_SCORE = 12.0
ATTACK_NPC_RANGE_M = 90.0
ATTACK_NPC_IDLE_RANGE_M = 45.0
ATTACK_DOWN_S = 0.2
ATTACK_RELOAD_FRAC = 0.5
ATTACK_MIN_HIT_PROB = 0.05
# Full target angular radius: the old v1/v2 gate. Half-radius gates fire less
# often than they improve accuracy, so keep the baseline's useful volume.
ATTACK_AIM_GATE_FRAC = 1.0
ATTACK_LOS_BONUS = 18.0
ATTACK_COVER_BONUS = 20.0
ATTACK_COVER_HOLD_BONUS = 6.0
ATTACK_COVER_HOLD_S = 0.6
ATTACK_REAR_BONUS = 6.0
ATTACK_DODGE_BONUS = 12.0

# --- zone -------------------------------------------------------------------
ZONE_SAFETY_M = 8.0
ZONE_MOVE_MARGIN_S = 5.0
ZONE_PATH_FACTOR = 1.15
ZONE_ACCEL_ALLOWANCE_S = 0.5
ZONE_MIN_SAFE_RADIUS_M = 25.0
ZONE_HOLD_BIAS = 0.4
ZONE_DAMAGE_BUDGET_FRAC = 0.10
BOOST_ENERGY_RESERVE = 30.0
ZONE_MIN_DWELL_S = 1.5
# 0.35 * 11.7 m/s ~= 4.1 m/s, just below the 5 m/s step-sound threshold.
HOLD_ORBIT_FRAC = 0.35

# --- loot (v2.2 arm 1) ------------------------------------------------------
# Value is in "first-secondary" units: 3.0 * kind for the first weapon, so a
# trip is worth roughly one place. Prices subtract time and expected damage.
LOOT_ENABLE = True
LOOT_ITEM_VALUE = True           # rank remembered items at all
LOOT_TTL_S = 90.0               # how long we keep a remembered item
LOOT_STALE_S = 20.0             # older than this: still a goal, worse ETA
LOOT_RADIUS_FIRST_M = 220.0
LOOT_RADIUS_M = 140.0
LOOT_FIRST_SECONDARY = 3.0
LOOT_SWAP_VALUE = 2.0           # a mortar in slot 1 is worth replacing
LOOT_SWAP_ENABLE = False        # 2a change, unproven officially: off for 2b
LOOT_KIND_VALUE = {"laser": 1.0, "lightning": 0.85, "mortar": 0.35, "gun": 0.0}
# A mortar is a late fallback, not an opening move: 32-seed practice sim had
# gun+laser 2.90, gun+lightning 2.11, gun+mortar 0.67, gun-only 0.14, and the
# traces show an early mortar trip burning the window where a laser is findable
# (seed 0: 14 s walking to a mortar, then 50 s exploring, dead at 87 s).
# A mortar is a real last resort: 32-seed practice sim had gun+laser 2.90,
# gun+lightning 2.11, gun+mortar 0.67, gun-only 0.14, and gating mortars until
# t>90 s cost four matches *any* second weapon without buying a laser. So the
# mortar stays takeable (0.35) and the swap below is the real guard against it
# blocking slot 1.
LOOT_MORTAR_AFTER_S = 0.0
# A crate is a 50 % weapon roll plus a cube, worth a detour but never a reason
# to give up the rotation or a fight while slot 1 is still empty.
# 2a shipped this at 0.6 and officially scored 2.77 against arm 1's 3.00, so
# the unproven 2a behaviour changes are reverted for the 2b measurement: this
# is back to the arm-1 value.
LOOT_CRATE_UNARMED = 1.0
LOOT_CRATE = 0.35
LOOT_CUBE_STAT = 0.50
LOOT_CUBE_HEAL = 0.40
LOOT_CUBE_UPGRADE = 0.50
LOOT_DROP = 1.6
LOOT_DROP_ALONE_M = 20.0       # capture freezes when a second mech is in the ring
LOOT_DRONE_M = 90.0
LOOT_DRONE_HP = 0.60
LOOT_DRONE_VALUE = 0.70
CRATE_RANGE_M = 40.0
LOOT_DROP_MAX_WAIT = 45.0
LOOT_RACE_SIGMA_S = 2.5
LOOT_RACE_FLOOR = 0.15
LOOT_RACE_TURN_S = 8.0
LOOT_RACE_RADIUS_M = 250.0
LOOT_THREAT_M = 120.0
LOOT_THREAT_SCALE = 60.0
LOOT_ITEM_VETO = 0.5            # hostile DPS at the item vs our own
LOOT_EXPOSURE_FRAC = 0.25       # fraction of the trip we are exposed
LOOT_DAMAGE_FRAC = 0.25         # veto: expected damage vs current HP
LOOT_TIME_PRICE = 0.010
LOOT_DAMAGE_PRICE = 0.002
LOOT_MIN_SCORE = 0.25
LOOT_URGENT = 0.75              # pre-empts FIGHT
LOOT_GOOD = 0.40                # pre-empts HOLD/MOVE-with-margin
LOOT_SLACK_MIN_S = 25.0
LOOT_HP_MIN = 0.60
LOOT_LATCH_BONUS = 1.3
LOOT_STALL_S = 4.0
LOOT_BLACKLIST_S = 15.0
LOOT_ZONE_MARGIN_S = 3.0

# --- explore / movement discipline (v2.2 arm 2a) ----------------------------
# Ablated at 32 paired practice seeds: on 2.19/1.91/1.72 (two runs) vs off
# 1.91/1.84, with the armed rate unchanged (21-23/32 vs 25/32) and ~1-2 s more
# time outside the zone. Blind exploration does not pay yet; arm 2b revisits it
# once the strength field can say *where* to look.
EXPLORE_ENABLE = False
EXPLORE_CELL_M = 60.0
EXPLORE_RADIUS_M = 150.0
EXPLORE_MIN_M = 25.0
EXPLORE_AHEAD_M = 45.0          # forward bias, in metres of score
EXPLORE_HOLD_S = 6.0
EXPLORE_ARRIVE_M = 25.0
EXPLORE_ZONE_MARGIN_S = 20.0
# Below sound.step_speed (5 m/s) a mech makes no footstep. Cap the commanded
# speed to 4.7 m/s whenever a known enemy is inside SILENT_RADIUS_M.
SILENT_SPEED_MPS = 4.7
SILENT_RADIUS_M = 120.0
# A second take for the same id inside this window is a pipeline duplicate.
TAKE_QUARANTINE_S = 0.3

# --- strength field (v2.2 arm 2b) -------------------------------------------
STR_CELL_M = 25.0
STR_REBUILD_S = 0.4
STR_TRACK_SIGMA_M = 25.0
STR_AGE_SIGMA_M = 6.0
STR_TRACK_TTL_S = 20.0
STR_DECAY_S = 45.0
STR_CONTACT_TTL_S = 6.0
STR_DAMAGE_AGE_S = 4.0
STR_LOOT_SIGMA_M = 35.0
STR_LOOT_MAX_ITEMS = 6
STR_ZONE_SIGMA_FRAC = 0.5
STR_ZONE_NEXT = 1.0
STR_ZONE_RING = 0.25
STR_CLASS_POWER = 55.0        # one gun-only house bot at 75 % HP
STR_CLASS_RAMP = 35.0         # towards a looted loadout by t=90 s
STR_RAY_SIGMA_M = 45.0
STR_RAY_ANGLE = 0.26          # ~15 deg

# --- disengage (v2.2 arm 2b) ------------------------------------------------
# Measured neutral and then cut: over 3 clean live rooms the mode **never
# triggered** (mode samples: move/hold/loot/cover/dodge only), and the 64-seed
# paired practice sim was +0.06 (CI -0.24..+0.37). The strength rebuild also
# cost ~1.4 ms per decision and tripled late replies under 4-way sim load. The
# code is kept behind flags for a future design that uses the field to choose
# *where to stand* rather than to trigger a retreat.
DISENGAGE_ENABLE = False
DIS_RADIUS_M = 90.0
DIS_MIN_M = 45.0
DIS_ZONE_MARGIN_S = 5.0
DIS_LATCH_S = 1.5
DIS_MAX_S = 20.0
DIS_REENTER_S = 5.0
DIS_TTB_S = 4.0
DIS_MULTI_S = 6.0
DIS_MULTI_HP = 0.70
DIS_STRENGTH_RATIO = 1.5
DIS_WEAK_HP = 0.65
DIS_MIN_HP = 0.30
DIS_HEAL_TO = 0.85
DIS_HEAL_TO_LASER = 0.95
DIS_FIRE_RANGE_M = 25.0
DIS_RISK_W = 0.6
DIS_DPS_W = 2.0
DIS_DIST_W = 0.02
DIS_CORRIDOR_M = 40.0
# heal ledger: heal earlier when the local field says we are outgunned, later
# when it says we are alone; late in the match survivors are ranked by HP.
HEAL_LEDGER_ENABLE = False
HEAL_BIAS_STRONG = 0.15
HEAL_BIAS_QUIET = 0.55
HEAL_DEADLINE_S = 90.0
# fight gate: only start fights we win and that have no pack behind them
FIGHT_GATE_ENABLE = False
FIGHT_TTK_RATIO = 1.3
FIGHT_SUPPORT_FRAC = 0.6
FIGHT_SUPPORT_M = 120.0
# hold spots: prefer cells the field thinks are empty (road.hold is 0..255)
HOLD_DENSITY_W = 0.0

# --- upgrades (v2.2 arm 1) --------------------------------------------------
UPGRADE_ENABLE = True
# HP-equivalent value of each effect. Regen assumes ~8 s of regen per match.
UPG_HP_PER_MUL = 1400.0         # per unit of max_hp multiplier
UPG_ARMOR_HP = 1400.0           # EHP conversion base
UPG_REGEN_SECONDS = 8.0
UPG_SPEED_HP = 60.0
UPG_TURN_HP = 25.0
UPG_ENERGY_HP = 15.0
UPG_EREGEN_HP = 10.0
UPG_DRAIN_HP = 5.0
UPG_SENSE_HP = 30.0
UPG_WEAPON_HP = 150.0
UPG_RANGE_HP = 40.0
UPG_MAG_HP = 60.0
UPG_LASER_CHARGE_HP = 80.0
UPG_MORTAR_HP = 10.0
UPG_UNKNOWN_HP = 10.0

# --- nav / timing -----------------------------------------------------------
PATH_RECOMPUTE_S = 0.5
NAV_CELL_M = 4.0
PATH_NODE_CAP = 20000
