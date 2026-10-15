### FreeCAD specifics

- Keep dimensions in one `App::VarSet` and drive sketch constraints, feature
  lengths, and joint offsets from it with expressions. Use its documented
  naming convention consistently.
- Constraint names that match unit symbols (`h`, `m`, `s`, `l`, `t`, `g`, `in`,
  `mm`, `N`, `V`) fail to parse in FreeCAD expressions.
- Treat `.FCStd` files as binary: keep associated scripts and plain-text
  parameter or design notes reviewable, and state in the README or an ADR
  whether `.FCStd` files are committed directly or stored another way (for
  example Git LFS).
- FreeCAD writes timestamped backups next to the model
  (`name.YYYYMMDD-HHMMSS.FCBak`). They are local recovery files and are
  ignored by this project's `.gitignore`; do not commit them.
