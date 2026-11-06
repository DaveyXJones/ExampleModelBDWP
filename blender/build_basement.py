"""
BDRY basement waterproofing model builder.

Rebuilds the whole model from code: textures, materials, geometry and names.
Edit this script (not the .blend) so the model stays reproducible.
Run it inside Blender (Claude runs it through the Blender MCP):

    p = r"<project folder>/blender/build_basement.py"   # the full path to this file
    exec(open(p).read(), {"__file__": p, "RUN": "all"})

RUN = "build"  -> rebuild the model and save blender/bdry_basement.blend
RUN = "export" -> export exports/bdry_basement.glb (Draco) and copy it to web/models/,
                  plus exports/bdry_basement_nodraco.glb without Draco, for hosts where the
                  viewer can't fetch the Draco decoder from the CDN
RUN = "all"    -> both

Coordinates: meters, Z up, +Y = north, top of the floor slab at Z = 0.
Names (the web viewer depends on them):
  SEC_<Name>                hover/tap sections (parent empties)
  PART_<Type>_<N|E|S|W>     labeled system parts; the web looks labels up by <Type>
  SHELL_*                   house structure (not labeled, never moves)
  FILL_*                    concrete patch, sump and window-well stone (not labeled)
"""
import bpy, bmesh, math, os, shutil
import numpy as np
from mathutils import Vector

try:
    PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
except NameError:
    # No __file__ (e.g. pasted into Blender's text editor): use the open .blend, which lives in blender/.
    if not bpy.data.filepath:
        raise RuntimeError("Run with __file__ set (see the top of this file) or open blender/bdry_basement.blend first")
    PROJECT = os.path.dirname(os.path.dirname(bpy.data.filepath))
RUN = globals().get("RUN", "all")

TEX_DIR = os.path.join(PROJECT, "blender", "textures")
BLEND_PATH = os.path.join(PROJECT, "blender", "bdry_basement.blend")
GLB_PATH = os.path.join(PROJECT, "exports", "bdry_basement.glb")
GLB_NODRACO_PATH = os.path.join(PROJECT, "exports", "bdry_basement_nodraco.glb")
WEB_GLB_PATH = os.path.join(PROJECT, "web", "models", "bdry_basement.glb")
ROOT_COLL = "BDRY_Model"

# ------------------------------------------------------------------ dimensions
IN = 0.0254
FT = 12 * IN
ROOM_X, ROOM_Y = 30 * FT, 24 * FT          # interior, wall face to wall face
XE, YN = ROOM_X / 2, ROOM_Y / 2
XW, YS = -XE, -YN
WALL_T = 10 * IN                            # 10" concrete block
SLAB_T = 4 * IN
FOOT_TOP = -SLAB_T                          # footing top = underside of slab
FOOT_T = 10 * IN
FOOT_PROJ = 6 * IN                          # footing sticks out 6" past the wall face
COURSE, BLOCK_L = 8 * IN, 16 * IN
N_COURSES = 12
WALL_TOP = FOOT_TOP + N_COURSES * COURSE    # ~7'8" above the floor
TRENCH_W = 17 * IN                          # an average trench, measured from the wall face
TRENCH_D = 10 * IN                          # measured from the top of the floor (confirmed)
PIPE_R = 4.2 * IN / 2                       # 4" ribbed slotted PVC, ~4.2" OD
FIT_R = PIPE_R + 0.006                      # fittings are a bit fatter
PIPE_OFF = FOOT_PROJ + PIPE_R + 0.5 * IN    # pipe sits beside the footing, so its cleanout cap lands in the
                                            # middle of the new concrete over the 17" trench
BED_T = 1 * IN                              # 1" bed of 1B pea gravel on the trench bottom
PIPE_Z = -TRENCH_D + BED_T + PIPE_R         # the pipe rests on that bed
BEND_R = 0.10                               # 90 elbow centerline radius
DIMPLE_T = 0.008
PANEL_T = 0.004
SYS_FRONT = DIMPLE_T + PANEL_T
SYS_H = 24 * IN                             # standard 2 ft wall system
DIMPLE_FOOT = 6 * IN                        # dimple leg across the footing
SILL_T, SILL_W = 1.5 * IN, 5.5 * IN
RIM_T, RIM_H = 1.5 * IN, 9.25 * IN
SUBBASE_BOTTOM = -0.80                      # deep enough for the sump basin
WEEP_Z = FOOT_TOP + 0.05                    # weep holes in the bottom course, inside the trench
WEEP_R = 0.5 * IN
WEEP_DEPTH = 1.5 * IN                       # through the block's face shell into the core
WEEP_CUTS = {}                              # side -> hole centres, filled by build_wall, cut in cut_holes
WIN_W, WIN_H = 32 * IN, 16 * IN
BLOCK_TILE = 2 * BLOCK_L                    # block texture = 2 blocks x 4 courses (32" square)

SIDES = {
    "N": dict(sec="SEC_WallNorth", along="x", face=YN, sign=-1),
    "E": dict(sec="SEC_WallEast", along="y", face=XE, sign=-1),
    "S": dict(sec="SEC_WallSouth", along="x", face=YS, sign=+1),
    "W": dict(sec="SEC_WallWest", along="y", face=XW, sign=+1),
}
FULL_HEIGHT_SIDE = "W"                                     # full-wall upgrade (an E or W wall: N/S own the corners)
# Full-wall upgrade, from the wall out: dimple board (optional on real jobs, shown here), an 11-14 mil white
# vapor barrier over the whole wall that wraps WRAP onto the next walls, then the standard 2 ft system on top.
BARRIER_T = 0.002                                          # the barrier, drawn 2 mm thick
WRAP = 18 * IN                                             # wraps 1-2 ft around each corner
WRAP_GAP = 0.02                                            # the sheet that moves stops this short of each corner;
                                                           # the corner strips belong to the wraps (they stay)
UPG_T = DIMPLE_T + BARRIER_T                               # what sits behind the 2 ft system on the upgrade wall
POURED_SIDES = {"N"}                                       # poured concrete (with the crack); the rest are block
POURED_TILE = 4 * FT                                       # poured texture: 4 ft square, form seams every 2 ft
WINDOWS = {"N": (2 * BLOCK_L, 4 * BLOCK_L), "S": (-4 * BLOCK_L, -2 * BLOCK_L)}
CLEANOUT_AT = {"N": XE - 0.6, "E": YS + 0.6, "S": XE - 0.6, "W": YS + 0.6}  # near a corner

# ---- sump area (NW corner) ----
SUMP_A = 21 * IN                            # basin centre, measured from both walls (clears the footings)
SUMP_C = Vector((XW + SUMP_A, YN - SUMP_A, 0.0))
SUMP_SQ = (6 * IN, 36 * IN)                 # dug-out square around the basin, measured from both walls
BASIN_RT, BASIN_RB, BASIN_D = 10 * IN, 8.25 * IN, 26 * IN   # about 30 gallons
BASIN_FLANGE, BASIN_WALL, LID_T = 11 * IN, 0.006, 0.012
SUMP_ENDS = {"N": "lo", "W": "hi"}          # these drains turn 45 degrees into the basin instead of the corner
TAIL_TURN = SUMP_A - PIPE_OFF               # the 45 sits this far past the basin centre line
BEND45_R = 0.08
PVC15_R = 1.9 * IN / 2                      # 1.5" Sch40 PVC (1.9" OD)
PVC15_FIT = PVC15_R + 0.005
Y_Z = -0.13                                 # Y fitting joining the two pumps, inside the basin
CHECK_Z = LID_T + 1 * IN                    # check valve sits 1" above the lid, on the single line (confirmed)
EXIT_Z = WALL_TOP + SILL_T + RIM_H / 2      # discharge goes out through the middle of the rim joist
PUMP_DIR = Vector((0.778, 0.628, 0.0)).normalized()   # main pump toward the north wall, backup opposite
MAIN_XY = SUMP_C + PUMP_DIR * 0.098         # (lands the riser in the joist bay between two joists)
BACK_XY = SUMP_C - PUMP_DIR * 0.11

# ---- window well (on the south window, the side facing the default camera) ----
WELL_SIDE = "S"
WELL_HALF_W = WIN_W / 2 + 5 * IN            # reaches 5" past each side of the window
WELL_OUT = 18 * IN                          # sticks out 18" from the wall
WELL_Z0 = WALL_TOP - WIN_H - 12 * IN        # bottom 12" below the window
WELL_Z1 = WELL_Z0 + 24 * IN                 # 24" tall, top a few inches above grade
WELL_GRAVEL = 6 * IN                        # gravel bed, 6" below the window

# ---- crack in the poured north wall: diagonal from the window's lower west corner, down and west ----
CRACK_FROM = (WINDOWS["N"][0], WALL_TOP - WIN_H)
CRACK_TO = (0.36, 0.62)                     # (x, z); ends above the 2 ft wall panel

# ---- dehumidifier (floor, north wall, east of the sump battery; drains into the sump) ----
DEHU = (XW + 1.55, XW + 2.10, YN - 0.60, YN - 0.32)   # x0, x1, y front, y back (partly on the trench patch)
DEHU_H = 0.53

# ---- water heater with a drain grate around it (east wall, across from the full-wall upgrade) ----
# The heater stands on a square of the old slab (the island). The trench goes around the island in a U, the
# 4" pipe jogs out along it, and a channel drain sits on top; its legs run back to the wall, where the wall
# system stops on either side of the heater. 1.5" PVC male adapters join the channel to the pipe below.
WH_SIDE = "E"
WH_S = 1.0                                  # tank centre along the east wall (north of the middle)
WH_R, WH_H = 10 * IN, 58 * IN               # 20" x 58" tank (about 50 gallons)
WH_D = 3 * IN + WH_R                        # tank centre from the wall face (it stands 3" off the wall)
ISLE_M = 4 * IN                             # old slab left around the tank
ISLE = (WH_S - WH_R - ISLE_M, WH_S + WH_R + ISLE_M, WH_D + WH_R + ISLE_M)   # s0, s1, depth from the wall
U_W = 12 * IN                               # width of the U trench
U_OUT = ISLE[2] + U_W                       # how far the U reaches into the room
U_S, U_N = ISLE[0] - U_W / 2, ISLE[1] + U_W / 2   # centre lines of the U's two legs (along the wall)
U_F = ISLE[2] + U_W / 2                     # and of its front run (from the wall)
SYS_PAD = 0.005                             # the wall system stops this short of the U trench
GRATE_W = 5 * IN                            # channel drain: 5" wide, 4" deep, top flush with the floor
GRATE_LIP = 0.4 * IN                        # channel rim on each side of the grate
ADAPTERS = ((U_S, (PIPE_OFF + U_F) / 2), (WH_S, U_F), (U_N, (PIPE_OFF + U_F) / 2))   # (s, d), one per run
ADAPT_R = 1.1 * IN                          # 1.5" PVC male adapter, socket end
HUB_Z = FOOT_TOP - 0.4 * IN                 # bottom of the channel's outlet hubs (the adapters thread in)


def P(side, s, d, z):
    """Point from wall coords: s = along the wall, d = distance into the room from the wall face."""
    w = SIDES[side]
    off = w["face"] + w["sign"] * d
    return Vector((s, off, z)) if w["along"] == "x" else Vector((off, s, z))


def inward(side):
    w = SIDES[side]
    return Vector((0, w["sign"], 0)) if w["along"] == "x" else Vector((w["sign"], 0, 0))


def along_vec(side):
    return Vector((1, 0, 0)) if SIDES[side]["along"] == "x" else Vector((0, 1, 0))


def span(side):
    return (XW, XE) if SIDES[side]["along"] == "x" else (YS, YN)


def owns_corners(side):
    return SIDES[side]["along"] == "x"      # north and south walls run through the corners


def sys_off(side):
    """How far a wall's standard 2 ft system sits off its face (the upgrade wall has dimple + barrier behind)."""
    return UPG_T if side == FULL_HEIGHT_SIDE else 0.0


def end_wall(side, end):
    """The wall at this end ('lo' or 'hi') of a wall."""
    if SIDES[side]["along"] == "x":
        return "W" if end == "lo" else "E"
    return "S" if end == "lo" else "N"


def wall_gap(side):
    """The stretch of a wall the water heater's U trench takes: the wall's own trench and system stop there."""
    return (ISLE[0] - U_W, ISLE[1] + U_W) if side == WH_SIDE else None


def around(a, b, gap, pad=0.0):
    """The parts of [a, b] outside the gap (widened by pad)."""
    if gap is None:
        return [(a, b)]
    return [(x0, x1) for x0, x1 in ((a, min(b, gap[0] - pad)), (max(a, gap[1] + pad), b)) if x1 - x0 > 1e-4]


def slab_outline():
    """Main slab outline inside the trenches, notched on the east side for the water heater's U trench."""
    assert WH_SIDE == "E"
    x0, x1, y0, y1 = XW + TRENCH_W, XE - TRENCH_W, YS + TRENCH_W, YN - TRENCH_W
    g0, g1 = wall_gap(WH_SIDE)
    xn = XE - U_OUT
    return [(x0, y0), (x1, y0), (x1, g0), (xn, g0), (xn, g1), (x1, g1), (x1, y1), (x0, y1)]


def lin(c):
    return tuple(((x + 0.055) / 1.055) ** 2.4 if x > 0.04045 else x / 12.92 for x in c)


# ------------------------------------------------------------------ mesh builder
class MB:
    def __init__(self):
        self.bm = bmesh.new()
        self.uv = self.bm.loops.layers.uv.verify()
        self.mats = []

    def mi(self, mat):
        if mat not in self.mats:
            self.mats.append(mat)
        return self.mats.index(mat)

    def _orient(self, faces):
        vol = 0.0
        for f in faces:
            vs = [v.co for v in f.verts]
            for i in range(1, len(vs) - 1):
                vol += vs[0].dot(vs[i].cross(vs[i + 1]))
        if vol < 0:
            bmesh.ops.reverse_faces(self.bm, faces=faces)

    def box(self, x0, x1, y0, y1, z0, z1, mat, tile=1.0, uoff=0.0, voff=0.0):
        xs, ys, zs = sorted((x0, x1)), sorted((y0, y1)), sorted((z0, z1))
        if min(xs[1] - xs[0], ys[1] - ys[0], zs[1] - zs[0]) < 1e-6:
            return
        bm, idx = self.bm, self.mi(mat)
        V = [bm.verts.new((xs[i], ys[j], zs[k])) for k in (0, 1) for j in (0, 1) for i in (0, 1)]
        v = lambda i, j, k: V[k * 4 + j * 2 + i]
        quads = [
            ((v(0, 0, 0), v(0, 1, 0), v(1, 1, 0), v(1, 0, 0)), "z"),
            ((v(0, 0, 1), v(1, 0, 1), v(1, 1, 1), v(0, 1, 1)), "z"),
            ((v(0, 0, 0), v(1, 0, 0), v(1, 0, 1), v(0, 0, 1)), "y"),
            ((v(0, 1, 0), v(0, 1, 1), v(1, 1, 1), v(1, 1, 0)), "y"),
            ((v(0, 0, 0), v(0, 0, 1), v(0, 1, 1), v(0, 1, 0)), "x"),
            ((v(1, 0, 0), v(1, 1, 0), v(1, 1, 1), v(1, 0, 1)), "x"),
        ]
        faces = []
        for q, ax in quads:
            f = bm.faces.new(q)
            f.material_index = idx
            for loop in f.loops:
                c = loop.vert.co
                u, w = (c.x, c.y) if ax == "z" else ((c.x, c.z) if ax == "y" else (c.y, c.z))
                loop[self.uv].uv = ((u - uoff) / tile, (w - voff) / tile)
            faces.append(f)
        self._orient(faces)

    def wbox(self, side, s0, s1, d0, d1, z0, z1, mat, **kw):
        a, b = P(side, s0, d0, z0), P(side, s1, d1, z1)
        self.box(a.x, b.x, a.y, b.y, a.z, b.z, mat, **kw)

    def cyl(self, p0, p1, r, mat, segs=24, vtile=None, v0=0.0, caps=True):
        bm, idx = self.bm, self.mi(mat)
        p0, p1 = Vector(p0), Vector(p1)
        axis = p1 - p0
        L = axis.length
        if L < 1e-6:
            return
        a = axis / L
        ref = Vector((0, 0, 1)) if abs(a.z) < 0.99 else Vector((1, 0, 0))
        e_up = (ref - a * ref.dot(a)).normalized()          # theta = 0 at the top of the pipe
        e_side = a.cross(e_up)
        r0, r1 = [], []
        for i in range(segs):
            t = 2 * math.pi * i / segs
            d = e_up * math.cos(t) + e_side * math.sin(t)
            r0.append(bm.verts.new(p0 + d * r))
            r1.append(bm.verts.new(p1 + d * r))
        vt = vtile or 1.0
        faces = []
        for i in range(segs):
            j = (i + 1) % segs
            f = bm.faces.new((r0[i], r0[j], r1[j], r1[i]))
            f.material_index, f.smooth = idx, True
            uvs = [(i / segs, v0 / vt), ((i + 1) / segs, v0 / vt),
                   ((i + 1) / segs, (v0 + L) / vt), (i / segs, (v0 + L) / vt)]
            for loop, uv in zip(f.loops, uvs):
                loop[self.uv].uv = uv
            faces.append(f)
        if caps:
            for ring in (r0, r1):
                f = bm.faces.new(list(reversed(ring)) if ring is r0 else ring)
                f.material_index = idx
                for loop in f.loops:
                    loop[self.uv].uv = (0.5, 0.5)
                faces.append(f)
                for i in range(segs):
                    e = bm.edges.get((ring[i], ring[(i + 1) % segs]))
                    if e:
                        e.smooth = False
        self._orient(faces)

    def elbow(self, center, e1, e2, R, r, mat, segs=24, steps=10, angle=math.pi / 2):
        """Torus segment starting at center+e1*R, heading along e2, sweeping `angle`."""
        bm, idx = self.bm, self.mi(mat)
        rings = []
        for k in range(steps + 1):
            phi = angle * k / steps
            radial = e1 * math.cos(phi) + e2 * math.sin(phi)
            tangent = -e1 * math.sin(phi) + e2 * math.cos(phi)
            nrm = radial.cross(tangent)
            c = center + radial * R
            rings.append([bm.verts.new(c + (radial * math.cos(2 * math.pi * i / segs) +
                                            nrm * math.sin(2 * math.pi * i / segs)) * r)
                          for i in range(segs)])
        faces = []
        for k in range(steps):
            a, b = rings[k], rings[k + 1]
            for i in range(segs):
                j = (i + 1) % segs
                f = bm.faces.new((a[i], b[i], b[j], a[j]))
                f.material_index, f.smooth = idx, True
                for loop in f.loops:
                    loop[self.uv].uv = (0.5, 0.5)
                faces.append(f)
        for ring in (rings[0], rings[-1]):
            f = bm.faces.new(ring if ring is rings[0] else list(reversed(ring)))
            f.material_index = idx
            faces.append(f)
            for i in range(segs):
                e = bm.edges.get((ring[i], ring[(i + 1) % segs]))
                if e:
                    e.smooth = False
        self._orient(faces)

    def bend(self, corner, d_in, d_out, R, r, mat, segs=24):
        """Pipe bend at `corner` between two straight runs; returns the bend's start and end points."""
        d_in, d_out = Vector(d_in).normalized(), Vector(d_out).normalized()
        ang = d_in.angle(d_out)
        L = R * math.tan(ang / 2)
        start = Vector(corner) - d_in * L
        n = (d_out - d_in * d_out.dot(d_in)).normalized()
        self.elbow(start + n * R, -n, d_in, R, r, mat, segs=segs, steps=max(3, round(ang / 0.16)), angle=ang)
        return start, Vector(corner) + d_out * L

    def pipe_path(self, pts, r, R, mat, fit_r=None, segs=20):
        """Pipe through a list of points, with a bend (fitting) at every corner."""
        pts = [Vector(p) for p in pts]
        starts, ends = [pts[0]], []
        for k in range(1, len(pts) - 1):
            d_in, d_out = pts[k] - pts[k - 1], pts[k + 1] - pts[k]
            if d_in.angle(d_out) < 1e-3:
                ends.append(pts[k]); starts.append(pts[k])
                continue
            a, b = self.bend(pts[k], d_in, d_out, R, fit_r or r, mat, segs=segs)
            ends.append(a); starts.append(b)
        ends.append(pts[-1])
        for a, b in zip(starts, ends):
            self.cyl(a, b, r, mat, segs=segs)

    def lathe(self, center, profile, mat, segs=32):
        """Solid of revolution around a vertical axis; profile = [(radius, z), ...] from axis to axis."""
        bm, idx = self.bm, self.mi(mat)
        c = Vector(center)
        rings = []
        for r, z in profile:
            if r < 1e-7:
                rings.append([bm.verts.new((c.x, c.y, z))])
            else:
                rings.append([bm.verts.new((c.x + r * math.cos(2 * math.pi * i / segs),
                                            c.y + r * math.sin(2 * math.pi * i / segs), z)) for i in range(segs)])
        faces = []
        for a, b in zip(rings, rings[1:]):
            if len(a) == 1 and len(b) == 1:
                continue
            for i in range(segs):
                j = (i + 1) % segs
                vs = ((a[0], b[j], b[i]) if len(a) == 1 else
                      (a[i], a[j], b[0]) if len(b) == 1 else (a[i], a[j], b[j], b[i]))
                f = bm.faces.new(vs)
                f.material_index, f.smooth = idx, True
                for loop in f.loops:
                    loop[self.uv].uv = (0.5, 0.5)
                faces.append(f)
        for ring in rings:                      # every profile corner stays crisp
            for i in range(len(ring) if len(ring) > 1 else 0):
                e = bm.edges.get((ring[i], ring[(i + 1) % segs]))
                if e:
                    e.smooth = False
        self._orient(faces)

    def tube(self, pts, r, mat, segs=10):
        """Round tube through a smooth list of points (a hose, a rolled edge); no fittings."""
        bm, idx = self.bm, self.mi(mat)
        pts = [Vector(p) for p in pts]
        rings, side = [], None
        for k, p in enumerate(pts):
            a = pts[max(k - 1, 0)]
            b = pts[min(k + 1, len(pts) - 1)]
            t = (b - a).normalized()
            if side is None:
                side = t.cross(Vector((0, 0, 1)) if abs(t.z) < 0.9 else Vector((1, 0, 0)))
            side = (side - t * side.dot(t)).normalized()       # carry the frame along without twisting
            upv = side.cross(t)
            rings.append([bm.verts.new(p + (side * math.cos(2 * math.pi * i / segs) +
                                            upv * math.sin(2 * math.pi * i / segs)) * r) for i in range(segs)])
        faces = []
        for ra, rb in zip(rings, rings[1:]):
            for i in range(segs):
                j = (i + 1) % segs
                f = bm.faces.new((ra[i], ra[j], rb[j], rb[i]))
                f.material_index, f.smooth = idx, True
                faces.append(f)
        for ring, cap in ((rings[0], list(reversed(rings[0]))), (rings[-1], rings[-1])):
            f = bm.faces.new(cap)
            f.material_index = idx
            faces.append(f)
            for i in range(segs):
                e = bm.edges.get((ring[i], ring[(i + 1) % segs]))
                if e:
                    e.smooth = False
        for f in faces:
            for loop in f.loops:
                loop[self.uv].uv = (0.5, 0.5)
        self._orient(faces)

    def prism(self, poly, z0, z1, mat, tile=1.0):
        """Vertical prism from a convex 2D outline [(x, y), ...]."""
        bm, idx = self.bm, self.mi(mat)
        bot = [bm.verts.new((x, y, z0)) for x, y in poly]
        top = [bm.verts.new((x, y, z1)) for x, y in poly]
        faces = [bm.faces.new(list(reversed(bot))), bm.faces.new(top)]
        for i in range(len(poly)):
            j = (i + 1) % len(poly)
            faces.append(bm.faces.new((bot[i], bot[j], top[j], top[i])))
        for f in faces:
            f.material_index = idx
            f.normal_update()
            flat = abs(f.normal.z) > 0.5
            for loop in f.loops:
                c = loop.vert.co
                loop[self.uv].uv = (c.x / tile, c.y / tile) if flat else ((c.x + c.y) / tile, c.z / tile)
        self._orient(faces)

    def bore(self, center, n, r, depth, mat_side, mat_end, segs=16):
        """Inside of a drilled hole: open at the wall face, dark at the bottom (`n` points out of the wall)."""
        n = Vector(n).normalized()
        ref = Vector((0, 0, 1)) if abs(n.z) < 0.9 else Vector((1, 0, 0))
        e1 = (ref - n * ref.dot(n)).normalized()
        e2 = n.cross(e1)
        ring = lambda c: [self.bm.verts.new(c + (e1 * math.cos(2 * math.pi * i / segs) +
                                                 e2 * math.sin(2 * math.pi * i / segs)) * r) for i in range(segs)]
        a, b = ring(Vector(center)), ring(Vector(center) - n * depth)
        si, ei = self.mi(mat_side), self.mi(mat_end)
        for i in range(segs):
            j = (i + 1) % segs
            f = self.bm.faces.new((a[i], a[j], b[j], b[i]))       # normals face the hole's axis
            f.material_index, f.smooth = si, True
        f = self.bm.faces.new(b)                                  # bottom of the hole, facing out
        f.material_index = ei
        for e in (self.bm.edges.get((b[i], b[(i + 1) % segs])) for i in range(segs)):
            if e:
                e.smooth = False

    def quad(self, corners, uvs, mat, facing=(0, 0, 1)):
        """One flat face with its own UVs, turned to face `facing`."""
        vs = [self.bm.verts.new(c) for c in corners]
        uv_of = dict(zip(vs, uvs))
        f = self.bm.faces.new(vs)
        f.material_index = self.mi(mat)
        f.normal_update()
        if f.normal.dot(Vector(facing)) < 0:
            f.normal_flip()
        for loop in f.loops:
            loop[self.uv].uv = uv_of[loop.vert]

    def pipe_hole(self, top, axis, R, r, mat, segs=20):
        """Dark hole drilled into the top of a horizontal pipe: a fan hugging the pipe just above its surface.
        `top` is the top of the pipe at the hole's centre, `axis` the pipe's direction."""
        axis = Vector(axis).normalized()
        side = axis.cross(Vector((0, 0, 1))).normalized()
        centre = Vector(top) - Vector((0, 0, R))
        Rs = R + 0.0006
        tip = self.bm.verts.new(centre + Vector((0, 0, Rs)))
        ring = []
        for i in range(segs):
            t = 2 * math.pi * i / segs
            th = math.asin(max(-1.0, min(1.0, r * math.sin(t) / Rs)))
            ring.append(self.bm.verts.new(centre + axis * (r * math.cos(t)) + side * (Rs * math.sin(th))
                                          + Vector((0, 0, Rs * math.cos(th)))))
        idx = self.mi(mat)
        for i in range(segs):
            f = self.bm.faces.new((tip, ring[i], ring[(i + 1) % segs]))
            f.material_index = idx
            f.normal_update()
            if f.normal.z < 0:
                f.normal_flip()
            for loop in f.loops:
                loop[self.uv].uv = (0.5, 0.5)

    def disc(self, center, n, r, mat, segs=16):
        n = Vector(n).normalized()
        ref = Vector((0, 0, 1)) if abs(n.z) < 0.9 else Vector((1, 0, 0))
        e1 = (ref - n * ref.dot(n)).normalized()
        e2 = n.cross(e1)
        vs = [self.bm.verts.new(center + (e1 * math.cos(t) + e2 * math.sin(t)) * r)
              for t in (2 * math.pi * i / segs for i in range(segs))]
        f = self.bm.faces.new(vs)
        f.material_index = self.mi(mat)
        for loop in f.loops:
            loop[self.uv].uv = (0.5, 0.5)

    def finish(self, name, parent, coll):
        if not self.bm.faces:
            self.bm.free()
            return None
        me = bpy.data.meshes.new(name)
        self.bm.to_mesh(me)
        self.bm.free()
        for m in self.mats:
            me.materials.append(m)
        ob = bpy.data.objects.new(name, me)
        coll.objects.link(ob)
        ob.parent = parent
        return ob


# ------------------------------------------------------------------ textures
def blur_wrap(a, sigma):
    H, W = a.shape
    fy = np.fft.fftfreq(H)[:, None]
    fx = np.fft.fftfreq(W)[None, :]
    g = np.exp(-2.0 * (np.pi * sigma) ** 2 * (fx ** 2 + fy ** 2))
    return np.real(np.fft.ifft2(np.fft.fft2(a) * g)).astype(np.float32)


def noise(rng, shape, sigma):
    a = blur_wrap(rng.normal(0, 1, shape).astype(np.float32), sigma) if sigma else \
        rng.normal(0, 1, shape).astype(np.float32)
    return (a - a.mean()) / (a.std() + 1e-8)


def save_image(name, rgb, fmt, non_color=False):
    os.makedirs(TEX_DIR, exist_ok=True)
    h, w = rgb.shape[:2]
    rgba = np.concatenate([np.clip(rgb, 0, 1), np.ones((h, w, 1))], axis=2).astype(np.float32)
    path = os.path.join(TEX_DIR, name + (".jpg" if fmt == "JPEG" else ".png"))
    tmp = bpy.data.images.new("TMP_" + name, w, h, alpha=False)
    tmp.pixels.foreach_set(rgba.ravel())
    tmp.filepath_raw = path
    tmp.file_format = fmt
    try:
        tmp.save(quality=88)
    except TypeError:
        tmp.save()
    bpy.data.images.remove(tmp)
    img = bpy.data.images.load(path, check_existing=False)
    img.name = "TEX_" + name
    if non_color:
        try:
            img.colorspace_settings.name = "Non-Color"
        except TypeError:
            pass
    return img


def tex_block(rng, H=1024):
    CP, BP, M = H // 4, H // 2, 12                      # course px, block px, mortar px
    yy, xx = np.mgrid[0:H, 0:H]
    course = yy // CP
    bx = (xx + (course % 2) * (BP // 2)) % H
    bid = course * 2 + bx // BP
    tones = 0.47 + 0.08 * rng.random(int(bid.max()) + 1)
    v = tones[bid] + 0.03 * noise(rng, (H, H), 0) + 0.025 * noise(rng, (H, H), 3) + 0.018 * noise(rng, (H, H), 30)
    v[rng.random((H, H)) < 0.006] -= 0.15
    ey = np.minimum(yy % CP - M, CP - yy % CP)
    ex = np.minimum(bx % BP - M, BP - bx % BP)
    edge = np.minimum(ey, ex)
    v -= np.where((edge >= 0) & (edge < 5), 0.05 * (1 - edge / 5.0), 0)
    mortar = ((yy % CP) < M) | ((bx % BP) < M)
    v = np.where(mortar, 0.61 + 0.025 * noise(rng, (H, H), 1), v)
    return np.stack([v, v * 0.985, v * 0.955], -1)


def tex_poured(rng, H=1024):
    """Form-finished poured wall, 4 ft square: vertical form seams every 2 ft, snap-tie holes on them."""
    yy, xx = np.mgrid[0:H, 0:H].astype(np.float32)
    v = (0.6 + 0.012 * noise(rng, (H, H), 0) + 0.014 * noise(rng, (H, H), 2)
         + 0.018 * noise(rng, (H, H), 14) + 0.022 * noise(rng, (H, H), 70))
    half = H // 2
    sx = np.minimum(xx % half, half - xx % half)            # distance to the nearest form seam
    v -= np.where(sx < 1.5, 0.07, np.where(sx < 4, 0.02, 0.0))
    r = H / 48 * 0.55                                       # ~1" snap-tie cone
    for cx in (0, half, H):
        for cy in (H / 4, 3 * H / 4):
            d = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2)
            v -= np.where(d < r, 0.32, np.where(d < r * 1.6, 0.06 * (1 - (d - r) / (0.6 * r)), 0.0))
    v[rng.random((H, H)) < 0.0012] -= 0.18                  # bug holes
    return np.stack([v, v * 0.99, v * 0.965], -1)


def tex_concrete(rng, base, H=1024):
    v = (base + 0.012 * noise(rng, (H, H), 0) + 0.012 * noise(rng, (H, H), 2)
         + 0.008 * noise(rng, (H, H), 12) + 0.01 * noise(rng, (H, H), 60))
    v[rng.random((H, H)) < 0.002] -= 0.08
    return np.stack([v, v * 0.99, v * 0.97], -1)


def pebble_cells(pts, H):
    """Tileable Voronoi cells: distance to the nearest and second-nearest pebble centre, and its index."""
    yy, xx = np.mgrid[0:H, 0:H].astype(np.float32)
    F1 = np.full((H, H), 1e9, np.float32)
    F2 = np.full((H, H), 1e9, np.float32)
    idx = np.zeros((H, H), np.int32)
    for k in range(len(pts)):
        dx = np.abs(xx - pts[k, 0]); dx = np.minimum(dx, H - dx)
        dy = np.abs(yy - pts[k, 1]); dy = np.minimum(dy, H - dy)
        d = np.sqrt(dx * dx + dy * dy)
        closer = d < F1
        F2 = np.where(closer, F1, np.minimum(F2, d))
        idx = np.where(closer, k, idx)
        F1 = np.where(closer, d, F1)
    return F1, F2, idx


def tex_gravel(rng, H=512, n=320):
    pts = rng.random((n, 2)) * H
    base = 0.24 + 0.34 * rng.random(n)
    cols = np.stack([base * (0.95 + 0.12 * rng.random(n)),
                     base * (0.93 + 0.08 * rng.random(n)),
                     base * (0.86 + 0.12 * rng.random(n))], -1)
    F1, F2, idx = pebble_cells(pts, H)
    gap = F2 - F1
    rel = F1 / (F1 + gap * 0.5 + 1e-3)                 # 0 at pebble centre, 1 at its edge
    shade = (1.0 - 0.55 * rel ** 2) * (0.2 + 0.8 * np.clip(gap / 3.5, 0, 1))
    rgb = cols[idx] * shade[..., None]
    rgb += 0.025 * noise(rng, (H, H), 0)[..., None]
    return rgb


def tex_pea_gravel(rng, H=512, n=440):
    """1B pea gravel: smaller, rounder and warmer than the washed stone, in mixed tans, browns and greys."""
    pts = rng.random((n, 2)) * H
    palette = np.array([(0.64, 0.56, 0.45), (0.56, 0.54, 0.50), (0.48, 0.40, 0.31),
                        (0.72, 0.68, 0.60), (0.42, 0.39, 0.35)], np.float32)
    cols = palette[rng.integers(0, len(palette), n)] * (0.85 + 0.25 * rng.random((n, 1)))
    F1, F2, idx = pebble_cells(pts, H)
    gap = F2 - F1
    rel = np.clip(F1 / (F1 + gap * 0.5 + 1e-3), 0, 1)  # 0 at pebble centre, 1 at its edge
    dome = np.sqrt(1.0 - rel ** 2)                       # rounded pebbles: bright middle, soft falloff
    shade = (0.3 + 0.7 * dome) * (0.15 + 0.85 * np.clip(gap / 3.0, 0, 1))
    rgb = cols[idx] * shade[..., None]
    rgb += 0.02 * noise(rng, (H, H), 0)[..., None]
    return rgb


def tex_vapor_barrier(rng, H=1024, per_m=40, k=9.0):
    """11-14 mil white vapor barrier: anti-rip fibres woven in (a fine diamond scrim, 1" apart at 1 m per
    tile) and soft folds where it hangs. Returns colour (H) and a fold normal map (H/2)."""
    h2 = H // 2
    folds = noise(rng, (h2 // 8, h2), 10)                  # long, vertical-ish folds: few rows, many columns
    folds = blur_wrap(np.repeat(folds, 8, axis=0), 2.0)
    folds = (folds - folds.mean()) / (folds.std() + 1e-8)
    gx = (np.roll(folds, -1, 1) - np.roll(folds, 1, 1)) * 0.5
    gy = (np.roll(folds, -1, 0) - np.roll(folds, 1, 0)) * 0.5
    nx, ny, nz = -gx * k / 8.0, -gy * k / 8.0, np.ones_like(folds)
    L = np.sqrt(nx * nx + ny * ny + nz * nz)
    nrm = np.stack([nx / L * 0.5 + 0.5, ny / L * 0.5 + 0.5, nz / L * 0.5 + 0.5], -1)
    yy, xx = np.mgrid[0:H, 0:H].astype(np.float32)
    sp = H / per_m
    d1, d2 = (xx + yy) % sp, (xx - yy) % sp
    fibre = (np.minimum(d1, sp - d1) < 1.1) | (np.minimum(d2, sp - d2) < 1.1)
    shade = np.kron(folds, np.ones((2, 2), np.float32))
    v = 0.885 + 0.02 * shade + 0.008 * noise(rng, (H, H), 0)
    v = np.where(fibre, v * 0.93, v)
    return np.stack([v * 0.99, v, v * 1.015], -1), nrm


def tex_dimple(H=512, n=5, k=18.0):
    sp = H / n
    r = 0.36 * sp
    yy, xx = np.mgrid[0:H, 0:H].astype(np.float32) + 0.5
    lx, ly = (xx % sp) - sp / 2, (yy % sp) - sp / 2
    d2 = (lx * lx + ly * ly) / (r * r)
    h = np.clip(1 - d2, 0, 1) ** 1.5
    gx = (np.roll(h, -1, 1) - np.roll(h, 1, 1)) * 0.5
    gy = (np.roll(h, -1, 0) - np.roll(h, 1, 0)) * 0.5
    nx, ny, nz = -gx * k, -gy * k, np.ones_like(h)
    L = np.sqrt(nx * nx + ny * ny + nz * nz)
    nrm = np.stack([nx / L * 0.5 + 0.5, ny / L * 0.5 + 0.5, nz / L * 0.5 + 0.5], -1)
    ring = np.exp(-((np.sqrt(d2) - 1.0) ** 2) / 0.02)
    v = 0.045 + 0.03 * h - 0.02 * ring
    return np.stack([v, v, v * 1.05], -1), nrm


def tex_pipe(rng, H=512, ribs=12):
    v = (np.arange(H) + 0.5) / H
    u = (np.arange(H) + 0.5) / H
    vv, uu = np.meshgrid(v, u, indexing="ij")          # rows = along the pipe, cols = around
    h = 0.5 + 0.5 * np.cos(2 * np.pi * ribs * vv)
    ny = 0.3 * np.sin(2 * np.pi * ribs * vv)
    nz = np.ones_like(ny)
    L = np.sqrt(ny * ny + nz * nz)
    nrm = np.stack([np.full_like(ny, 0.5), ny / L * 0.5 + 0.5, nz / L * 0.5 + 0.5], -1)
    c = 0.88 + 0.05 * h + 0.008 * noise(rng, (H, H), 0)
    slot = (np.abs(vv - 0.5) < 0.012) & (np.abs(uu - 0.5) < 0.28)   # slots across the bottom, ends show on the sides
    c = np.where(slot, 0.05, c)
    nrm[slot] = (0.5, 0.5, 1.0)
    return np.stack([c, c, c * 0.99], -1), nrm


def tex_grate(W=256, H=512):
    """Channel-drain grate from above. u = along the channel (one tile = 1"), v = across the whole grate.
    Short slots across the grate in three staggered lanes, dark grey plastic bars between them."""
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32) + 0.5
    lane_h = H / 3
    lane = np.floor(yy / lane_h)
    ly = yy - lane * lane_h                                # across, inside the lane
    period = W / 2                                         # two slots per inch
    lx = (xx + (lane % 2) * period / 2) % period           # along, inside the period (lanes staggered)
    bar_u, bar_v = 0.42 * period, 0.16 * lane_h
    slot = (np.abs(lx - period / 2) < (period - bar_u) / 2) & (np.abs(ly - lane_h / 2) < lane_h / 2 - bar_v)
    edge = (np.abs(lx - period / 2) < (period - bar_u) / 2 + 3) & (np.abs(ly - lane_h / 2) < lane_h / 2 - bar_v + 3)
    v = np.full((H, W), 0.30, np.float32)
    v = np.where(edge, 0.22, v)
    v = np.where(slot, 0.035, v)
    return np.stack([v, v * 1.02, v * 1.06], -1)


def make_textures():
    rng = np.random.default_rng(7)
    T = {}
    T["block"] = save_image("block_basecolor", tex_block(rng), "JPEG")
    T["poured"] = save_image("poured_basecolor", tex_poured(rng), "JPEG")
    T["slab"] = save_image("slab_basecolor", tex_concrete(rng, 0.66), "JPEG")
    T["patch"] = save_image("patch_basecolor", tex_concrete(rng, 0.52), "JPEG")
    T["gravel"] = save_image("gravel_basecolor", tex_gravel(rng), "JPEG")
    dc, dn = tex_dimple()
    T["dimple"] = save_image("dimple_basecolor", dc, "JPEG")
    T["dimple_n"] = save_image("dimple_normal", dn, "PNG", non_color=True)
    pc, pn = tex_pipe(rng)
    T["pipe"] = save_image("drainpipe_basecolor", pc, "JPEG")
    T["pipe_n"] = save_image("drainpipe_normal", pn, "PNG", non_color=True)
    T["pea"] = save_image("peagravel_basecolor", tex_pea_gravel(rng), "JPEG")   # new ones go last, so the others
    bc, bn = tex_vapor_barrier(rng)                                              # stay as they were
    T["barrier"] = save_image("vaporbarrier_basecolor", bc, "JPEG")
    T["barrier_n"] = save_image("vaporbarrier_normal", bn, "PNG", non_color=True)
    T["grate"] = save_image("grate_basecolor", tex_grate(), "JPEG")
    return T


# ------------------------------------------------------------------ materials
def make_mat(name, color=(0.8, 0.8, 0.8), rough=0.8, metal=0.0, tex=None, normal=None, alpha=None):
    m = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    if m.node_tree is None:
        m.use_nodes = True
    nt = m.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    out.location = (400, 0)
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    nt.links.new(bsdf.outputs[0], out.inputs["Surface"])
    bsdf.inputs["Base Color"].default_value = (*lin(color), 1.0)
    bsdf.inputs["Roughness"].default_value = rough
    bsdf.inputs["Metallic"].default_value = metal
    if tex is not None:
        t = nt.nodes.new("ShaderNodeTexImage")
        t.image, t.location = tex, (-400, 200)
        nt.links.new(t.outputs["Color"], bsdf.inputs["Base Color"])
    if normal is not None:
        t = nt.nodes.new("ShaderNodeTexImage")
        t.image, t.location = normal, (-600, -200)
        nm = nt.nodes.new("ShaderNodeNormalMap")
        nm.location = (-250, -200)
        nt.links.new(t.outputs["Color"], nm.inputs["Color"])
        nt.links.new(nm.outputs["Normal"], bsdf.inputs["Normal"])
    if alpha is not None:
        bsdf.inputs["Alpha"].default_value = alpha
        try:
            m.surface_render_method = "BLENDED"
        except (AttributeError, TypeError):
            pass
    m.diffuse_color = (*lin(color), 1.0 if alpha is None else alpha)
    return m


def make_materials(T):
    return {
        "block": make_mat("MAT_Block", (0.55, 0.55, 0.53), 0.92, tex=T["block"]),
        "poured": make_mat("MAT_PouredConcrete", (0.6, 0.6, 0.58), 0.85, tex=T["poured"]),
        "crack": make_mat("MAT_Crack", (0.04, 0.04, 0.04), 1.0),
        "polyurethane": make_mat("MAT_Polyurethane", (0.86, 0.62, 0.22), 0.55),
        "hit": make_mat("MAT_HitArea", (1.0, 0.0, 1.0), 1.0, alpha=0.0),
        "concrete": make_mat("MAT_Concrete", (0.66, 0.66, 0.64), 0.88, tex=T["slab"]),
        "patch": make_mat("MAT_ConcretePatch", (0.52, 0.52, 0.5), 0.82, tex=T["patch"]),
        "stone": make_mat("MAT_Stone", (0.5, 0.48, 0.45), 0.9, tex=T["gravel"]),
        "pea": make_mat("MAT_PeaGravel", (0.6, 0.55, 0.48), 0.85, tex=T["pea"]),
        "barrier": make_mat("MAT_VaporBarrier", (0.9, 0.9, 0.91), 0.45, tex=T["barrier"], normal=T["barrier_n"]),
        "subbase": make_mat("MAT_SubBase", (0.36, 0.31, 0.26), 1.0),
        "pvc": make_mat("MAT_PVC", (0.93, 0.93, 0.92), 0.35),
        "pipe": make_mat("MAT_DrainPipe", (0.92, 0.92, 0.91), 0.45, tex=T["pipe"], normal=T["pipe_n"]),
        "dimple": make_mat("MAT_DimpleBoard", (0.05, 0.05, 0.05), 0.5, tex=T["dimple"], normal=T["dimple_n"]),
        "panel": make_mat("MAT_WallPanel", (0.95, 0.95, 0.94), 0.55),
        "hole": make_mat("MAT_Hole", (0.02, 0.02, 0.02), 1.0),
        "bore": make_mat("MAT_HoleBore", (0.2, 0.2, 0.19), 1.0),
        "sill": make_mat("MAT_SillPlate", (0.55, 0.58, 0.44), 0.85),
        "wood": make_mat("MAT_Wood", (0.72, 0.56, 0.38), 0.8),
        "frame": make_mat("MAT_WindowFrame", (0.9, 0.9, 0.88), 0.5),
        "glass": make_mat("MAT_Glass", (0.62, 0.74, 0.8), 0.05, alpha=0.3),
        "basin": make_mat("MAT_SumpBasin", (0.08, 0.08, 0.08), 0.55),
        "lid": make_mat("MAT_SumpLid", (0.17, 0.17, 0.17), 0.6),
        "rubber": make_mat("MAT_Rubber", (0.03, 0.03, 0.03), 0.9),
        "pump": make_mat("MAT_PumpCastIron", (0.16, 0.17, 0.18), 0.45, metal=0.4),
        "backup": make_mat("MAT_BackupPump", (0.16, 0.27, 0.45), 0.5),
        "float": make_mat("MAT_Float", (0.9, 0.88, 0.8), 0.5),
        "paver": make_mat("MAT_Paver", (0.5, 0.48, 0.45), 0.9),
        "metal": make_mat("MAT_Metal", (0.72, 0.72, 0.72), 0.35, metal=0.9),
        "battery": make_mat("MAT_Battery", (0.06, 0.06, 0.06), 0.55),
        "charger": make_mat("MAT_Charger", (0.78, 0.78, 0.75), 0.5),
        "cable": make_mat("MAT_Cable", (0.03, 0.03, 0.03), 0.6),
        "galv": make_mat("MAT_Galvanized", (0.74, 0.76, 0.78), 0.38, metal=0.85),
        "dehu": make_mat("MAT_DehuBody", (0.9, 0.9, 0.9), 0.45),
        "grille": make_mat("MAT_Grille", (0.14, 0.14, 0.15), 0.6),
        "hose": make_mat("MAT_Hose", (0.2, 0.2, 0.22), 0.5),
        "channel": make_mat("MAT_ChannelDrain", (0.24, 0.25, 0.27), 0.6),
        "grate": make_mat("MAT_Grate", (0.3, 0.31, 0.33), 0.55, tex=T["grate"]),
        "heater": make_mat("MAT_WaterHeater", (0.84, 0.85, 0.86), 0.35, metal=0.15),
        "copper": make_mat("MAT_Copper", (0.78, 0.47, 0.3), 0.35, metal=0.9),
        "brass": make_mat("MAT_Brass", (0.8, 0.66, 0.36), 0.35, metal=0.85),
        "handle": make_mat("MAT_ValveHandle", (0.15, 0.3, 0.7), 0.5),
    }


# ------------------------------------------------------------------ scene helpers
def reset_collection():
    root = bpy.data.collections.get(ROOT_COLL)
    if root:
        for ob in model_objects(root):
            bpy.data.objects.remove(ob, do_unlink=True)
        for c in list(root.children_recursive):
            bpy.data.collections.remove(c)
        bpy.data.collections.remove(root)
    for me in list(bpy.data.meshes):
        if me.users == 0:
            bpy.data.meshes.remove(me)
    for img in list(bpy.data.images):
        if img.name.startswith("TEX_") or img.name.startswith("TMP_"):
            bpy.data.images.remove(img)
    root = bpy.data.collections.new(ROOT_COLL)
    bpy.context.scene.collection.children.link(root)
    return root


def model_objects(root):
    """Objects in the model collections (walked directly; all_objects can be stale right after deletes)."""
    return [o for c in [root, *root.children_recursive] for o in c.objects if o is not None]


def section(root, name):
    coll = bpy.data.collections.new("C_" + name[4:])
    root.children.link(coll)
    ob = bpy.data.objects.new(name, None)
    ob.empty_display_type, ob.empty_display_size = "PLAIN_AXES", 0.3
    coll.objects.link(ob)
    return ob, coll


# ------------------------------------------------------------------ builders
def build_wall(side, M, root):
    sec, coll = section(root, SIDES[side]["sec"])
    s_lo, s_hi = span(side)
    corners = owns_corners(side)
    poured = side in POURED_SIDES
    wmat = M["poured"] if poured else M["block"]
    blk = dict(tile=POURED_TILE if poured else BLOCK_TILE, voff=FOOT_TOP)

    # foundation wall: concrete block, or poured concrete (with a window opening on N and S)
    mb = MB()
    a0, a1 = (s_lo - WALL_T, s_hi + WALL_T) if corners else (s_lo, s_hi)
    if side in WINDOWS:
        w0, w1 = WINDOWS[side]
        mb.wbox(side, a0, w0, -WALL_T, 0, FOOT_TOP, WALL_TOP, wmat, **blk)
        mb.wbox(side, w1, a1, -WALL_T, 0, FOOT_TOP, WALL_TOP, wmat, **blk)
        mb.wbox(side, w0, w1, -WALL_T, 0, FOOT_TOP, WALL_TOP - WIN_H, wmat, **blk)
    else:
        mb.wbox(side, a0, a1, -WALL_T, 0, FOOT_TOP, WALL_TOP, wmat, **blk)
    mb.finish(f"SHELL_Wall_{side}", sec, coll)

    # footing
    mb = MB()
    f0, f1 = ((s_lo - WALL_T - FOOT_PROJ, s_hi + WALL_T + FOOT_PROJ) if corners
              else (s_lo + FOOT_PROJ, s_hi - FOOT_PROJ))
    mb.wbox(side, f0, f1, -WALL_T - FOOT_PROJ, FOOT_PROJ, FOOT_TOP - FOOT_T, FOOT_TOP, M["concrete"], tile=2.0)
    mb.finish(f"SHELL_Footing_{side}", sec, coll)

    # sill plate, rim joist, joist stubs
    mb = MB()
    s0, s1 = (s_lo - WALL_T, s_hi + WALL_T) if corners else (s_lo - WALL_T + SILL_W, s_hi + WALL_T - SILL_W)
    mb.wbox(side, s0, s1, -WALL_T, -WALL_T + SILL_W, WALL_TOP, WALL_TOP + SILL_T, M["sill"])
    r0, r1 = (s_lo - WALL_T, s_hi + WALL_T) if corners else (s_lo - WALL_T + RIM_T, s_hi + WALL_T - RIM_T)
    zr = WALL_TOP + SILL_T
    mb.wbox(side, r0, r1, -WALL_T, -WALL_T + RIM_T, zr, zr + RIM_H, M["wood"])
    if corners:                                   # joists bear on the N and S walls
        k = 1
        while s_lo + k * BLOCK_L < s_hi - 0.05:
            s = s_lo + k * BLOCK_L
            mb.wbox(side, s - 0.75 * IN, s + 0.75 * IN, -WALL_T + RIM_T, 0.45, zr, zr + RIM_H, M["wood"])
            k += 1
    mb.finish(f"SHELL_Framing_{side}", sec, coll)

    # window
    if side in WINDOWS:
        w0, w1 = WINDOWS[side]
        mb = MB()
        z0, z1, fw = WALL_TOP - WIN_H, WALL_TOP, 2 * IN
        d0, d1 = -WALL_T / 2 - 0.035, -WALL_T / 2 + 0.035
        mb.wbox(side, w0, w1, d0, d1, z0, z0 + fw, M["frame"])
        mb.wbox(side, w0, w1, d0, d1, z1 - fw, z1, M["frame"])
        mb.wbox(side, w0, w0 + fw, d0, d1, z0 + fw, z1 - fw, M["frame"])
        mb.wbox(side, w1 - fw, w1, d0, d1, z0 + fw, z1 - fw, M["frame"])
        mb.wbox(side, w0 + fw, w1 - fw, -WALL_T / 2 - 0.003, -WALL_T / 2 + 0.003, z0 + fw, z1 - fw, M["glass"])
        mb.finish(f"SHELL_Window_{side}", sec, coll)

    off = sys_off(side)                                   # this wall's 2 ft system sits this far off the face
    lo_off, hi_off = sys_off(end_wall(side, "lo")), sys_off(end_wall(side, "hi"))
    top = FOOT_TOP + SYS_H
    gap = wall_gap(side)                                  # the water heater's U trench (east wall): the trench,
                                                          # pipe and wall system stop on either side of it

    if side == FULL_HEIGHT_SIDE:
        # full-wall upgrade: dimple board behind the barrier (not on every job), full height
        mb = MB()
        mb.wbox(side, s_lo, s_hi, 0, DIMPLE_T, FOOT_TOP, WALL_TOP - 0.01, M["dimple"], tile=0.15, voff=FOOT_TOP)
        mb.finish(f"PART_BarrierDimple_{side}", sec, coll)
        # the vapor barrier sheet, down to the footing behind the 2 ft system; its corner strips and the
        # wraps onto the next walls are SHELL_BarrierWrap_* in those walls
        mb = MB()
        mb.wbox(side, s_lo + WRAP_GAP, s_hi - WRAP_GAP, DIMPLE_T, UPG_T, FOOT_TOP, WALL_TOP - 0.005, M["barrier"], tile=1.0)
        mb.finish(f"PART_VaporBarrier_{side}", sec, coll)

    for end in ("lo", "hi"):
        nb = end_wall(side, end)
        if nb != FULL_HEIGHT_SIDE or not corners:
            continue
        # the upgrade wall's barrier wraps around this corner onto this wall. It stays put; where this wall's
        # dimple board covers it, it sits inside the board, so it shows once this wall's system lifts away.
        mb = MB()
        s0, s1 = (s_lo + DIMPLE_T, s_lo + WRAP) if end == "lo" else (s_hi - WRAP, s_hi - DIMPLE_T)
        mb.wbox(side, s0, s1, 0.001, 0.001 + BARRIER_T, FOOT_TOP, WALL_TOP - 0.005, M["barrier"], tile=1.0)
        n_lo, n_hi = span(nb)
        c0, c1 = ((n_hi - WRAP_GAP, n_hi - 0.001) if abs(SIDES[side]["face"] - n_hi) < 1e-6
                  else (n_lo + 0.001, n_lo + WRAP_GAP))
        mb.wbox(nb, c0, c1, DIMPLE_T, UPG_T, FOOT_TOP, WALL_TOP - 0.005, M["barrier"], tile=1.0)
        mb.finish(f"SHELL_BarrierWrap_{side}", sec, coll)

    # standard 2 ft system. Dimple board: vertical leg on the wall + 6" leg across the footing
    mb = MB()
    v0, v1 = ((s_lo + lo_off, s_hi - hi_off) if corners
              else (s_lo + DIMPLE_T + lo_off, s_hi - DIMPLE_T - hi_off))
    for a, b in around(v0, v1, gap, SYS_PAD):
        mb.wbox(side, a, b, off, off + DIMPLE_T, FOOT_TOP, top, M["dimple"], tile=0.15, voff=FOOT_TOP)
    f0, f1 = ((s_lo + lo_off + DIMPLE_T, s_hi - hi_off - DIMPLE_T) if corners
              else (s_lo + DIMPLE_FOOT, s_hi - DIMPLE_FOOT))
    for a, b in around(f0, f1, gap, SYS_PAD):
        mb.wbox(side, a, b, off + DIMPLE_T, DIMPLE_FOOT, FOOT_TOP, FOOT_TOP + DIMPLE_T, M["dimple"], tile=0.15)
    mb.finish(f"PART_DimpleBoard_{side}", sec, coll)

    # white 2 ft wall panel (membrane / vapor barrier) with its top trim
    mb = MB()
    p0, p1 = ((s_lo + lo_off + SYS_FRONT, s_hi - hi_off - SYS_FRONT) if corners
              else (s_lo + DIMPLE_T + lo_off, s_hi - DIMPLE_T - hi_off))
    for a, b in around(p0, p1, gap, SYS_PAD):
        mb.wbox(side, a, b, off + DIMPLE_T, off + SYS_FRONT, FOOT_TOP + DIMPLE_T, top, M["panel"])
    c0, c1 = (p0, p1) if corners else (s_lo + SYS_FRONT + 0.003 + lo_off, s_hi - SYS_FRONT - 0.003 - hi_off)
    for a, b in around(c0, c1, gap, SYS_PAD):
        mb.wbox(side, a, b, off, off + SYS_FRONT + 0.003, top, top + 0.008, M["panel"])
    mb.finish(f"PART_WallMembrane_{side}", sec, coll)

    # weep holes (block walls only): one per block core in the bottom course, drilled through the
    # block's face shell (the wall itself gets matching holes in cut_holes)
    if not poured:
        mb = MB()
        lo, hi = s_lo + 0.08, s_hi - 0.08
        WEEP_CUTS[side] = []
        for k in range(math.floor(lo / BLOCK_L) - 1, math.ceil(hi / BLOCK_L) + 1):
            for c in (0.25, 0.75):
                s = (k + c) * BLOCK_L
                if lo <= s <= hi and not (gap and gap[0] - 0.03 < s < gap[1] + 0.03):
                    center = P(side, s, 0.0, WEEP_Z)
                    mb.bore(center, inward(side), WEEP_R - 0.0006, WEEP_DEPTH, M["bore"], M["hole"])
                    WEEP_CUTS[side].append(center)
        mb.finish(f"PART_WeepHoles_{side}", sec, coll)

    # concrete patch over the trench. At the sump end it stops at the sump square: the strips beside the
    # square are SHELL_SumpCorner_NW (never moves), so the patch's explode doesn't drag them through the
    # lid, the check valve and the battery.
    sump_end = SUMP_ENDS.get(side)
    mb = MB()
    a, b = (s_lo + SYS_FRONT + lo_off, s_hi - SYS_FRONT - hi_off) if corners else (s_lo + TRENCH_W, s_hi - TRENCH_W)
    if sump_end == "lo":
        a = s_lo + SUMP_SQ[1]
    if sump_end == "hi":
        b = s_hi - SUMP_SQ[1]
    for a, b in around(a, b, gap):
        mb.wbox(side, a, b, SYS_FRONT + off, TRENCH_W, FOOT_TOP + DIMPLE_T, 0.0, M["patch"], tile=2.0)
    mb.finish(f"FILL_Patch_{side}", sec, coll)

    # 2B stone around the pipe, above the gravel bed (pipe hole is cut later); labeled
    mb = MB()
    a, b = (s_lo + FOOT_PROJ, s_hi - FOOT_PROJ) if corners else (s_lo + TRENCH_W, s_hi - TRENCH_W)
    runs = around(a, b, gap)
    for a, b in runs:
        mb.wbox(side, a, b, FOOT_PROJ, TRENCH_W, -TRENCH_D + BED_T, FOOT_TOP + DIMPLE_T, M["stone"], tile=0.3)
    mb.finish(f"PART_DrainStone_{side}", sec, coll)

    # 1" bed of 1B pea gravel across the trench bottom; the pipe rests on it; labeled
    mb = MB()
    for a, b in runs:
        mb.wbox(side, a, b, FOOT_PROJ, TRENCH_W, -TRENCH_D, -TRENCH_D + BED_T, M["pea"], tile=0.2)
    mb.finish(f"PART_GravelBed_{side}", sec, coll)

    # perimeter drain: slotted pipe, corner 90s (N/S own the corners), cleanout tee + capped riser
    mb = MB()
    lo, hi = s_lo + PIPE_OFF + BEND_R, s_hi - PIPE_OFF - BEND_R
    L45 = BEND45_R * math.tan(math.radians(22.5))
    if sump_end == "lo":
        lo = s_lo + SUMP_A + TAIL_TURN + L45
    if sump_end == "hi":
        hi = s_hi - SUMP_A - TAIL_TURN - L45
    # on the water heater's wall the pipe stops where it jogs out around the heater (that jog, its elbows
    # included, belongs to SEC_DrainGrate)
    for a, b in ([(lo, hi)] if gap is None else [(lo, U_S - BEND_R), (U_N + BEND_R, hi)]):
        mb.cyl(P(side, a, PIPE_OFF, PIPE_Z), P(side, b, PIPE_OFF, PIPE_Z), PIPE_R, M["pipe"],
               vtile=5 * IN, v0=a)
    av, n = along_vec(side), inward(side)
    if sump_end:                                  # 45 into the side of the sump basin
        # The 45 and the stub into the basin are their own piece that never moves: when the wall opens
        # the pipe lifts out of the fitting, instead of the stub rising up through the sump lid.
        tb = MB()
        s_t = s_lo + SUMP_A + TAIL_TURN if sump_end == "lo" else s_hi - SUMP_A - TAIL_TURN
        T = P(side, s_t, PIPE_OFF, PIPE_Z)
        d_in = -av if sump_end == "lo" else av
        target = Vector((SUMP_C.x, SUMP_C.y, PIPE_Z))
        d_out = (target - T).normalized()
        start, end_pt = tb.bend(T, d_in, d_out, BEND45_R, FIT_R, M["pvc"])
        tb.cyl(start, start - d_in * 0.04, FIT_R + 0.004, M["pvc"])
        tb.cyl(end_pt, end_pt + d_out * 0.04, FIT_R + 0.004, M["pvc"])
        tb.cyl(end_pt, target - d_out * (basin_radius_at(PIPE_Z) - 1 * IN), PIPE_R, M["pvc"])
        tb.finish(f"SHELL_DrainTail_{side}", sec, coll)
    if corners:
        for end, sgn in (("lo", +1), ("hi", -1)):
            if end == sump_end:
                continue
            s_k = s_lo + PIPE_OFF if end == "lo" else s_hi - PIPE_OFF
            K = P(side, s_k, PIPE_OFF, PIPE_Z)
            C = K + n * BEND_R + av * (sgn * BEND_R)
            e1, e2 = -n, av * (-sgn)
            mb.elbow(C, e1, e2, BEND_R, FIT_R, M["pvc"])
            start, finish_pt = C + e1 * BEND_R, C + e2 * BEND_R
            mb.cyl(start, start - e2 * 0.04, FIT_R + 0.004, M["pvc"])
            mb.cyl(finish_pt, finish_pt - e1 * 0.04, FIT_R + 0.004, M["pvc"])
    c = P(side, CLEANOUT_AT[side], PIPE_OFF, PIPE_Z)
    up = Vector((0, 0, 1))
    mb.cyl(c - av * 0.12, c + av * 0.12, FIT_R, M["pvc"])
    mb.cyl(c, c + up * (FIT_R + 0.035), FIT_R, M["pvc"])
    mb.cyl(c + up * FIT_R, Vector((c.x, c.y, -0.010)), PIPE_R, M["pvc"])
    mb.cyl(Vector((c.x, c.y, -0.014)), Vector((c.x, c.y, 0.004)), PIPE_R + 0.009, M["pvc"])
    mb.finish(f"PART_PerimeterDrain_{side}", sec, coll)


def build_floor(M, root):
    sec, coll = section(root, "SEC_FloorSlab")
    # the slab inside the trenches, notched for the water heater's U trench, plus the island of old slab the
    # heater stands on (the U goes around it)
    mb = MB()
    mb.prism(slab_outline(), FOOT_TOP, 0.0, M["concrete"], tile=2.0)
    mb.wbox(WH_SIDE, ISLE[0], ISLE[1], 0, ISLE[2], FOOT_TOP, 0.0, M["concrete"], tile=2.0)
    mb.finish("SHELL_Slab", sec, coll)
    mb = MB()
    mb.box(XW + FOOT_PROJ, XE - FOOT_PROJ, YS + FOOT_PROJ, YN - FOOT_PROJ, SUBBASE_BOTTOM, -TRENCH_D, M["subbase"])
    mb.prism(slab_outline(), -TRENCH_D, FOOT_TOP, M["subbase"])
    mb.wbox(WH_SIDE, ISLE[0], ISLE[1], FOOT_PROJ, ISLE[2], -TRENCH_D, FOOT_TOP, M["subbase"])
    mb.finish("SHELL_SubBase", sec, coll)


def basin_radius_at(z):
    """Outside radius of the tapered basin wall at height z."""
    return BASIN_RB + (BASIN_RT - BASIN_RB) * (z + BASIN_D) / (BASIN_D - 0.012)


def build_sump(M, root):
    """Sump basin + lid, main pump and smaller battery-backup pump joined by a Y into one 1.5" line,
    check valve 1" above the lid, discharge up the north wall and out through the rim joist."""
    sec, coll = section(root, "SEC_SumpArea")
    C, zb = SUMP_C, -BASIN_D
    up = Vector((0, 0, 1))
    perp = Vector((-PUMP_DIR.y, PUMP_DIR.x, 0))
    at = lambda xy, z: Vector((xy.x, xy.y, z))

    # 30-gallon basin with a rim flange, flush with the floor
    mb = MB()
    mb.lathe(C, [(0, zb), (BASIN_RB, zb), (BASIN_RT, -0.012), (BASIN_FLANGE, -0.012), (BASIN_FLANGE, 0.0),
                 (BASIN_RT - BASIN_WALL, 0.0), (BASIN_RB - BASIN_WALL, zb + BASIN_WALL), (0, zb + BASIN_WALL)],
             M["basin"], segs=40)
    mb.finish("PART_SumpPit_NW", sec, coll)

    # lid, with a rubber grommet where the discharge comes through
    mb = MB()
    mb.lathe(C, [(0, 0.0), (BASIN_FLANGE, 0.0), (BASIN_FLANGE, LID_T), (0, LID_T)], M["lid"], segs=40)
    mb.lathe(MAIN_XY, [(0, LID_T), (0.045, LID_T), (0.045, LID_T + 0.003), (0, LID_T + 0.003)], M["rubber"])
    mb.finish("PART_SumpLid_NW", sec, coll)

    # main pump: cast iron, vertical float switch, carry handle, discharge up to the Y
    z0 = zb + BASIN_WALL
    ztop = z0 + 0.275
    mb = MB()
    mb.lathe(MAIN_XY, [(0, z0), (0.1016, z0), (0.1016, z0 + 0.07), (0.088, z0 + 0.078), (0.088, z0 + 0.245),
                       (0.07, z0 + 0.265), (0.03, ztop), (0, ztop)], M["pump"], segs=32)
    h1, h2 = MAIN_XY + perp * 0.06 + PUMP_DIR * 0.04, MAIN_XY + perp * 0.06 - PUMP_DIR * 0.04
    mb.pipe_path([at(h1, ztop - 0.02), at(h1, ztop + 0.035), at(h2, ztop + 0.035), at(h2, ztop - 0.02)],
                 0.007, 0.012, M["metal"], segs=12)
    fp = MAIN_XY + perp * 0.115
    mb.cyl(at(fp, z0 + 0.02), at(fp, z0 + 0.30), 0.005, M["metal"], segs=10)
    mb.cyl(at(MAIN_XY + perp * 0.085, z0 + 0.05), at(fp, z0 + 0.05), 0.006, M["metal"], segs=10)
    mb.cyl(at(fp, z0 + 0.15), at(fp, z0 + 0.21), 0.022, M["float"], segs=20)
    mb.cyl(at(MAIN_XY, ztop - 0.01), at(MAIN_XY, Y_Z - 0.05), PVC15_R, M["pvc"], segs=20)
    mb.finish("PART_SumpPump_NW", sec, coll)

    # smaller battery-backup pump on a paver (kicks on higher), discharge 45s over into the Y
    zp = z0 + 0.05
    btop = zp + 0.21
    mb = MB()
    mb.lathe(BACK_XY, [(0, z0), (0.08, z0), (0.08, zp), (0, zp)], M["paver"], segs=24)
    mb.lathe(BACK_XY, [(0, zp), (0.072, zp), (0.072, zp + 0.05), (0.065, zp + 0.056), (0.065, zp + 0.19),
                       (0.05, zp + 0.205), (0.02, btop), (0, btop)], M["backup"], segs=28)
    fb = BACK_XY + perp * 0.09
    mb.cyl(at(fb, zp + 0.03), at(fb, zp + 0.36), 0.005, M["metal"], segs=10)
    mb.cyl(at(BACK_XY + perp * 0.06, zp + 0.06), at(fb, zp + 0.06), 0.006, M["metal"], segs=10)
    mb.cyl(at(fb, zp + 0.25), at(fb, zp + 0.30), 0.02, M["float"], segs=20)
    J = at(MAIN_XY, Y_Z)
    K = at(BACK_XY, Y_Z - (MAIN_XY - BACK_XY).length)
    br = (J - K).normalized()
    mb.pipe_path([at(BACK_XY, btop - 0.01), K, J - br * 0.05], PVC15_R, 0.04, M["pvc"], fit_r=PVC15_FIT)
    mb.finish("PART_BatteryBackup_NW", sec, coll)

    # Y fitting, and the single 1.5" line up through the lid to the check valve
    mb = MB()
    mb.cyl(J - up * 0.06, J + up * 0.05, PVC15_FIT, M["pvc"], segs=20)
    mb.cyl(J, J - br * 0.075, PVC15_FIT, M["pvc"], segs=20)
    mb.cyl(J, at(MAIN_XY, CHECK_Z + 0.03), PVC15_R, M["pvc"], segs=20)
    mb.finish("PART_YFitting_NW", sec, coll)

    # check valve, 1" above the lid
    z = CHECK_Z
    mb = MB()
    mb.lathe(MAIN_XY, [(0, z), (0.029, z), (0.029, z + 0.045), (0.034, z + 0.05), (0.046, z + 0.07),
                       (0.048, z + 0.115), (0.046, z + 0.16), (0.034, z + 0.18), (0.029, z + 0.185),
                       (0.029, z + 0.23), (0, z + 0.23)], M["pvc"], segs=32)
    mb.finish("PART_CheckValve_NW", sec, coll)

    # discharge: straight up to the joists, through the joist bay and the rim joist, then down and away
    zt = CHECK_Z + 0.23
    out = YN + WALL_T + 0.10
    x = MAIN_XY.x
    pts = [at(MAIN_XY, zt - 0.03), at(MAIN_XY, EXIT_Z), Vector((x, out, EXIT_Z)),
           Vector((x, out, EXIT_Z - 0.35)), Vector((x, out + 0.6, EXIT_Z - 0.35))]
    mb = MB()
    mb.pipe_path(pts, PVC15_R, 0.045, M["pvc"], fit_r=PVC15_FIT)
    dl = mb.finish("PART_DischargeLine_NW", sec, coll)
    label_marker(dl, (x, MAIN_XY.y, 1.5))

    # battery + charger/inverter on the floor, cable in under the lid to the backup pump
    bx0, bx1, by0, by1 = XW + 1.02, XW + 1.35, YN - 0.52, YN - 0.32
    cy = (by0 + by1) / 2
    mb = MB()
    mb.box(bx0, bx1, by0, by1, 0.0, 0.235, M["battery"])
    mb.box(bx0 - 0.005, bx1 + 0.005, by0 - 0.005, by1 + 0.005, 0.235, 0.255, M["battery"])
    mb.box(bx0 + 0.05, bx1 - 0.05, by0 + 0.035, by1 - 0.035, 0.255, 0.335, M["charger"])
    lid_pt = C + (Vector((bx0, cy, 0)) - C).normalized() * (BASIN_FLANGE - 0.02)
    mb.pipe_path([Vector((bx0 + 0.05, cy, 0.30)), Vector((bx0 - 0.04, cy, 0.30)), Vector((bx0 - 0.04, cy, 0.006)),
                  Vector((lid_pt.x, lid_pt.y, 0.006))], 0.005, 0.02, M["cable"], segs=10)
    mb.finish("PART_BackupBattery_NW", sec, coll)

    # concrete patch and stone around the basin
    sq0, sq1 = SUMP_SQ
    mb = MB()
    mb.box(XW + sq0, XW + sq1, YN - sq1, YN - sq0, FOOT_TOP, 0.0, M["patch"], tile=2.0)
    mb.finish("FILL_SumpPatch_NW", sec, coll)
    mb = MB()
    mb.box(XW + sq0, XW + sq1, YN - sq1, YN - sq0, SUBBASE_BOTTOM + 0.04, FOOT_TOP, M["stone"], tile=0.3)
    mb.finish("FILL_SumpStone_NW", sec, coll)
    # concrete over the footings beside the square (an L along both walls). It never moves: as part of
    # the N/W trench patches it used to fly through the lid, the check valve and the battery.
    mb = MB()
    xw, yn = XW + SYS_FRONT + sys_off("W"), YN - SYS_FRONT - sys_off("N")     # in front of the wall systems
    mb.box(xw, XW + sq0, YN - sq1, yn, FOOT_TOP + DIMPLE_T, 0.0, M["patch"], tile=2.0)
    mb.box(XW + sq0, XW + sq1, YN - sq0, yn, FOOT_TOP + DIMPLE_T, 0.0, M["patch"], tile=2.0)
    mb.finish("SHELL_SumpCorner_NW", sec, coll)


def label_marker(part, loc):
    """Empty under a part that tells the web viewer where to pin the part's label."""
    ob = bpy.data.objects.new("LBL_" + part.name, None)
    ob.empty_display_size = 0.1
    part.users_collection[0].objects.link(ob)
    ob.parent = part
    ob.location = loc
    return ob


def smooth_path(ctrl, steps=6):
    """Catmull-Rom curve through the control points."""
    P = [Vector(p) for p in ctrl]
    P = [P[0]] + P + [P[-1]]
    out = []
    for i in range(1, len(P) - 2):
        p0, p1, p2, p3 = P[i - 1], P[i], P[i + 1], P[i + 2]
        for s in range(steps):
            t = s / steps
            out.append(0.5 * (2 * p1 + (p2 - p0) * t + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t * t
                              + (3 * p1 - p0 - 3 * p2 + p3) * t * t * t))
    out.append(P[-2])
    return out


def build_window_well(M, root):
    """Corrugated galvanized well around the south window, bolted to the wall, with a gravel bed."""
    sec, coll = section(root, "SEC_WindowWell")
    w0, w1 = WINDOWS[WELL_SIDE]
    cx, wy = (w0 + w1) / 2, YS - WALL_T            # window centre, outside face of the south wall
    a, b, z0, z1 = WELL_HALF_W, WELL_OUT, WELL_Z0, WELL_Z1
    lam, amp, J = 0.06, 0.006, 40                   # corrugation pitch and depth, segments around
    K = int(round((z1 - z0) / lam * 8))

    def edge(t, z, extra=0.0):                      # half-ellipse in plan, rippled for the corrugation
        n = Vector((math.cos(t) / a, -math.sin(t) / b, 0)).normalized()
        base = Vector((cx + a * math.cos(t), wy - b * math.sin(t), z))
        return base + n * (amp * math.sin(2 * math.pi * (z - z0) / lam) + extra)

    mb = MB()
    idx = mb.mi(M["galv"])
    grid = [[mb.bm.verts.new(edge(math.pi * j / J, z0 + (z1 - z0) * k / K)) for j in range(J + 1)]
            for k in range(K + 1)]
    for k in range(K):
        for j in range(J):
            f = mb.bm.faces.new((grid[k][j], grid[k][j + 1], grid[k + 1][j + 1], grid[k + 1][j]))
            f.material_index, f.smooth = idx, True
            for loop in f.loops:
                loop[mb.uv].uv = (0.5, 0.5)
    mb.tube([edge(math.pi * j / J, z1, 0.004) for j in range(J + 1)], 0.008, M["galv"], segs=8)  # rolled top
    for xa, xb in ((cx + a, cx + a + 0.065), (cx - a - 0.065, cx - a)):                       # wall flanges
        mb.box(xa, xb, wy - 0.004, wy, z0, z1, M["galv"])
        for zb in (z0 + 0.12, (z0 + z1) / 2, z1 - 0.12):
            xm = (xa + xb) / 2
            mb.cyl((xm, wy - 0.004, zb), (xm, wy - 0.013, zb), 0.009, M["metal"], segs=6)
    well = mb.finish(f"PART_WindowWell_{WELL_SIDE}", sec, coll)
    label_marker(well, tuple(edge(math.pi / 2, z1 - 0.06)))

    mb = MB()
    poly = [(cx + (a - 0.012) * math.cos(t), wy - (b - 0.012) * math.sin(t)) for t in (math.pi * j / 24 for j in range(25))]
    mb.prism(poly, z0, z0 + WELL_GRAVEL, M["stone"], tile=0.3)
    mb.finish(f"FILL_WellGravel_{WELL_SIDE}", sec, coll)


def crack_points(seed=11, n=24):
    """Jagged crack path as (x, z) points in the north wall's plane."""
    rng = np.random.default_rng(seed)
    a, b = Vector(CRACK_FROM), Vector(CRACK_TO)
    d = b - a
    t = d.normalized()
    perp = Vector((-t.y, t.x))
    pts, off = [], 0.0
    for i in range(n + 1):
        off = 0.0 if i in (0, n) else 0.55 * off + float(rng.normal(0, 0.011))
        pts.append(a + d * (i / n) + perp * off)
    return pts


def build_crack(M, root):
    """Crack through the poured north wall, the polyurethane that fills it, and an invisible hover area."""
    sec, coll = section(root, "SEC_CrackRepair")
    pts = crack_points()
    n = len(pts) - 1

    def side_of(i):                                  # unit vector across the crack, in the wall plane
        t = (pts[min(i + 1, n)] - pts[max(i - 1, 0)]).normalized()
        return Vector((-t.y, t.x))

    def ribbon(mb, mat, y, half_width):              # flat strip along the crack at depth y
        idx, prev = mb.mi(mat), None
        for i, p in enumerate(pts):
            q = side_of(i) * half_width(i)
            pair = (mb.bm.verts.new((p.x + q.x, y, p.y + q.y)), mb.bm.verts.new((p.x - q.x, y, p.y - q.y)))
            if prev:
                f = mb.bm.faces.new((prev[0], prev[1], pair[1], pair[0]))
                f.material_index = idx
                for loop in f.loops:
                    loop[mb.uv].uv = (0.5, 0.5)
            prev = pair

    # the crack line, on both faces of the wall (wider at the window corner)
    mb = MB()
    for y in (YN - 0.0015, YN + WALL_T + 0.0015):
        ribbon(mb, M["crack"], y, lambda i: 0.002 + 0.0045 * (1 - i / n))
    mb.finish("SHELL_Crack_N", sec, coll)

    # polyurethane filling the crack through the full wall thickness
    mb = MB()
    idx = mb.mi(M["polyurethane"])
    rings = []
    for i, p in enumerate(pts):
        q = side_of(i) * 0.003
        rings.append([mb.bm.verts.new((p.x + s * q.x, y, p.y + s * q.y))
                      for s, y in ((1, YN + 0.001), (-1, YN + 0.001), (-1, YN + WALL_T - 0.001), (1, YN + WALL_T - 0.001))])
    faces = []
    for ra, rb in zip(rings, rings[1:]):
        for k in range(4):
            faces.append(mb.bm.faces.new((ra[k], ra[(k + 1) % 4], rb[(k + 1) % 4], rb[k])))
    faces += [mb.bm.faces.new(list(reversed(rings[0]))), mb.bm.faces.new(rings[-1])]
    for f in faces:
        f.material_index = idx
        for loop in f.loops:
            loop[mb.uv].uv = (0.5, 0.5)
    mb._orient(faces)
    mb.finish("PART_CrackRepair_N", sec, coll)

    # invisible, wider strip so the thin crack is easy to hover or tap (hidden by the web viewer)
    mb = MB()
    ribbon(mb, M["hit"], YN - 0.004, lambda i: 0.11)
    mb.finish("HIT_CrackRepair_N", sec, coll)


def build_dehumidifier(M, root):
    """Floor dehumidifier near the sump; its drain hose runs along the floor in under the sump lid."""
    sec, coll = section(root, "SEC_Dehumidifier")
    x0, x1, y0, y1 = DEHU
    zf, zt = 0.025, DEHU_H
    mb = MB()
    mb.box(x0, x1, y0, y1, zf, zt, M["dehu"])
    mb.box(x0 + 0.06, x1 - 0.06, y0 - 0.002, y0 + 0.004, 0.09, 0.42, M["grille"])        # front grille
    for k in range(9):                                                                    # louvres
        z = 0.105 + k * 0.036
        mb.box(x0 + 0.06, x1 - 0.06, y0 - 0.007, y0 - 0.002, z, z + 0.012, M["dehu"])
    mb.box(x0 - 0.004, x0 + 0.002, y0 + 0.05, y1 - 0.05, 0.12, 0.40, M["grille"])        # side intake
    mb.box(x1 - 0.22, x1 - 0.06, y0 + 0.03, y0 + 0.11, zt, zt + 0.006, M["grille"])     # controls
    for fx in (x0 + 0.05, x1 - 0.05):
        for fy in (y0 + 0.05, y1 - 0.05):
            mb.cyl((fx, fy, 0.0), (fx, fy, zf), 0.02, M["rubber"], segs=12)
    hose = smooth_path([(x0 - 0.002, y1 - 0.06, 0.07), (x0 - 0.06, y1 - 0.07, 0.05), (x0 - 0.10, y1 - 0.12, 0.012),
                        (x0 - 0.14, y0 + 0.01, 0.009), (XW + 1.10, YN - 0.585, 0.009),
                        (XW + 0.80, YN - 0.575, 0.009)], steps=6)
    mb.tube(hose, 0.009, M["hose"], segs=10)
    dh = mb.finish("PART_Dehumidifier_N", sec, coll)
    label_marker(dh, ((x0 + x1) / 2, (y0 + y1) / 2, zt + 0.01))


def build_water_heater(M, root):
    """Water heater on the east wall with a drain grate around it (David's photo, 2026-11-05). The heater stays
    put (the viewer fades it while the section is open); the U's pieces lift out of the trench in a stack."""
    side = WH_SIDE
    sec, coll = section(root, "SEC_DrainGrate")
    n, av, up = inward(side), along_vec(side), Vector((0, 0, 1))
    C = P(side, WH_S, WH_D, 0.0)
    R, H = WH_R, WH_H

    # ---- water heater: tank, water lines up into the joists (shutoff on the cold), T&P valve with its
    # discharge pipe, drain valve, wiring box
    mb = MB()
    mb.lathe(C, [(0, 0.0), (R - 0.012, 0.0), (R - 0.012, 0.02), (R, 0.035), (R, H - 0.06),
                 (R - 0.015, H - 0.02), (R - 0.06, H), (0, H)], M["heater"], segs=40)
    z_top = WALL_TOP + SILL_T + RIM_H
    for sgn in (-1, 1):                                   # cold (south side), hot (north side)
        p = C + av * (sgn * 4 * IN)
        mb.cyl(p + up * (H - 0.01), p + up * (H + 1.5 * IN), 0.55 * IN, M["metal"], segs=16)
        mb.cyl(p + up * (H + 1.5 * IN), p + up * (H + 2.6 * IN), 0.8 * IN, M["brass"], segs=16)
        mb.cyl(p + up * (H + 2.6 * IN), Vector((p.x, p.y, z_top)), 0.44 * IN, M["copper"], segs=16)
        if sgn < 0:
            zv = H + 10 * IN
            mb.cyl(p + up * zv, p + up * (zv + 2.4 * IN), 0.75 * IN, M["brass"], segs=16)
            a = p + up * (zv + 1.1 * IN) - av * (0.3 * IN)
            b = p + n * (3.5 * IN) + up * (zv + 1.3 * IN) + av * (0.3 * IN)
            mb.box(a.x, b.x, a.y, b.y, a.z, b.z, M["handle"])
    zt = H - 6 * IN                                       # T&P valve on the south side, pipe down to 6" off the floor
    tp0 = C - av * (R - 0.004) + up * zt
    tp1 = C - av * (R + 2.0 * IN) + up * zt
    mb.cyl(tp0, tp1, 0.6 * IN, M["brass"], segs=16)
    mb.box(tp1.x - 0.3 * IN, tp1.x + 0.3 * IN, tp1.y, tp1.y + 1.6 * IN, tp1.z + 0.6 * IN, tp1.z + 0.8 * IN, M["brass"])
    mb.cyl(tp1, Vector((tp1.x, tp1.y, 6 * IN)), 0.44 * IN, M["copper"], segs=16)
    d0 = C + n * (R - 0.004) + up * (7 * IN)              # drain valve, facing the room
    mb.cyl(d0, d0 + n * (1.4 * IN), 0.42 * IN, M["brass"], segs=16)
    mb.cyl(d0 + n * (1.4 * IN), d0 + n * (2.0 * IN), 0.55 * IN, M["brass"], segs=16)
    mb.cyl(d0 + n * (0.7 * IN), d0 + n * (0.7 * IN) + up * (0.8 * IN), 0.3 * IN, M["brass"], segs=12)
    j = C - n * (R - 3 * IN)                              # wiring box on top, conduit up
    mb.box(j.x - 1.5 * IN, j.x + 1.5 * IN, j.y - 1.5 * IN, j.y + 1.5 * IN, H - 0.012, H + 2 * IN, M["metal"])
    mb.cyl(j + up * (H + 2 * IN), Vector((j.x, j.y, z_top)), 0.35 * IN, M["metal"], segs=12)
    mb.finish("SHELL_WaterHeater_WH", sec, coll)

    # ---- the 4" pipe's jog around the island: four 90s and the three runs between them
    mb = MB()
    turns = [(P(side, U_S, PIPE_OFF, PIPE_Z), av, n), (P(side, U_S, U_F, PIPE_Z), n, av),
             (P(side, U_N, U_F, PIPE_Z), av, -n), (P(side, U_N, PIPE_OFF, PIPE_Z), -n, av)]
    ends = []
    for K, d_in, d_out in turns:
        a, b = mb.bend(K, d_in, d_out, BEND_R, FIT_R, M["pvc"])
        mb.cyl(a - d_in * 0.04, a, FIT_R + 0.004, M["pvc"])
        mb.cyl(b, b + d_out * 0.04, FIT_R + 0.004, M["pvc"])
        ends.append((a, b))
    for (_, b), (a, _) in zip(ends, ends[1:]):
        mb.cyl(b, a, PIPE_R, M["pipe"], vtile=5 * IN, v0=0.0)
    pipe = mb.finish("PART_PerimeterDrain_WH", sec, coll)
    label_marker(pipe, P(side, WH_S - 0.22, U_F, PIPE_Z + PIPE_R))
    hb = MB()                                             # the holes the adapters drop into (kept apart from the
    for s, d in ADAPTERS:                                 # pipe so the stone's pipe channel is cut cleanly)
        hb.pipe_hole(P(side, s, d, PIPE_Z + PIPE_R), av if s == WH_S else n, PIPE_R, ADAPT_R + 0.002, M["hole"])
    holes = hb.finish("DECAL_PipeHoles_WH", sec, coll)
    holes.parent = pipe

    # ---- trench fill: 1" pea gravel bed, 2B stone up to the channel's underside, concrete beside the channel
    legs = [(ISLE[0] - U_W, ISLE[0]), (ISLE[1], ISLE[1] + U_W)]
    mb = MB()
    for s0, s1 in legs:
        mb.wbox(side, s0, s1, FOOT_PROJ, U_OUT, -TRENCH_D, -TRENCH_D + BED_T, M["pea"], tile=0.2)
    mb.wbox(side, ISLE[0], ISLE[1], ISLE[2], U_OUT, -TRENCH_D, -TRENCH_D + BED_T, M["pea"], tile=0.2)
    bed = mb.finish("PART_GravelBed_WH", sec, coll)
    label_marker(bed, P(side, U_N, U_OUT - 0.1, -TRENCH_D + BED_T))
    mb = MB()
    for s0, s1 in legs:
        mb.wbox(side, s0, s1, FOOT_PROJ, U_OUT, -TRENCH_D + BED_T, FOOT_TOP, M["stone"], tile=0.3)
    mb.wbox(side, ISLE[0], ISLE[1], ISLE[2], U_OUT, -TRENCH_D + BED_T, FOOT_TOP, M["stone"], tile=0.3)
    stone = mb.finish("PART_DrainStone_WH", sec, coll)
    label_marker(stone, P(side, U_S, U_OUT - 0.1, FOOT_TOP))
    gw = GRATE_W / 2
    mb = MB()
    for s0, s1, d1 in ((ISLE[0] - U_W, U_S - gw, U_OUT), (U_S + gw, ISLE[0], U_F - gw),
                       (ISLE[1], U_N - gw, U_F - gw), (U_N + gw, ISLE[1] + U_W, U_OUT)):
        mb.wbox(side, s0, s1, 0, d1, FOOT_TOP, 0.0, M["patch"], tile=2.0)
    mb.wbox(side, U_S - gw, U_N + gw, U_F + gw, U_OUT, FOOT_TOP, 0.0, M["patch"], tile=2.0)
    mb.wbox(side, ISLE[0], ISLE[1], ISLE[2], U_F - gw, FOOT_TOP, 0.0, M["patch"], tile=2.0)
    mb.finish("FILL_Patch_WH", sec, coll)

    # ---- channel drain: legs back to the wall and a front run, grate on top, outlet hubs underneath
    mb = MB()
    for c in (U_S, U_N):                                  # (2 mm off the wall, so it lifts clear of it)
        mb.wbox(side, c - gw, c + gw, 0.002, U_F + gw, FOOT_TOP, 0.0, M["channel"])
    mb.wbox(side, U_S + gw, U_N - gw, U_F - gw, U_F + gw, FOOT_TOP, 0.0, M["channel"])
    lip, zg = GRATE_LIP, 0.0006
    for c in (U_S, U_N):                                  # grate: slots run across it (u along, v across)
        s0, s1, d0, d1 = c - gw + lip, c + gw - lip, lip, U_F + gw - lip
        mb.quad([P(side, s0, d0, zg), P(side, s1, d0, zg), P(side, s1, d1, zg), P(side, s0, d1, zg)],
                [(d0 / IN, 0), (d0 / IN, 1), (d1 / IN, 1), (d1 / IN, 0)], M["grate"])
    s0, s1, d0, d1 = U_S + gw - lip, U_N - gw + lip, U_F - gw + lip, U_F + gw - lip
    mb.quad([P(side, s0, d0, zg), P(side, s1, d0, zg), P(side, s1, d1, zg), P(side, s0, d1, zg)],
            [(s0 / IN, 0), (s1 / IN, 0), (s1 / IN, 1), (s0 / IN, 1)], M["grate"])
    for s, d in ADAPTERS:
        mb.cyl(P(side, s, d, HUB_Z), P(side, s, d, FOOT_TOP + 0.002), 1.35 * IN, M["channel"], segs=20)
    grate = mb.finish("PART_DrainGrate_WH", sec, coll)
    label_marker(grate, P(side, WH_S + 0.22, U_F, 0.0))

    # ---- 1.5" PVC male adapters: threads up in the channel's hub, hex, socket end down into the pipe
    mb = MB()
    for s, d in ADAPTERS:
        c = P(side, s, d, 0.0)
        at = lambda z: Vector((c.x, c.y, z))
        # (only 0.8" between the channel and the pipe: the threads hide in the hub, the hex sits in the gap)
        mb.cyl(at(HUB_Z - 0.1 * IN), at(FOOT_TOP - 0.003), 0.95 * IN, M["pvc"], segs=20)          # threads
        for k in range(3):
            z = HUB_Z + (0.03 + 0.09 * k) * IN
            mb.cyl(at(z), at(z + 0.04 * IN), 1.0 * IN, M["pvc"], segs=20)
        mb.cyl(at(HUB_Z - 0.3 * IN), at(HUB_Z - 0.1 * IN), 1.25 * IN, M["pvc"], segs=6)          # hex
        mb.cyl(at(PIPE_Z + PIPE_R - 0.6 * IN), at(HUB_Z - 0.3 * IN), ADAPT_R, M["pvc"], segs=20)   # socket
    ad = mb.finish("PART_MaleAdapter_WH", sec, coll)
    s, d = ADAPTERS[1]
    label_marker(ad, P(side, s, d, HUB_Z - 0.2 * IN))


def temp_object(root, name, fill):
    mb = MB()
    fill(mb)
    me = bpy.data.meshes.new(name)
    mb.bm.to_mesh(me)
    mb.bm.free()
    ob = bpy.data.objects.new(name, me)
    root.objects.link(ob)
    return ob


def remove_temp(ob):
    me = ob.data
    bpy.data.objects.remove(ob, do_unlink=True)
    bpy.data.meshes.remove(me)


def subtract(target, cutter):
    """Boolean-difference `cutter` out of `target`; the result keeps the target's own material."""
    solvers = [i.identifier for i in bpy.types.BooleanModifier.bl_rna.properties["solver"].enum_items]
    mat = target.data.materials[0]
    mod = target.modifiers.new("cut", "BOOLEAN")
    mod.operation, mod.object = "DIFFERENCE", cutter
    mod.solver = "EXACT" if "EXACT" in solvers else solvers[0]
    for attr in ("use_self", "use_hole_tolerant"):
        if hasattr(mod, attr):
            setattr(mod, attr, True)
    dg = bpy.context.evaluated_depsgraph_get()
    dg.update()
    new = bpy.data.meshes.new_from_object(target.evaluated_get(dg))
    target.modifiers.remove(mod)
    if len(new.polygons) < 4:
        print("WARNING: boolean failed for", target.name)
        bpy.data.meshes.remove(new)
        return
    bm = bmesh.new()                                      # drop the odd zero-area sliver the cut can leave
    bm.from_mesh(new)
    bmesh.ops.dissolve_degenerate(bm, dist=1e-6, edges=bm.edges[:])
    bm.to_mesh(new)
    bm.free()
    new.validate(clean_customdata=False)                  # what the glTF exporter would otherwise fix (and warn about)
    new.materials.clear()
    new.materials.append(mat)
    for p in new.polygons:
        p.material_index = 0
    old = target.data
    target.data = new
    bpy.data.meshes.remove(old)
    new.name = target.name


def cut_holes(root):
    objs = {o.name: o for o in model_objects(root)}
    sq0, sq1 = SUMP_SQ
    # dig the sump square out of the slab, sub-base and the N/W trench fills
    pit = temp_object(root, "TMP_pit", lambda mb: mb.box(XW + sq0, XW + sq1, YN - sq1, YN - sq0,
                                                          SUBBASE_BOTTOM + 0.04, 0.05, None))
    for name in ("SHELL_Slab", "SHELL_SubBase", "PART_DrainStone_N", "PART_DrainStone_W",
                 "PART_GravelBed_N", "PART_GravelBed_W"):
        subtract(objs[name], pit)
    remove_temp(pit)
    # drill the weep holes into the block walls
    for side, centers in WEEP_CUTS.items():
        n = inward(side)
        drill = temp_object(root, "TMP_weep", lambda mb: [mb.cyl(c + n * 0.01, c - n * (WEEP_DEPTH + 0.003), WEEP_R, None, segs=16)
                                                          for c in centers])
        subtract(objs[f"SHELL_Wall_{side}"], drill)
        remove_temp(drill)
    # the lid's footprint out of the concrete patch around the sump
    lid = temp_object(root, "TMP_lid", lambda mb: mb.cyl((SUMP_C.x, SUMP_C.y, -0.3), (SUMP_C.x, SUMP_C.y, 0.1),
                                                          BASIN_FLANGE, None, segs=40))
    subtract(objs["FILL_SumpPatch_NW"], lid)
    remove_temp(lid)
    # pipe-shaped channels through all the stone (the fatter fittings dip into the gravel bed too),
    # and the basin's shape out of the sump stone
    def drains(mb):
        for o in objs.values():
            if o.name.startswith(("PART_PerimeterDrain_", "SHELL_DrainTail_")):
                mb.bm.from_mesh(o.data)
    chan = temp_object(root, "TMP_drains", drains)
    for o in objs.values():
        if o.name.startswith(("PART_DrainStone_", "PART_GravelBed_")) or o.name == "FILL_SumpStone_NW":
            subtract(o, chan)
    remove_temp(chan)
    # the male adapters' holes down through the stone around the water heater
    ad = temp_object(root, "TMP_adapters", lambda mb: [mb.cyl(P(WH_SIDE, s, d, PIPE_Z), P(WH_SIDE, s, d, FOOT_TOP + 0.01),
                                                              ADAPT_R + 0.003, None, segs=20) for s, d in ADAPTERS])
    subtract(objs["PART_DrainStone_WH"], ad)
    remove_temp(ad)
    basin = temp_object(root, "TMP_basin", lambda mb: mb.lathe(SUMP_C, [
        (0, -BASIN_D - 0.001), (BASIN_RB + 0.002, -BASIN_D - 0.001), (BASIN_RT + 0.002, -0.012),
        (BASIN_FLANGE, -0.012), (BASIN_FLANGE, 0.2), (0, 0.2)], None, segs=40))
    subtract(objs["FILL_SumpStone_NW"], basin)
    remove_temp(basin)


def build():
    sc = bpy.context.scene
    sc.unit_settings.system = "METRIC"
    sc.unit_settings.scale_length = 1.0
    root = reset_collection()
    M = make_materials(make_textures())
    for side in ("N", "E", "S", "W"):
        build_wall(side, M, root)
    build_floor(M, root)
    build_sump(M, root)
    build_window_well(M, root)
    build_dehumidifier(M, root)
    build_water_heater(M, root)
    build_crack(M, root)
    cut_holes(root)
    os.makedirs(os.path.dirname(BLEND_PATH), exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=BLEND_PATH, check_existing=False)
    objs = model_objects(root)
    tris = sum(sum(len(p.vertices) - 2 for p in o.data.polygons) for o in objs if o.type == "MESH")
    print(f"built {len(objs)} objects, ~{tris} triangles, saved {BLEND_PATH}")


def export(draco=True):
    root = bpy.data.collections[ROOT_COLL]
    names = {o.name for o in model_objects(root)}
    for o in bpy.context.view_layer.objects:
        o.select_set(o.name in names)
    path = GLB_PATH if draco else GLB_NODRACO_PATH
    os.makedirs(os.path.dirname(path), exist_ok=True)
    compression = dict(
        export_draco_mesh_compression_level=6, export_draco_position_quantization=14,
        export_draco_normal_quantization=10, export_draco_texcoord_quantization=12,
    ) if draco else {}
    bpy.ops.export_scene.gltf(
        filepath=path, export_format="GLB", use_selection=True, export_apply=True,
        export_yup=True, export_extras=True, export_cameras=False, export_lights=False,
        export_image_format="AUTO",
        export_draco_mesh_compression_enable=draco, **compression,
    )
    if not draco:
        print(f"exported {path} ({os.path.getsize(path) / 1e6:.2f} MB, no Draco)")
        return
    os.makedirs(os.path.dirname(WEB_GLB_PATH), exist_ok=True)
    shutil.copy2(GLB_PATH, WEB_GLB_PATH)
    print(f"exported {GLB_PATH} ({os.path.getsize(GLB_PATH) / 1e6:.2f} MB) and copied to {WEB_GLB_PATH}")


if RUN in ("build", "all"):
    build()
if RUN in ("export", "all"):
    export()
    export(draco=False)
