# CAD workflow

This document defines the repository-specific CAD contract and is written
for any contributor or tool. FreeCAD 1.1 Python, MCP execution, and
workbench/API specifics live in the user-level `freecad-scripts` skill (see
`AGENTS.md`). Project requirements recorded here take precedence when they
are more specific.

## Project configuration

Fill in these values when adopting the template.

| Topic | Project convention |
|---|---|
| CAD application and version | `REPLACE_WITH_CAD_APPLICATION_AND_VERSION` |
| Primary workbenches | `REPLACE_WITH_WORKBENCHES` |
| Units | `REPLACE_WITH_UNITS` |
| Parameter source and naming | `REPLACE_WITH_VARSET_OR_OTHER_PARAMETER_SOURCE_AND_NAMING_CONVENTION` |
| Part and assembly structure | `REPLACE_WITH_BODY_AND_ASSEMBLY_CONVENTION` |
| Model sources | `REPLACE_WITH_SOURCE_DIRECTORY` |
| Reference inputs and scale source | `REPLACE_WITH_REFERENCE_MESH_OR_IMAGE_DIRECTORY_AND_SCALE_SOURCE_OR_NOT_APPLICABLE` |
| Automation scripts or macros | `REPLACE_WITH_SCRIPT_DIRECTORY_OR_NOT_APPLICABLE` |
| Exports | `REPLACE_WITH_EXPORT_DIRECTORY` |
| Required export formats | `REPLACE_WITH_FORMATS` |
| Mesh export settings and tolerance | `REPLACE_WITH_TESSELLATION_DEFLECTION_AND_DEVIATION_TOLERANCE_OR_NOT_APPLICABLE` |
| Required extensions or add-ons | `REPLACE_WITH_REQUIREMENTS_AND_VERSIONS_OR_NONE` |

Record add-on versions: add-on Python APIs are unversioned and can change when
the add-on updates, so record the version the project was verified against.

## Source of truth and repository layout

- Editable, parametric model sources are authoritative. Do not treat meshes,
  screenshots, or exported interchange files as editable source unless this
  project explicitly says otherwise.
- Keep model inputs, parameter sources, automation scripts, and exports in
  the directories named above. Use stable, descriptive filenames.
- Record the units, coordinate convention, datum/origin convention, and any
  manufacturing assumptions in the model or its adjacent documentation.
- Prefer parameterized dimensions and named constraints over unexplained
  literal values. If the project uses FreeCAD `App::VarSet`, use its documented
  naming convention consistently.
- Treat `.FCStd` files as binary. Keep associated scripts and plain-text
  parameter or design notes reviewable in version control; do not rely on a
  binary diff to explain an engineering change. Models can be several
  megabytes, so state in the README or an ADR whether `.FCStd` files are
  committed directly or stored another way (for example Git LFS).
- FreeCAD writes timestamped backups next to the model
  (`name.YYYYMMDD-HHMMSS.FCBak`). They are local recovery files: do not commit
  them, and add `*.FCBak` to the project's `.gitignore` when FreeCAD is used.

## Parametric conventions

- Keep dimensions in one parameter source (for FreeCAD, an `App::VarSet`) and
  drive sketch constraints, feature lengths, and joint offsets from it with
  expressions, rather than typing literal numbers into features. Record the
  object name and property naming convention in the configuration table.
- Name driven sketch constraints descriptively. Names that match unit symbols
  (`h`, `m`, `s`, `l`, `t`, `g`, `in`, `mm`, `N`, `V`) fail to parse in
  FreeCAD expressions.
- Build each part as its own body, with features created inside it, and combine
  bodies in an assembly or with explicit boolean/binder features.
- Sketches should be fully constrained unless a free degree of freedom is
  intentional and noted; an under-constrained sketch can change shape when a
  parameter changes.

## Reverse-engineered and image-derived models

Use this section when a model is built to match a scanned mesh, a photograph,
or a drawing.

- Keep the source mesh or image as a reference input, not as the model.
  Record its origin, units, and the scale source (a known dimension in the
  image, a caliper reading, a drawing note). An image or mesh without a stated
  scale is not a measurement.
- Label each dimension as measured, standard, or assumed, with the estimated
  error where known. Do not present an estimate as a measurement.
- Compare the finished model with the source and record the result: for a
  mesh, the deviation (maximum, 95th percentile, fraction within tolerance)
  against a stated tolerance; for an image, the comparison method and what
  differs.
- State which regions are approximations (for example freeform surfaces that
  no primitive fits) and which were rebuilt as parametric features.
- A faceted solid converted straight from a mesh is not a parametric model and
  must not be delivered as one.

## Generated artifacts

- Specify in the project README or an ADR which exports are committed and
  which are reproducible build outputs. Do not commit ad hoc duplicates.
- Exported filenames must identify the source model and meaningful revision or
  configuration when several variants exist.
- Export using the project units and orientation. Do not silently convert
  units or reorient a deliverable.
- Keep production artifacts separate from temporary renders, mesh repairs,
  and diagnostics. Retain the latter only under the repository's local debug
  policy unless they are deliberate evidence.

## Change and verification workflow

1. Read this file, the relevant model or script, and the governing drawing,
   requirement, or ADR before changing geometry.
2. For FreeCAD scripting or MCP work, follow the `freecad-scripts` skill;
   use headless execution for pure geometry when practical and the live GUI
   only when GUI state is required.
3. Recompute the document and resolve errors before saving or exporting.
   A feature that reports an up-to-date state can still be wrong; check the
   result, not only the state.
4. Verify the changed geometry against its stated requirements: critical
   dimensions, units, placement/orientation, and (where relevant) volume,
   mass, clearance, interference, or mesh deviation. Check sketches for
   remaining degrees of freedom and for redundant or conflicting constraints.
5. For assemblies, verify the solved placement (bounding box or measured
   positions) after adding or changing a joint. An invalid joint reference can
   be accepted without an error and leave parts at their origins while the
   solver reports success.
6. For printable or manufacturable solids, verify the required topology and
   export integrity. Read the exported file back and confirm it is a closed
   solid with no non-manifold edges, and that its volume and bounding box
   match the model. For curved parts, set the tessellation deflection
   explicitly rather than relying on defaults, and record it.
7. Record assumptions, approximations, measured results, and any intentionally
   unverified condition in the change description, design note, or ADR.

## Design decisions

Create an ADR for durable choices that affect downstream design or
manufacturing: unit systems, coordinate frames, parameter naming, material
assumptions, tolerance strategy, export formats, part/assembly boundaries,
or required add-ons. Reference the ADR here or from the affected model's
documentation instead of duplicating its decision.

## Pre-merge checklist

- [ ] Model recomputes without errors or unresolved dependencies.
- [ ] Critical dimensions and units were checked against the requirement.
- [ ] Dimensions come from the parameter source; sketches are fully constrained
      or the free degrees of freedom are noted.
- [ ] Assembly placements were checked after every joint change.
- [ ] Model source, scripts, and committed exports follow the layout above.
- [ ] Required exports were regenerated, read back, and validated (closed
      solid, volume and bounding box match, tessellation settings recorded).
- [ ] For models derived from a mesh or image: scale source, measured versus
      assumed dimensions, and the deviation or comparison result are recorded.
- [ ] Backup files (`*.FCBak`) and temporary mesh repairs are not committed.
- [ ] Assumptions, approximations, and relevant measurement results are recorded.
- [ ] A durable engineering convention has an ADR when needed.
