Command notes verified against FreeCAD 1.1.4:

- Run a check headless with `freecadcmd <script.py> -- <arguments>`; arguments
  after `--` appear in `sys.argv`. On macOS the binary is
  `/Applications/FreeCAD.app/Contents/Resources/bin/freecadcmd`.
- Headless FreeCAD has no GUI: `ViewObject` is `None`, constructing a Qt widget
  aborts the process, and the Curves workbench commands need the GUI session.
  Assembly joint creation was only verified in the GUI session.
- Add the project's model-check script (recompute without errors, critical
  dimensions, sketch constraint state, export read-back) to the command table
  above, and say whether it needs the GUI.
- Add-ons such as Curves or Curved Shapes are not part of FreeCAD: list the
  required versions in `cad.md` and re-run the model checks after updating them.
