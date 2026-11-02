# -*- coding: utf-8 -*-
"""
Add a parametric WIDTH to a Revit family that is already parametric in LENGTH.

Written for: PNC_Linear_Trench_Drain NEW.rfa (Revit 2024, Plumbing Fixtures).
Works with: pyRevit (IronPython or CPython engine) or RevitPythonShell, Revit 2022+.

HOW TO RUN
  1. Open the .rfa in Revit (Family Editor). Save a backup copy first.
  2. Run this script (pyRevit: put it in a pushbutton or use the "Run script" tool;
     RevitPythonShell: open it and run).
  3. Read the report it prints, then flex the new "Width" parameter in
     Family Types to check it.

WHAT IT DOES (one undoable transaction)
  - Finds the existing Length dimension to work out which way is "across" the drain.
  - Measures the current width of the solid geometry.
  - Adds a "Width" length parameter (instance/type to match "Length").
  - Draws two reference planes on the outer edges, plus an EQ dimension about the
    centre plane and an overall dimension labelled "Width".
  - Locks every outer face of the geometry to those two planes.
  - For inner faces close to an edge (channel walls, lips, grate frame), adds a
    reference plane and a locked dimension to the nearest edge plane, so wall
    thickness stays the same while the width changes.
  - Tests the result by changing Width by +100 mm, then puts it back.
"""

# ---------------------------------------------------------------- settings
WIDTH_PARAM_NAME = "Width"
LENGTH_PARAM_NAME = "Length"   # the existing parameter that already works
EDGE_ZONE_MM = 60.0            # inner faces within this distance of an edge follow that edge
FLEX_TEST_MM = 100.0           # how much to change Width by during the self-test
PLAN_VIEW_NAME = "Ref. Level"  # plan view used to host planes and dimensions
# -------------------------------------------------------------------------

from Autodesk.Revit.DB import (
    BuiltInParameter, Dimension, FamilyInstance, FilteredElementCollector,
    GenericForm, ImportInstance, Line, Options, PlanarFace, ReferenceArray,
    ReferencePlane, Solid, SubTransaction, Transaction, ViewPlan, XYZ,
    GeometryInstance,
)

try:
    from Autodesk.Revit.DB import GroupTypeId, SpecTypeId
    HAS_FORGE = True
except ImportError:
    HAS_FORGE = False

try:
    doc = __revit__.ActiveUIDocument.Document  # noqa: F821  (pyRevit / RPS)
except NameError:
    from pyrevit import revit
    doc = revit.doc

FT = 304.8  # mm per foot (Revit internal unit)
TOL = 0.5 / FT


def mm(v):
    return v / FT


def say(msg):
    print(msg)


# ------------------------------------------------------------ checks
if not doc.IsFamilyDocument:
    raise Exception("Open the family (.rfa) in the Family Editor first.")

fm = doc.FamilyManager


def find_param(name):
    for p in fm.Parameters:
        if p.Definition.Name.lower() == name.lower():
            return p
    return None


length_param = find_param(LENGTH_PARAM_NAME)


# ------------------------------------------------------------ plan view
def get_plan_view():
    plans = [v for v in FilteredElementCollector(doc).OfClass(ViewPlan)
             if not v.IsTemplate]
    for v in plans:
        if v.Name == PLAN_VIEW_NAME:
            return v
    if plans:
        return plans[0]
    raise Exception("No floor plan view found in the family.")


view = get_plan_view()
z0 = view.GenLevel.Elevation if view.GenLevel else 0.0


# ------------------------------------------------------------ which way is width?
def find_length_axis():
    """Direction of the dimension labelled Length (X or Y)."""
    for d in FilteredElementCollector(doc).OfClass(Dimension):
        try:
            lbl = d.FamilyLabel
        except Exception:
            lbl = None
        if lbl is None or lbl.Definition.Name.lower() != LENGTH_PARAM_NAME.lower():
            continue
        crv = d.Curve
        if isinstance(crv, Line):
            dirn = crv.Direction
            return "X" if abs(dirn.X) >= abs(dirn.Y) else "Y"
    return None


length_axis = find_length_axis()
if length_axis is None:
    say("! Could not find the Length dimension; assuming Length runs along X.")
    length_axis = "X"
width_axis = "Y" if length_axis == "X" else "X"
AX = XYZ.BasisY if width_axis == "Y" else XYZ.BasisX     # across the drain
ALONG = XYZ.BasisX if width_axis == "Y" else XYZ.BasisY  # along the drain
say("Length runs along %s, so Width will run along %s." % (length_axis, width_axis))


def w_of(p):
    return p.DotProduct(AX)


def l_of(p):
    return p.DotProduct(ALONG)


# ------------------------------------------------------------ geometry
def forms():
    out = []
    for e in FilteredElementCollector(doc).WhereElementIsNotElementType():
        if isinstance(e, GenericForm):
            out.append(e)
    return out


def imports():
    return list(FilteredElementCollector(doc).OfClass(ImportInstance))


def nested():
    return list(FilteredElementCollector(doc).OfClass(FamilyInstance))


def extents(elements):
    """(wmin, wmax, lmin, lmax) of the solids, from bounding boxes."""
    wmin = lmin = 1e9
    wmax = lmax = -1e9
    for e in elements:
        if isinstance(e, GenericForm) and not e.IsSolid:
            continue  # voids do not define the outside size
        bb = e.get_BoundingBox(None)
        if bb is None:
            continue
        for p in (bb.Min, bb.Max):
            wmin = min(wmin, w_of(p)); wmax = max(wmax, w_of(p))
            lmin = min(lmin, l_of(p)); lmax = max(lmax, l_of(p))
    return wmin, wmax, lmin, lmax


def width_faces(form):
    """Planar faces of a form whose normal points across the drain."""
    opts = Options()
    opts.ComputeReferences = True
    opts.IncludeNonVisibleObjects = True
    found = []

    def walk(geo):
        for g in geo:
            if isinstance(g, Solid):
                for f in g.Faces:
                    if isinstance(f, PlanarFace) and f.Reference is not None:
                        n = f.FaceNormal
                        if abs(abs(n.DotProduct(AX)) - 1.0) < 1e-6:
                            found.append((w_of(f.Origin), f))
            elif isinstance(g, GeometryInstance):
                walk(g.GetSymbolGeometry())

    geo = form.get_Geometry(opts)
    if geo is not None:
        walk(geo)
    return found


all_forms = forms()
geo_elems = all_forms + nested()
if not geo_elems:
    raise Exception("No solid geometry found to make parametric.")

for imp in imports():
    say("! Imported CAD/ACIS geometry found (id %s). Revit cannot stretch it;"
        " it will keep its size. Rebuild it as native extrusions/sweeps." % imp.Id)

wmin, wmax, lmin, lmax = extents(geo_elems)
cur_width = wmax - wmin
centre = (wmin + wmax) / 2.0
say("Current width: %.1f mm (from %.1f to %.1f mm)." % (cur_width * FT, wmin * FT, wmax * FT))


# ------------------------------------------------------------ helpers to build
def find_centre_plane():
    name = "Center (Front/Back)" if width_axis == "Y" else "Center (Left/Right)"
    best = None
    for rp in FilteredElementCollector(doc).OfClass(ReferencePlane):
        if rp.Name == name:
            return rp
        d = rp.Direction
        if abs(abs(d.DotProduct(ALONG)) - 1.0) < 1e-6 and abs(w_of(rp.BubbleEnd)) < TOL:
            best = rp
    return best


def plane_at(w, name):
    """Reference plane along the drain at width position w (reuses an existing one)."""
    for rp in FilteredElementCollector(doc).OfClass(ReferencePlane):
        d = rp.Direction
        if abs(abs(d.DotProduct(ALONG)) - 1.0) < 1e-6 and abs(w_of(rp.BubbleEnd) - w) < TOL:
            return rp
    a = AX.Multiply(w) + ALONG.Multiply(lmin - mm(300)) + XYZ(0, 0, z0)
    b = AX.Multiply(w) + ALONG.Multiply(lmax + mm(300)) + XYZ(0, 0, z0)
    rp = doc.FamilyCreate.NewReferencePlane(a, b, XYZ.BasisZ, view)
    try:
        rp.Name = name
    except Exception:
        pass
    return rp


def dim_between(planes, l_pos):
    ra = ReferenceArray()
    for rp in planes:
        ra.Append(rp.GetReference())
    ws = [w_of(rp.BubbleEnd) for rp in planes]
    p1 = AX.Multiply(min(ws)) + ALONG.Multiply(l_pos) + XYZ(0, 0, z0)
    p2 = AX.Multiply(max(ws)) + ALONG.Multiply(l_pos) + XYZ(0, 0, z0)
    return doc.FamilyCreate.NewDimension(view, Line.CreateBound(p1, p2), ra)


def add_width_param():
    p = find_param(WIDTH_PARAM_NAME)
    if p is not None:
        say("Using existing parameter '%s'." % WIDTH_PARAM_NAME)
        return p
    is_inst = length_param.IsInstance if length_param else False
    if HAS_FORGE:
        p = fm.AddParameter(WIDTH_PARAM_NAME, GroupTypeId.Geometry, SpecTypeId.Length, is_inst)
    else:  # Revit 2021 and older
        from Autodesk.Revit.DB import BuiltInParameterGroup, ParameterType
        p = fm.AddParameter(WIDTH_PARAM_NAME, BuiltInParameterGroup.PG_GEOMETRY,
                            ParameterType.Length, is_inst)
    say("Added %s parameter '%s'." % ("instance" if is_inst else "type", WIDTH_PARAM_NAME))
    return p


# ------------------------------------------------------------ do it
t = Transaction(doc, "Add parametric Width")
t.Start()
try:
    if fm.CurrentType is None:
        fm.NewType("Default")

    width_p = add_width_param()
    fm.Set(width_p, cur_width)

    side = {+1: plane_at(wmax, "Width Edge +"), -1: plane_at(wmin, "Width Edge -")}
    edge_w = {+1: wmax, -1: wmin}

    # EQ about the centre plane (only if the geometry is centred on it)
    cplane = find_centre_plane()
    dim_l = lmin - mm(400)
    if cplane is not None and abs(centre - w_of(cplane.BubbleEnd)) < mm(1):
        eq = dim_between([side[-1], cplane, side[+1]], dim_l)
        eq.AreSegmentsEqual = True
        say("Width is centred: added EQ dimension about '%s'." % cplane.Name)
    else:
        say("! Geometry is not centred on the centre plane; Width will grow from"
            " the '-' edge only. Add an EQ dimension by hand if you want it centred.")
        if cplane is not None:
            lock = dim_between([cplane, side[-1]], dim_l)
            lock.IsLocked = True

    overall = dim_between([side[-1], side[+1]], dim_l - mm(250))
    overall.FamilyLabel = width_p
    say("Labelled overall dimension with '%s'." % WIDTH_PARAM_NAME)

    # lock faces
    locked = inner = skipped = 0
    inner_planes = {}
    half = cur_width / 2.0
    zone = min(mm(EDGE_ZONE_MM), half * 0.8)
    for f_el in all_forms:
        for w, face in width_faces(f_el):
            s = +1 if w >= centre else -1
            off = abs(edge_w[s] - w)
            if off < TOL:
                target = side[s]
            elif off <= zone:
                key = (s, round(off * FT, 1))
                if key not in inner_planes:
                    rp = plane_at(w, "Width Inner %s%.0f" % ("+" if s > 0 else "-", off * FT))
                    d = dim_between([side[s], rp], lmax + mm(400) + mm(150) * len(inner_planes))
                    d.IsLocked = True
                    inner_planes[key] = rp
                target = inner_planes[key]
            else:
                continue  # central detail: leave it where it is
            try:
                doc.FamilyCreate.NewAlignment(view, target.GetReference(), face.Reference)
                if off < TOL:
                    locked += 1
                else:
                    inner += 1
            except Exception as ex:
                skipped += 1
                say("  could not lock a face of element %s: %s" % (f_el.Id, ex))

    say("Locked %d outer faces and %d inner faces (%d inner edge planes)."
        % (locked, inner, len(inner_planes)))
    if skipped:
        say("! %d faces could not be locked (often arrayed copies; locking the"
            " first array member is usually enough)." % skipped)

    # flex test
    st = SubTransaction(doc)
    st.Start()
    try:
        fm.Set(width_p, cur_width + mm(FLEX_TEST_MM))
        doc.Regenerate()
        n_wmin, n_wmax, _, _ = extents(geo_elems)
        grew = (n_wmax - n_wmin) - cur_width
        if abs(grew - mm(FLEX_TEST_MM)) < mm(1):
            say("Flex test PASSED: +%.0f mm Width gave +%.1f mm geometry." % (FLEX_TEST_MM, grew * FT))
        else:
            say("! Flex test: +%.0f mm Width gave +%.1f mm geometry. Some parts are"
                " not locked yet; see the guide." % (FLEX_TEST_MM, grew * FT))
    except Exception as ex:
        say("! Flex test failed: %s" % ex)
    finally:
        st.RollBack()

    t.Commit()
    say("Done. Save the family, then load it into the project.")
except Exception:
    t.RollBack()
    raise
