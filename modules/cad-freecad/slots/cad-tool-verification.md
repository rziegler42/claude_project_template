### FreeCAD verification

- For FreeCAD scripting or MCP work, use user-level FreeCAD scripting guidance
  when it is configured; run pure geometry headless (`freecadcmd`) and use the
  live GUI only when GUI state is required.
- Headless FreeCAD has no GUI: `ViewObject` is `None`, constructing a Qt widget
  aborts the process, and the Curves workbench commands need the GUI session.
  Assembly joint creation was only verified in the GUI session.
