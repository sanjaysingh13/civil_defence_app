"""
Management command: seed_equipment_types

Usage:
    uv run python manage.py seed_equipment_types
    uv run python manage.py seed_equipment_types --dry-run

What it does:
  1. Creates one EquipmentType row for each of the 62 equipment items listed
     in the procurement register (the same list used by seed_equipment).
  2. Each type gets:
       • name       — the canonical equipment name from the register
       • category   — the same category used in seed_equipment (FIRE/RESCUE/etc.)
       • description — a human-readable explanation of what the item is and does
       • scheduled_maintenance_periodicity — months between mandatory checks
  3. After creating/updating all types, the command matches existing Equipment
     rows to their type by name (Equipment.name == EquipmentType.name) and
     sets the equipment_type FK on each matched row.

Idempotency:
    Uses update_or_create on EquipmentType.name, so re-running is safe.
    Equipment FK assignment uses bulk_update in batches for performance.

Run order:
    seed_equipment (creates Equipment rows) → THIS COMMAND (creates EquipmentType
    and links them to Equipment) → seed_initial_maintenance (seeds first logs).
"""

from django.core.management.base import BaseCommand

from civil_defence_app.equipment.models import Equipment, EquipmentCategory, EquipmentType


# ─────────────────────────────────────────────────────────────────────────────
# EQUIPMENT TYPE SEED DATA
#
# This dict maps each equipment name (same keys as EQUIP_META in seed_equipment)
# to its type-level metadata:
#   category    — the EquipmentCategory choice value (string like "RESCUE")
#   description — plain-English explanation of the item for any reader
#   periodicity — months between scheduled maintenance checks
#
# Periodicity rationale:
#   1 month  → Life-critical (SCUBA, breathing apparatus, life jackets,
#               inflatable boats, fire entry suits) or engine-powered
#               (generators, compressors, chainsaws, motors) or medical
#               (first aid kits — restock monthly)
#   3 months → Structural rescue equipment (ropes, harnesses, pulleys,
#               carabiners), lighting, power tools, PPE helmets
#   6 months → Simple hand tools (shovels, spades, crowbars, blankets),
#               consumable PPE (gloves, boots, knee pads, disposable masks)
# ─────────────────────────────────────────────────────────────────────────────

EQUIPMENT_TYPE_SEED_DATA: list[dict] = [
    {
        "name":        "Portable Generator Set",
        "category":    EquipmentCategory.OTHER,
        "description": (
            "Petrol or diesel-powered portable generator for emergency electrical supply at "
            "incident sites. Powers search lights, power tools, and communication equipment "
            "during grid outages. Monthly check covers fuel level, engine oil, spark plugs, "
            "battery terminals, and load test."
        ),
        "periodicity": 1,
    },
    {
        "name":        "Air Compressor Machine",
        "category":    EquipmentCategory.RESCUE,
        "description": (
            "Compressed-air supply unit for pneumatic rescue tools and SCUBA cylinder refilling. "
            "Critical for search and rescue in confined spaces and underwater operations. "
            "Monthly maintenance covers oil level, belt condition, pressure relief valve, and "
            "air filter."
        ),
        "periodicity": 1,
    },
    {
        "name":        "Power Ascender (Battery Operated)",
        "category":    EquipmentCategory.RESCUE,
        "description": (
            "Battery-powered rope ascender for lifting personnel and equipment during vertical "
            "rescue operations such as high-rise building rescues and cliff evacuations. "
            "Monthly check covers battery charge, motor function, rope grip mechanism, and "
            "safety lock."
        ),
        "periodicity": 1,
    },
    {
        "name":        "Rope Delivery Gun (Rope Launcher)",
        "category":    EquipmentCategory.RESCUE,
        "description": (
            "Pneumatic or pyrotechnic device that fires a line over distance or height to "
            "establish rope access. Used in flood rescue to reach stranded persons across "
            "water or high vantage points. Quarterly check covers projectile storage, "
            "gas cartridge pressure, and rope condition."
        ),
        "periodicity": 3,
    },
    {
        "name":        "Circular Saw",
        "category":    EquipmentCategory.RESCUE,
        "description": (
            "High-powered circular saw for cutting through concrete, metal shuttering, and "
            "debris during structural collapse rescues. Monthly maintenance covers blade "
            "sharpness, guard function, lubrication of bearings, and power supply test."
        ),
        "periodicity": 1,
    },
    {
        "name":        "Bullet Chain Saw",
        "category":    EquipmentCategory.RESCUE,
        "description": (
            "Petrol-powered chainsaw for cutting fallen trees, wooden structures, and debris "
            "in post-storm and flood operations. Monthly check covers chain tension and "
            "sharpness, bar lubrication, fuel/oil levels, and engine start test."
        ),
        "periodicity": 1,
    },
    {
        "name":        "Diamond Chain Saw",
        "category":    EquipmentCategory.RESCUE,
        "description": (
            "Diamond-tipped chain saw capable of cutting reinforced concrete and masonry "
            "during urban search and rescue. Monthly check covers diamond segment wear, "
            "water cooling system, drive sprocket, and engine performance."
        ),
        "periodicity": 1,
    },
    {
        "name":        "Disposable Mask",
        "category":    EquipmentCategory.PERSONAL,
        "description": (
            "N95 or equivalent disposable respiratory protection mask for dusty, smoky, or "
            "potentially contaminated environments. Single-use PPE for field responders. "
            "Six-monthly stock check covers quantity, expiry dates, and packaging integrity."
        ),
        "periodicity": 6,
    },
    {
        "name":        "Fiber Respac Stretcher",
        "category":    EquipmentCategory.MEDICAL,
        "description": (
            "Lightweight fibre-reinforced plastic basket stretcher for transporting injured "
            "persons over difficult terrain. Rigid frame prevents further injury to trauma "
            "victims. Quarterly check covers cracks, strap buckles, and padding condition."
        ),
        "periodicity": 3,
    },
    {
        "name":        "Life Jacket with Reflective Panel",
        "category":    EquipmentCategory.FLOOD,
        "description": (
            "Personal flotation device (PFD) with high-visibility reflective panels for "
            "flood rescue operations. Must provide minimum 100 N buoyancy. Monthly "
            "inspection checks inflation bladder integrity, CO2 cartridge (if automatic), "
            "buckle and strap function, and reflective tape adhesion."
        ),
        "periodicity": 1,
    },
    {
        "name":        "Canvas Stretcher",
        "category":    EquipmentCategory.MEDICAL,
        "description": (
            "Lightweight folding canvas stretcher for patient transport in first aid "
            "situations. Simpler and more portable than fibre stretchers; suitable for "
            "stable patients. Quarterly check covers canvas tears, frame joints, and "
            "carrying handles."
        ),
        "periodicity": 3,
    },
    {
        "name":        "Screw Carabiner",
        "category":    EquipmentCategory.RESCUE,
        "description": (
            "Locking carabiner with screw-gate mechanism for rope rescue systems. Provides "
            "a secure, manually locked connection between rope system components. Quarterly "
            "check covers gate function, screw thread, and visual inspection for cracks, "
            "sharp edges, or corrosion."
        ),
        "periodicity": 3,
    },
    {
        "name":        "Fire Axe",
        "category":    EquipmentCategory.FIRE,
        "description": (
            "Forged steel fire axe for forcible entry through doors, walls, and debris during "
            "fire rescue. Combination of cutting blade and blunt poll. Quarterly check covers "
            "blade sharpness, head-to-handle security, and handle integrity."
        ),
        "periodicity": 3,
    },
    {
        "name":        "Quick Draw (incl. 02 carabiners)",
        "category":    EquipmentCategory.RESCUE,
        "description": (
            "Two carabiners connected by a short sewn sling for rapidly attaching rope to "
            "anchor points in rope rescue systems. Standard component in vertical rescue "
            "rigging. Quarterly inspection covers carabiner gates, sling stitching, and "
            "webbing abrasion."
        ),
        "periodicity": 3,
    },
    {
        "name":        "Stop Lock Decender",
        "category":    EquipmentCategory.RESCUE,
        "description": (
            "Rope descender with auto-locking mechanism that arrests descent automatically "
            "when the operator releases the handle. Provides controlled, safe lowering during "
            "rope rescue. Quarterly check covers locking cam, sheave, and rope compatibility."
        ),
        "periodicity": 3,
    },
    {
        "name":        "Fixe Pully",
        "category":    EquipmentCategory.RESCUE,
        "description": (
            "Fixed-sheave rescue pulley for creating mechanical advantage in hauling and "
            "lowering systems. Used when heavy loads or victims must be raised from voids "
            "and depths. Quarterly check covers sheave rotation, side plates, and "
            "attachment point."
        ),
        "periodicity": 3,
    },
    {
        "name":        "Tandem Pully",
        "category":    EquipmentCategory.RESCUE,
        "description": (
            "Double-sheave pulley that travels along a fixed rope to create a travelling-"
            "pulley mechanical advantage system. Used in complex rope rescue haul systems. "
            "Quarterly check covers both sheaves, cam pawls, and load attachment."
        ),
        "periodicity": 3,
    },
    {
        "name":        "Gri-Gri",
        "category":    EquipmentCategory.RESCUE,
        "description": (
            "Assisted-braking belay and rappel device with a cam mechanism that grips the "
            "rope automatically if the operator loses grip. Provides a safety backup during "
            "descent. Quarterly check covers cam function, rope channel wear, and handle "
            "spring return."
        ),
        "periodicity": 3,
    },
    {
        "name":        "Manual Ascender (Left & Right)",
        "category":    EquipmentCategory.RESCUE,
        "description": (
            "Pair of mechanical rope clamps (jumar/ascender) for climbing a fixed rope. "
            "The left-hand and right-hand pair allows alternating hand movements for "
            "efficient vertical ascent. Quarterly check covers cam teeth, safety catch, "
            "and attachment holes."
        ),
        "periodicity": 3,
    },
    {
        "name":        "ID Jacket (Flourecent Orange Reflective)",
        "category":    EquipmentCategory.PERSONAL,
        "description": (
            "High-visibility fluorescent orange identification jacket with retro-reflective "
            "strips. Worn by Civil Defence responders at incident scenes for role "
            "identification and traffic safety. Six-monthly check covers reflective "
            "strip adhesion and jacket seam integrity."
        ),
        "periodicity": 6,
    },
    {
        "name":        "Semi Static Kernmental Rope 10-11 mm (100 mtr)",
        "category":    EquipmentCategory.RESCUE,
        "description": (
            "100-metre semi-static kernmantle rescue rope (10-11 mm diameter). Low-stretch "
            "design provides minimal elongation under load, making it ideal for rappelling "
            "and lowering systems. Life-critical: must be retired after any fall-arrest event. "
            "Quarterly check covers sheath condition, cuts, stiffness, and correct storage."
        ),
        "periodicity": 3,
    },
    {
        "name":        "Kernmental Rope 5-6 mm (100 mtr)",
        "category":    EquipmentCategory.RESCUE,
        "description": (
            "100-metre 5-6 mm accessory cord (kernmantle construction) for anchor slings, "
            "prusik friction hitches, and lashing in rope rescue systems. Not rated for "
            "primary life-safety load. Quarterly check covers sheath wear and knot-holding "
            "ability."
        ),
        "periodicity": 3,
    },
    {
        "name":        "Kernmental Rope 12.72-13.5 mm (100 mtr)",
        "category":    EquipmentCategory.RESCUE,
        "description": (
            "100-metre heavy-duty kernmantle rescue rope (12.72-13.5 mm diameter) for "
            "high-load haul systems and structural rescue operations. Rated for the "
            "heaviest rescue loads. Quarterly check covers sheath integrity, core "
            "condition via handling, and end terminations."
        ),
        "periodicity": 3,
    },
    {
        "name":        "Harness Chair (Rescue Chair)",
        "category":    EquipmentCategory.RESCUE,
        "description": (
            "Specialised seat harness configuration for rescuing conscious, injured, or "
            "panicked victims who cannot manage their own descent. Keeps the victim in a "
            "seated position during lowering. Quarterly inspection covers leg loop buckles, "
            "main tie-in point, and all webbing stitching."
        ),
        "periodicity": 3,
    },
    {
        "name":        "Seat Harness Adjustable",
        "category":    EquipmentCategory.RESCUE,
        "description": (
            "Adjustable waist-and-leg rescue harness for rope rescue operators. Distributes "
            "suspension load across the hips and thighs during work at height. Quarterly "
            "inspection covers webbing for cuts and abrasion, buckle auto-lock function, "
            "and belay loop stitching."
        ),
        "periodicity": 3,
    },
    {
        "name":        "Full Body Harness",
        "category":    EquipmentCategory.RESCUE,
        "description": (
            "Full-body rescue harness with chest, waist, and leg connections. Used for "
            "rescuing unconscious or injured persons and for operators in high-angle "
            "environments where inverted positions are possible. Quarterly check covers "
            "all straps, buckles, dorsal D-ring, and chest connection point."
        ),
        "periodicity": 3,
    },
    {
        "name":        "Hand held Search Light",
        "category":    EquipmentCategory.RESCUE,
        "description": (
            "High-intensity portable searchlight for illuminating incident scenes, collapsed "
            "structures, and flooded areas during night operations. Monthly check covers "
            "battery charge, bulb/LED condition, waterproofing seals, and beam alignment."
        ),
        "periodicity": 1,
    },
    {
        "name":        "Portable Emergency Lighting System",
        "category":    EquipmentCategory.OTHER,
        "description": (
            "Self-contained portable lighting tower or flood-light system for sustained "
            "illumination of large incident sites during prolonged operations. Monthly check "
            "covers generator fuel, bulb condition, mast extension mechanism, and "
            "electrical cable integrity."
        ),
        "periodicity": 1,
    },
    {
        "name":        "FRP Industrial Safety Helmet (Without Visor)",
        "category":    EquipmentCategory.PERSONAL,
        "description": (
            "Fibre-reinforced plastic hard hat meeting IS 2925 / EN 397 industrial safety "
            "standards. Protects against falling debris and impact injuries. Quarterly check "
            "covers shell for cracks or UV degradation, suspension harness integrity, and "
            "chin-strap condition."
        ),
        "periodicity": 3,
    },
    {
        "name":        "FRP Helmet with visor",
        "category":    EquipmentCategory.PERSONAL,
        "description": (
            "Fibre-reinforced plastic helmet with integrated clear polycarbonate visor for "
            "face protection against dust, sparks, and chemical splatter during rescue "
            "operations. Quarterly check covers visor clarity/scratches, visor mechanism, "
            "and shell condition."
        ),
        "periodicity": 3,
    },
    {
        "name":        "Safety Helmet with LED Lamp",
        "category":    EquipmentCategory.PERSONAL,
        "description": (
            "Hard hat with integrated rechargeable LED headlamp for hands-free lighting in "
            "confined spaces, collapsed structures, and night operations. Quarterly check "
            "covers helmet shell, LED lamp function, battery charge, and headlamp mounting."
        ),
        "periodicity": 3,
    },
    {
        "name":        "Mitton Gloves",
        "category":    EquipmentCategory.PERSONAL,
        "description": (
            "Heavy-duty work gloves (mitten style) for general handling of debris, rough "
            "materials, and equipment during rescue and relief operations. Six-monthly "
            "check covers material integrity and seam condition."
        ),
        "periodicity": 6,
    },
    {
        "name":        "Heavy Duty Working Gloves",
        "category":    EquipmentCategory.PERSONAL,
        "description": (
            "Cut-resistant and abrasion-resistant work gloves for rescue personnel handling "
            "glass shards, metal debris, and sharp edges in structural collapse situations. "
            "Quarterly check covers cut-resistance integrity, palm material, and wrist "
            "closure."
        ),
        "periodicity": 3,
    },
    {
        "name":        "Free fall arrest net with stand",
        "category":    EquipmentCategory.RESCUE,
        "description": (
            "Safety net system with portable stand frame, deployed below working areas to "
            "catch falling objects or personnel during rescue at height. Quarterly "
            "inspection covers net mesh for tears, stand joints, and anchor point strength."
        ),
        "periodicity": 3,
    },
    {
        "name":        "Hydraulic Jack",
        "category":    EquipmentCategory.RESCUE,
        "description": (
            "High-capacity hydraulic lifting jack for raising collapsed structural elements "
            "(beams, slabs, vehicle frames) during confined-space and structural collapse "
            "rescues. Monthly check covers hydraulic fluid level, seal condition, ram "
            "extension/retraction, and load rating label."
        ),
        "periodicity": 1,
    },
    {
        "name":        "Telescopic Aluminum Ladder (35ft)",
        "category":    EquipmentCategory.RESCUE,
        "description": (
            "Adjustable-length aluminium extension ladder reaching up to 35 feet (approx. "
            "10.7 m). Used for accessing upper floors, rescuing persons from heights, and "
            "crossing flood-water obstacles. Quarterly check covers rungs, locking "
            "mechanisms, and feet condition."
        ),
        "periodicity": 3,
    },
    {
        "name":        "Crow bar",
        "category":    EquipmentCategory.RESCUE,
        "description": (
            "Heavy forged-steel pry bar for forcible entry, debris removal, and leveraging "
            "collapsed structural elements during urban search and rescue. Six-monthly "
            "check covers straightness, tip condition, and absence of cracks."
        ),
        "periodicity": 6,
    },
    {
        "name":        "Spade (5ft)",
        "category":    EquipmentCategory.RESCUE,
        "description": (
            "Long-handled digging spade for clearing debris, earthworks, and channel-cutting "
            "during flood prevention, sand-bagging, and post-disaster cleanup. Six-monthly "
            "check covers blade sharpness, handle integrity, and socket joint."
        ),
        "periodicity": 6,
    },
    {
        "name":        "Shovel",
        "category":    EquipmentCategory.RESCUE,
        "description": (
            "Standard digging and scooping shovel for sand-bagging, debris clearing, and "
            "earthworks in flood prevention and disaster relief operations. Six-monthly "
            "check covers blade condition, handle, and socket."
        ),
        "periodicity": 6,
    },
    {
        "name":        "Sledge Hammer",
        "category":    EquipmentCategory.RESCUE,
        "description": (
            "Heavy sledgehammer (typically 4-6 kg head) for forcible entry through masonry, "
            "concrete walls, and padlocked metal during emergency rescue. Six-monthly "
            "check covers head-to-handle security and handle condition."
        ),
        "periodicity": 6,
    },
    {
        "name":        "Foot Tape Sling 120cm",
        "category":    EquipmentCategory.RESCUE,
        "description": (
            "120 cm nylon or Dyneema sewn tape sling for building anchor points in rope "
            "rescue systems. Looped over natural features or artificial anchors. Quarterly "
            "inspection covers webbing for cuts, abrasion, UV damage, and stitching."
        ),
        "periodicity": 3,
    },
    {
        "name":        "Foot Tape Sling 150 cm",
        "category":    EquipmentCategory.RESCUE,
        "description": (
            "150 cm nylon or Dyneema sewn tape sling for creating anchor extensions and "
            "equalised anchor systems in rope rescue. Longer length allows more versatile "
            "rigging. Quarterly inspection same as 120 cm sling."
        ),
        "periodicity": 3,
    },
    {
        "name":        "Come alone (Pulling & Lifting Machine)",
        "category":    EquipmentCategory.RESCUE,
        "description": (
            "Manual chain hoist (come-along) providing mechanical advantage (typically 4:1) "
            "for lifting and pulling heavy loads: vehicle extrication, structural beams, "
            "and large debris. Monthly check covers chain links, hooks, and ratchet mechanism."
        ),
        "periodicity": 1,
    },
    {
        "name":        "Woolen Blanket",
        "category":    EquipmentCategory.FLOOD,
        "description": (
            "Heavy woollen blanket for victim warming during flood, cold-weather, and "
            "shock treatment situations. Also used as ground cover and improvised stretcher "
            "padding. Six-monthly check covers fabric integrity, cleanliness, and storage."
        ),
        "periodicity": 6,
    },
    {
        "name":        "First Aid Box (with medicine)",
        "category":    EquipmentCategory.MEDICAL,
        "description": (
            "Comprehensive first aid kit containing bandages, antiseptics, analgesics, "
            "wound dressings, gloves, and emergency medicines. Essential at every deployment. "
            "Monthly check covers item quantities, expiry dates, and box integrity — "
            "expired/used items must be replaced immediately."
        ),
        "periodicity": 1,
    },
    {
        "name":        "Demolition Hammer",
        "category":    EquipmentCategory.RESCUE,
        "description": (
            "Electric or pneumatic demolition hammer (jackhammer) for breaking reinforced "
            "concrete and masonry during structural rescue operations and building access. "
            "Monthly check covers chisel condition, power supply, anti-vibration system, "
            "and trigger safety."
        ),
        "periodicity": 1,
    },
    {
        "name":        "Mega Phone with Sling",
        "category":    EquipmentCategory.COMM,
        "description": (
            "Battery-powered megaphone with shoulder sling for crowd control, victim "
            "communication in noisy environments, and public announcements during large-scale "
            "emergencies. Quarterly check covers battery charge, speaker clarity, volume, "
            "and sling condition."
        ),
        "periodicity": 3,
    },
    {
        "name":        "CBRN Mask With BA Set",
        "category":    EquipmentCategory.PERSONAL,
        "description": (
            "Full-face respirator with self-contained breathing apparatus (BA set) for use "
            "in Chemical, Biological, Radiological, and Nuclear hazard environments. "
            "Life-critical equipment. Monthly inspection covers face-seal, cylinder "
            "pressure, demand valve, and low-pressure alarm function."
        ),
        "periodicity": 1,
    },
    {
        "name":        "Search Camera with Accessories",
        "category":    EquipmentCategory.RESCUE,
        "description": (
            "Flexible fibre-optic or digital camera system (snake camera / victim locator) "
            "for finding survivors in voids and collapsed structures. Includes probe, monitor, "
            "and recording capability. Quarterly check covers probe flexibility, lens "
            "clarity, monitor function, and battery."
        ),
        "periodicity": 3,
    },
    {
        "name":        "Tripod with Winch",
        "category":    EquipmentCategory.RESCUE,
        "description": (
            "Heavy-duty tripod with mechanical winch for lowering rescuers and raising victims "
            "from confined spaces such as manholes, wells, and building voids. Monthly check "
            "covers winch brake, cable condition, tripod leg locks, and anchor point rating."
        ),
        "periodicity": 1,
    },
    {
        "name":        "Fire entry Suit with BA set",
        "category":    EquipmentCategory.FIRE,
        "description": (
            "Proximity fire entry suit with aluminised outer shell combined with a "
            "self-contained breathing apparatus. Provides thermal and respiratory protection "
            "for entry into burning structures. Life-critical. Monthly check covers suit "
            "seams, visor, BA cylinder pressure, and regulator function."
        ),
        "periodicity": 1,
    },
    {
        "name":        "SCUBA Set with Accessories",
        "category":    EquipmentCategory.FLOOD,
        "description": (
            "Self-Contained Underwater Breathing Apparatus with regulator, buoyancy control "
            "device (BCD), tank, mask, fins, and dive computer. Used for underwater search "
            "and rescue in flood and drowning incidents. Life-critical. Monthly check covers "
            "cylinder pressure, regulator breathing, BCD inflation, and all hose connections."
        ),
        "periodicity": 1,
    },
    {
        "name":        "Battery Operated Metal Cutter",
        "category":    EquipmentCategory.RESCUE,
        "description": (
            "Cordless angle grinder or reciprocating saw for cutting metal bars, vehicle "
            "frames, and metal shuttering during extrication and rescue. Monthly check "
            "covers battery charge, cutting disc/blade condition, guard integrity, and "
            "trigger safety."
        ),
        "periodicity": 1,
    },
    {
        "name":        "Boot Hard Toes (Gum Boot)",
        "category":    EquipmentCategory.PERSONAL,
        "description": (
            "Steel-toe rubber gum boot for protection in flooded, muddy, or chemically "
            "contaminated environments. Required footwear for all field staff in flood "
            "relief operations. Six-monthly check covers sole condition, steel toe cap "
            "exposure, and rubber integrity."
        ),
        "periodicity": 6,
    },
    {
        "name":        "Knee Pad",
        "category":    EquipmentCategory.PERSONAL,
        "description": (
            "Protective knee pads for rescue workers operating in confined spaces, on rough "
            "debris surfaces, and during prolonged kneeling in structural rescue. Six-monthly "
            "check covers padding integrity and strap buckles."
        ),
        "periodicity": 6,
    },
    {
        "name":        "Telescopic Stand with 02 Helogen Light",
        "category":    EquipmentCategory.RESCUE,
        "description": (
            "Adjustable-height telescopic lighting stand with two halogen or LED flood lamps "
            "for illuminating large work areas during night operations and extended rescues. "
            "Monthly check covers bulb condition, electrical cable, stand locking, and "
            "power source."
        ),
        "periodicity": 1,
    },
    {
        "name":        "Pole Purner",
        "category":    EquipmentCategory.RESCUE,
        "description": (
            "Long-handled pole pruner or pole saw for cutting overhead branches and "
            "vegetation that obstruct rescue access after storms and cyclones. Quarterly "
            "check covers blade sharpness, pole joint locks, and rope/trigger pull mechanism."
        ),
        "periodicity": 3,
    },
    {
        "name":        "INF Boat along with Accessories",
        "category":    EquipmentCategory.FLOOD,
        "description": (
            "Inflatable rubber rescue boat with paddles, foot pump, repair kit, and mooring "
            "lines for flood rescue operations. Deployed for accessing stranded persons in "
            "inundated areas. Monthly check covers inflation, seam integrity, valve "
            "condition, and accessory completeness."
        ),
        "periodicity": 1,
    },
    {
        "name":        "Out Board Motor (OBM)",
        "category":    EquipmentCategory.FLOOD,
        "description": (
            "Petrol-powered outboard motor for propelling inflatable or rigid rescue boats "
            "during flood operations. Monthly maintenance covers fuel system, spark plug, "
            "gearbox oil, propeller condition, and full engine start test."
        ),
        "periodicity": 1,
    },
    {
        "name":        "Life Buoy",
        "category":    EquipmentCategory.FLOOD,
        "description": (
            "Ring-type personal flotation device (life ring) thrown to persons in distress "
            "in open water. Attached to a heaving line for retrieval. Monthly check covers "
            "buoyancy foam integrity, ring cover, throw-line length and condition, and "
            "reflective tape."
        ),
        "periodicity": 1,
    },
    {
        "name":        "Civil Defence Rescue Vehicle (Big)",
        "category":    EquipmentCategory.OTHER,
        "description": (
            "Large Civil Defence Rescue Vehicle (CDRV) for transporting rescue teams, "
            "full equipment load, and supplies to incident sites. Serves as mobile command "
            "post and logistics base. Monthly check covers engine, tyres, lights, "
            "communication equipment on board, and rescue kit inventory."
        ),
        "periodicity": 1,
    },
    {
        "name":        "Civil Defence Rescue Vehicle (Mini)",
        "category":    EquipmentCategory.OTHER,
        "description": (
            "Compact Civil Defence Rescue Vehicle (Mini CDRV) for rapid response in "
            "congested urban areas and narrow lanes. Carries a core set of rescue equipment "
            "and a small response team. Monthly check covers engine, tyres, lights, and "
            "on-board equipment."
        ),
        "periodicity": 1,
    },
]


# ─────────────────────────────────────────────────────────────────────────────
# MANAGEMENT COMMAND
# ─────────────────────────────────────────────────────────────────────────────

class Command(BaseCommand):
    """
    Django management command: seed_equipment_types.

    Creates EquipmentType rows from EQUIPMENT_TYPE_SEED_DATA and then links
    existing Equipment rows to their type by matching Equipment.name to
    EquipmentType.name.
    """

    help = "Seed EquipmentType records and link existing Equipment rows to their types."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            default=False,
            help="Parse and print what would happen without writing to the database.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        self.stdout.write(f"Dry run: {dry_run}\n")

        # ── 1. Create / update EquipmentType rows ─────────────────────────────
        #
        # update_or_create uses `name` as the lookup key (it's unique).
        # defaults= are applied on both create AND update, so re-running
        # the command will refresh descriptions and periodicities if changed.

        self.stdout.write("Creating EquipmentType records …")
        created_count = 0
        updated_count = 0

        for entry in EQUIPMENT_TYPE_SEED_DATA:
            if dry_run:
                self.stdout.write(
                    f"  [DRY ] {entry['name'][:60]} "
                    f"| {entry['category']} | {entry['periodicity']}m"
                )
                continue

            _, was_created = EquipmentType.objects.update_or_create(
                name=entry["name"],
                defaults={
                    "category":                         entry["category"],
                    "description":                      entry["description"],
                    "scheduled_maintenance_periodicity": entry["periodicity"],
                },
            )
            if was_created:
                created_count += 1
            else:
                updated_count += 1

        if not dry_run:
            self.stdout.write(self.style.SUCCESS(
                f"  → {created_count} created, {updated_count} updated."
            ))

        # ── 2. Link existing Equipment rows to their EquipmentType ────────────
        #
        # The seed_equipment command sets Equipment.name = the equipment type
        # name (e.g. "Life Jacket with Reflective Panel").  We use this to
        # bulk-assign the equipment_type FK.
        #
        # Strategy:
        #   a. Build a dict { equipment_name → EquipmentType pk } from DB.
        #   b. Fetch all Equipment rows where equipment_type is null (or all).
        #   c. Set equipment_type_id on each and bulk_update in batches.

        if dry_run:
            # Count potential assignments without touching the DB.
            type_names = {e["name"] for e in EQUIPMENT_TYPE_SEED_DATA}
            would_update = Equipment.objects.filter(
                name__in=type_names,
                equipment_type__isnull=True,
            ).count()
            self.stdout.write(
                self.style.WARNING(
                    f"\n[DRY ] Would link ~{would_update} Equipment rows to their types."
                )
            )
            self.stdout.write(self.style.WARNING("DRY RUN — no records written."))
            return

        self.stdout.write("\nLinking Equipment rows to EquipmentType …")

        # Build a { name: EquipmentType instance } lookup from DB so we only
        # query the types table once instead of once per equipment row.
        type_by_name: dict[str, EquipmentType] = {
            et.name: et for et in EquipmentType.objects.all()
        }

        # Only fetch equipment that doesn't already have a type assigned.
        # Iterator() avoids loading all 28,263 rows into memory at once;
        # Django fetches them in batches from the database cursor.
        unlinked_qs = Equipment.objects.filter(equipment_type__isnull=True).iterator()

        batch:      list[Equipment] = []
        batch_size  = 500
        linked      = 0
        unmatched   = 0

        for equip in unlinked_qs:
            et = type_by_name.get(equip.name)
            if et is None:
                unmatched += 1
                continue
            equip.equipment_type = et
            batch.append(equip)

            # bulk_update writes a single SQL UPDATE per batch, much faster
            # than calling equip.save() individually for 28k rows.
            if len(batch) >= batch_size:
                Equipment.objects.bulk_update(batch, ["equipment_type"])
                linked += len(batch)
                batch = []

        # Flush the last partial batch.
        if batch:
            Equipment.objects.bulk_update(batch, ["equipment_type"])
            linked += len(batch)

        self.stdout.write(self.style.SUCCESS(f"  → {linked} Equipment rows linked."))
        if unmatched:
            self.stdout.write(
                self.style.WARNING(
                    f"  → {unmatched} Equipment rows had no matching EquipmentType "
                    f"(name mismatch — these remain untyped)."
                )
            )

        self.stdout.write(self.style.SUCCESS("\nDone."))
