# Trench drain: add a parametric Width

Family: `PNC_Linear_Trench_Drain NEW.rfa` (Revit 2024, Plumbing Fixtures).
It already has a working **Length** (with a grate array). This adds **Width**.

`.rfa` files can only be edited inside Revit, so this folder gives you a script
to run in Revit and the manual steps to do the same thing by hand.

## Option A: run the script (fastest)

1. Save a backup copy of the `.rfa`.
2. Open the family in Revit.
3. Run `add_width_parameter.py` with **pyRevit** or **RevitPythonShell**.
4. Read the printed report. A message saying `Flex test PASSED` means it worked.
5. Open **Family Types**, change Width a few times and check the plan and 3D views.
6. Save.

The script:

- adds a `Width` parameter, instance or type to match `Length`
- adds two reference planes on the outer edges, with an **EQ** dimension about the centre plane and an overall dimension labelled `Width`
- locks the outer faces of all solids to those planes
- keeps channel wall, lip and frame thicknesses fixed (faces within 60 mm of an edge get their own plane, locked at a fixed distance)
- changes Width by +100 mm as a test, then puts it back

You can change the settings at the top of the script, such as `EDGE_ZONE_MM` and `WIDTH_PARAM_NAME`.
Use **Undo** to remove everything the script did, because it runs as one step.

## Option B: by hand

1. Open the **Ref. Level** floor plan.
2. Draw two **reference planes** along the drain, one on each long edge.
3. Draw a dimension from the edge plane to the **Center (Front/Back)** plane to the other edge plane. Click **EQ**.
4. Draw an overall dimension between the two edge planes. Select it, then in **Label**, choose **Create Parameter**. Name it `Width`, set it to Instance to match Length, and put it in the Dimensions group.
5. Use **Align** (`AL`) to lock the geometry to the planes. Click the plane, click the face, then click the padlock. Do this for:
   - the outer sides of the channel body
   - the sides of the **Drain Void**
   - the sides of the **first grate** in the array (the other copies follow it)
6. For the inner channel walls, add a reference plane at each inner face. Dimension it to the nearest edge plane and lock that dimension, so the wall thickness stays fixed. Then align the inner face to the new plane and lock it.
7. If an extrusion's profile was sketched in a **section or elevation view**, edit the sketch there. Lock its sketch lines to the edge planes, which you can see in that view.
8. **Flex** it: in Family Types, try several widths before saving.

## Things to watch

- **Imported CAD/ACIS geometry** cannot stretch. The script reports any it finds. Rebuild those parts as extrusions or sweeps.
- If the grate is a **nested family**, it needs its own Width parameter. Link it to the host's `Width` through the nested family's type properties.
- If some faces are reported as "could not lock", lock them by hand with Option B, step 5.
