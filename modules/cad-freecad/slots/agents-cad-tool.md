### FreeCAD

For FreeCAD scripting, MCP `execute_code` work, mesh reverse engineering,
image-to-CAD modelling, assemblies, or 3MF export, use user-level FreeCAD
scripting guidance when it is configured, and follow `docs/cad.md`.

- Test unfamiliar API calls headless first (`freecadcmd`), then in the live GUI.
- Do not rely on recalled FreeCAD API: several calls no longer exist in 1.1
  (PySide2, `Support`, `import FEM`, and others). Consult the user-level
  guidance's deprecated-API table when it is available.
