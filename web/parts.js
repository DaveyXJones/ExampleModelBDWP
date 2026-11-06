// Everything a non-programmer may want to tweak lives in this file.
//
// PART_INFO  - the label title and the short description shown when a label is clicked.
//              Keys match the model's object names: PART_<Key>_<N|E|S|W>.
// EXPLODE    - how far each piece moves when its wall "explodes" (meters):
//              in    = toward the middle of the room
//              up    = straight up
//              along = sideways along the wall
//              order = when it starts moving (0 first, then 1, 2 ...)
//              fade  = see-through amount when exploded (1 = solid, 0.3 = mostly clear)
//              label = where the label sits: t = along the wall (-0.5 left end .. 0.5 right end,
//                      seen from inside the room), h = height on the piece (0 bottom .. 1 top)
// SECTIONS   - the hoverable sections, the text shown while one is open, and per-wall overrides.

export const PART_INFO = {
  // ---- walls (in the model now) ----
  PerimeterDrain: {
    title: 'Interior Perimeter Drain',
    text: 'Collects water where it sits and moves it along the system into our sump pit.',
  },
  DimpleBoard: {
    title: 'DrainTile Dimple Board',
    text: 'Creates an air pocket between the wall/slab and the perimeter drain, so water can move freely into the drain.',
  },
  WallMembrane: {
    title: 'Wall Membrane / Vapor Barrier',
    text: 'Protects your basement from moisture on the walls.',
  },
  WallMembraneFull: {
    title: 'Full-Height Wall Membrane (Upgrade)',
    text: 'The upgrade runs the wall membrane all the way up the wall, protecting the whole wall from moisture.',
  },
  WeepHoles: {
    title: 'Weep Holes',
    text: 'Holes drilled into the bottom row of block let water trapped inside the hollow block cores drain into the system.',
  },

  // ---- sump area (in the model now) ----
  SumpPit: {
    title: 'Sump Pit & Lid',
    text: 'A 30-gallon basin that collects the water from your basement.',
  },
  SumpPump: {
    title: 'Sump Pump',
    text: 'Pumps the collected water up and out through the discharge line.',
  },
  BatteryBackup: {
    title: 'Battery Backup Pump',
    text: 'Protection during power outages. If the power goes out, this smaller pump runs on a connected battery/inverter setup.',
  },
  BackupBattery: {
    title: 'Battery & Inverter',
    text: 'Powers the backup pump when the power goes out.',
  },
  YFitting: {
    title: 'Y Fitting',
    text: 'Joins the main pump and the backup pump, so a single 1.5" PVC line carries the water out for either pump.',
  },
  CheckValve: {
    title: 'Check Valve',
    text: 'Stops the water in the discharge line from running back down into the sump pit when the pump shuts off.',
  },
  DischargeLine: {
    title: 'Discharge Line',
    text: '1.5" or 2" Schedule 40 PVC pipe that carries the water from the sump to the outside of your home.',
  },

  // ---- window well and dehumidifier (in the model now) ----
  Dehumidifier: {
    title: 'Dehumidifier',
    text: 'Removes the moisture in the air. It can be connected to the BDRY system for easy drainage.',
  },
  WindowWell: {
    title: 'Window Well',
    text: 'Keeps water from spilling into or under your basement windows.',
  },

  // ---- crack in the poured wall (pump injection ports/hookup to be added once we have the reference) ----
  CrackRepair: {
    title: 'Crack Injection',
    text: 'Polyurethane crack injection fills the voids and cracks that water often finds its way into.',
  },
};

export const EXPLODE = {
  WallMembrane:     { in: 0.30, up: 1.15, order: 0, label: { t: -0.32, h: 0.95 } },
  WallMembraneFull: { in: 0.75, up: 1.25, order: 0, fade: 0.8, label: { t: -0.22, h: 0.9 } },
  DimpleBoard:      { in: 0.15, up: 0.58, order: 1, label: { t: -0.1, h: 0.85 } },
  WeepHoles:        { in: 0.00, up: 0.00, order: 0, label: { t: 0.1, h: 0.5 } },
  PerimeterDrain:   { in: 0.45, up: 0.34, order: 2, label: { t: 0.3, h: 0.6 } },
  Stone:            { in: 0.85, up: 0.30, order: 1 },
  Patch:            { in: 1.25, up: 0.15, order: 0 },

  // sump area: 'in' points from the corner toward the middle of the room, 'along' toward the
  // north wall (negative = along the west wall). The basin, pumps and lid lift out as a stack in
  // front of the west wall; the check valve, discharge line and battery stay put.
  SumpPatch:        { in: 1.30, along: 0.5, up: 0.10, order: 0 },
  SumpPit:          { in: 0.70, along: -0.6, up: 0.72, order: 1, label: { h: 0.55 } },
  SumpPump:         { in: 0.70, along: -0.6, up: 1.65, order: 2, label: { h: 0.45 } },
  BatteryBackup:    { in: 0.70, along: -0.6, up: 1.65, order: 2, label: { h: 0.3 } },
  YFitting:         { in: 0.70, along: -0.6, up: 1.65, order: 2, label: { h: 0.5 } },
  SumpLid:          { in: 0.70, along: -0.6, up: 2.15, order: 3 },
  CheckValve:       { label: { h: 0.6 } },
  DischargeLine:    {},   // label position comes from the model (LBL_ empty)
  BackupBattery:    { label: { h: 0.95 } },

  // window well: slides along the wall to uncover the window and the gravel bed under it
  WindowWell:       { in: 0.55, along: 1.15, up: 0 },
  // dehumidifier: a small lift so it is clear it's selected
  Dehumidifier:     { in: 0.12, up: 0.15 },
  // crack: the polyurethane that fills it slides out of the wall to show it fills the full thickness
  CrackRepair:      { in: 0.5, up: 0.05, label: { h: 0.85 } },
};

// inward/along are three.js directions: +x east, -z north, +y up.
export const SECTIONS = {
  SEC_WallNorth: { title: 'Standard 2 ft wall system', inward: [0, 0, 1], along: [1, 0, 0] },
  SEC_WallEast:  { title: 'Standard 2 ft wall system', inward: [-1, 0, 0], along: [0, 0, 1] },
  SEC_WallSouth: { title: 'Standard 2 ft wall system', inward: [0, 0, -1], along: [-1, 0, 0] },
  SEC_WallWest:  {
    title: 'Full-height wall system (upgrade)', inward: [1, 0, 0], along: [0, 0, -1],
    explode: { DimpleBoard: { in: 0.38, up: 0.62, label: { t: 0.02, h: 0.3 } } },
  },
  SEC_SumpArea:  { title: 'Sump pump system with battery backup', inward: [0.7071, 0, 0.7071], along: [0.7071, 0, -0.7071] },
  SEC_WindowWell:   { title: 'Window well', inward: [0, 0, 1], along: [1, 0, 0] },  // 'in' = away from the house here
  SEC_Dehumidifier: { title: 'Dehumidifier', inward: [0, 0, 1], along: [1, 0, 0] },
  // the crack is on the north wall, so it turns see-through together with that wall
  SEC_CrackRepair:  { title: 'Crack injection (poured wall)', inward: [0, 0, 1], along: [1, 0, 0], fadeWith: 'SEC_WallNorth' },
  SEC_FloorSlab: { title: 'Floor slab' },
};

export const TIMING = {
  duration: 0.6,       // seconds for one piece to move
  stagger: 0.12,       // delay between 'order' groups
  collapseSpeed: 1.5,  // closing is this much faster than opening
  leaveDelay: 380,     // ms the cursor can be off a section before it closes
};

export const VIEW = {
  home: { position: [8.9, 10, 11.9], target: [-0.6, 0, -0.6] },
  wheelZoomSpeed: 5,      // mouse wheel step size (1 = three.js default ~5% per notch; 5 = ~23% per notch)
  touchZoomSpeed: 1,      // pinch zoom (1 = follows your fingers)
  minDistance: 0.12,      // closest zoom in meters (~5"), close enough for weep holes and pipe slots
  maxDistance: 30,
  fadedWallOpacity: 0.12, // walls between the camera and the room turn see-through
  envIntensity: 0.55,
  sunIntensity: 2.2,
  hemiIntensity: 0.55,
};
