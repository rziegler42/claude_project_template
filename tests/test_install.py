import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
spec = importlib.util.spec_from_file_location("install", os.path.join(ROOT, "install.py"))
install = importlib.util.module_from_spec(spec)
spec.loader.exec_module(install)

SENTINEL_EMAIL = "sentinel-global@example.invalid"
HARNESS_NAMES = ["claude-workflow", "remote-runner", "freecad-scripts", "graphify-semantic", "superpowers"]
ALL = "cad-freecad,graphify,formal,claude"


def run(argv, stdin_tty=False):
    lines = []
    original_stderr = sys.stderr
    sys.stderr = io.StringIO()
    try:
        code = install.main(argv, out=lines.append)
        err = sys.stderr.getvalue()
    finally:
        sys.stderr = original_stderr
    return code, "\n".join(lines), err


def read_tree(root):
    tree = {}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d != ".git"]
        for filename in filenames:
            full = os.path.join(dirpath, filename)
            with open(full, encoding="utf-8") as handle:
                tree[os.path.relpath(full, root).replace(os.sep, "/")] = handle.read()
    return tree


class InstallerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.work = self.tmp.name
        gitconfig = os.path.join(self.work, "global.gitconfig")
        with open(gitconfig, "w") as handle:
            handle.write("[user]\n\tname = Sentinel Global\n\temail = %s\n" % SENTINEL_EMAIL)
        self.saved = dict(os.environ)
        os.environ["GIT_CONFIG_GLOBAL"] = gitconfig
        os.environ["GIT_CONFIG_SYSTEM"] = os.devnull
        self.addCleanup(self._restore_env)

    def _restore_env(self):
        os.environ.clear()
        os.environ.update(self.saved)

    def target(self, name="demo"):
        return os.path.join(self.work, name)

    def new(self, with_="", name="demo", extra=None):
        argv = [self.target(name)]
        if with_:
            argv += ["--with", with_]
        argv += ["--git-name", "Test User", "--git-email", "tester@users.noreply.example.invalid"]
        argv += extra or []
        return run(argv)

    # -- structure ----------------------------------------------------

    def test_no_modules_is_neutral_base(self):
        code, out, err = self.new()
        self.assertEqual(code, 0, err)
        tree = read_tree(self.target())
        self.assertIn("AGENTS.md", tree)
        self.assertNotIn("CLAUDE.md", tree)
        self.assertNotIn("docs/cad.md", tree)
        self.assertNotIn("LICENSE", tree)
        self.assertNotIn("Graphify", tree["AGENTS.md"])
        self.assertNotIn("Graphify", tree["docs/plans/next.md"])
        self.assertNotIn("graphify-out", tree[".gitignore"])

    def test_slot_markers_survive_for_add(self):
        self.new()
        tree = read_tree(self.target())
        self.assertIn("@module-slot: agents-guidance", tree["AGENTS.md"])
        self.assertIn("@module-slot: gitignore", tree[".gitignore"])

    def test_all_modules(self):
        code, out, err = self.new(ALL)
        self.assertEqual(code, 0, err)
        tree = read_tree(self.target())
        self.assertIn("CLAUDE.md", tree)
        self.assertIn(".graphifyignore", tree)
        self.assertIn("docs/cad.md", tree)
        self.assertIn("## Graphify", tree["AGENTS.md"])
        self.assertIn("## Formal verification", tree["AGENTS.md"])
        self.assertIn("## CAD work", tree["AGENTS.md"])
        self.assertIn("### FreeCAD", tree["AGENTS.md"])
        self.assertIn("/graphify-out/", tree[".gitignore"])
        self.assertIn("*.FCBak", tree[".gitignore"])
        self.assertIn("/.claude/settings.local.json", tree[".gitignore"])
        self.assertIn("Discovery and impact evidence", tree["docs/plans/next.md"])
        self.assertIn("FreeCAD configuration", tree["docs/cad.md"])
        self.assertIn("freecadcmd", tree["docs/development.md"])
        self.assertIn("[CAD workflow](docs/cad.md)", tree["README.md"])
        self.assertIn("`cad.md`", tree["docs/README.md"])

    def test_requires_resolved(self):
        code, out, err = self.new("cad-freecad")
        self.assertEqual(code, 0, err)
        self.assertIn("Required modules added: cad", out)
        self.assertIn("docs/cad.md", read_tree(self.target()))

    def test_cad_alone_has_no_freecad(self):
        self.new("cad")
        tree = read_tree(self.target())
        for path, text in tree.items():
            if path.startswith(".git"):
                continue
            self.assertNotIn("FCStd", text, path)
            self.assertNotIn("FCBak", text, path)
            self.assertNotIn("freecad", text.lower(), path)

    def test_every_single_module_installs(self):
        for name in install.load_modules():
            with self.subTest(module=name):
                code, out, err = self.new(name, name="m-" + name)
                self.assertEqual(code, 0, err)

    def test_neutrality_outside_harness_modules(self):
        modules = install.load_modules()
        non_harness = [n for n, m in modules.items() if not m["harness"]]
        self.new(",".join(non_harness))
        for path, text in read_tree(self.target()).items():
            for needle in HARNESS_NAMES:
                self.assertNotIn(needle, text, "%s mentions %s" % (path, needle))

    def test_placeholder_name_substituted(self):
        self.new(name="my-project")
        tree = read_tree(self.target("my-project"))
        self.assertIn("# my-project", tree["README.md"])
        self.assertNotIn("REPLACE_WITH_PROJECT_NAME", tree["README.md"])
        code, out, err = self.new(name="other", extra=["--name", "Custom Name"])
        self.assertIn("# Custom Name", read_tree(self.target("other"))["README.md"])

    # -- runner contract stub -----------------------------------------

    STUB = ".claude/remote-runner.toml"

    def test_runner_stub_shipped_with_claude(self):
        code, out, err = self.new("claude", name="my-project")
        self.assertEqual(code, 0, err)
        tree = read_tree(self.target("my-project"))
        self.assertIn(self.STUB, tree)
        self.assertIn('id = "my-project"', tree[self.STUB])
        self.assertNotIn("REPLACE_WITH_", tree[self.STUB])
        self.assertNotIn(".claude/settings.local.json", tree)
        self.assertNotIn("Unresolved placeholders:\n  .claude", out)

    def test_runner_stub_declares_no_profile(self):
        tomllib = None
        try:
            import tomllib
        except ImportError:
            self.skipTest("tomllib needs Python 3.11+")
        self.new("claude")
        with open(os.path.join(self.target(), self.STUB), "rb") as handle:
            data = tomllib.load(handle)
        self.assertEqual(list(data), ["project"])
        self.assertEqual(list(data["project"]), ["id"])

    def test_runner_stub_absent_without_claude(self):
        self.new("graphify")
        self.assertNotIn(self.STUB, read_tree(self.target()))

    def test_runner_id_is_slugged_from_name(self):
        for name, expected in (("My Project", "My-Project"), ('a"b\\c', "a-b-c"), ("x_y-1", "x_y-1")):
            with self.subTest(name=name):
                code, out, err = self.new("claude", name="p", extra=["--name", name])
                self.assertEqual(code, 0, err)
                text = read_tree(self.target("p"))[self.STUB]
                self.assertIn('id = "%s"' % expected, text)
                self.tmp_clear("p")

    def tmp_clear(self, name):
        import shutil
        shutil.rmtree(self.target(name))

    def test_unusable_runner_id_refused_before_writing(self):
        for name in ("---", "\u65e5\u672c\u8a9e", "_x"):
            with self.subTest(name=name):
                code, out, err = self.new("claude", name="p", extra=["--name=" + name])
                self.assertEqual(code, 2)
                self.assertIn("project id", err)
                self.assertFalse(os.path.exists(self.target("p")))

    def test_unusable_runner_id_ok_without_a_runner_stub(self):
        code, out, err = self.new("", name="p", extra=["--name=---"])
        self.assertEqual(code, 0, err)

    def test_add_claude_matches_fresh_install(self):
        self.new("")
        code, out, err = run(["--add", "claude", "--dir", self.target()])
        self.assertEqual(code, 0, err)
        self.new("claude", name="fresh", extra=["--name", "demo"])
        added = read_tree(self.target())
        fresh = read_tree(self.target("fresh"))
        added.pop(".template-manifest"), fresh.pop(".template-manifest")
        self.assertEqual(added.keys(), fresh.keys())
        for path in fresh:
            self.assertEqual(added[path], fresh[path], path)
        self.assertIn('id = "demo"', added[self.STUB])

    # -- git ----------------------------------------------------------

    def git(self, *args, cwd=None):
        return subprocess.run(
            ["git"] + list(args), cwd=cwd or self.target(), text=True, capture_output=True
        )

    def test_fresh_repo_no_remote_no_commits(self):
        self.new()
        self.assertEqual(self.git("remote").stdout.strip(), "")
        self.assertNotEqual(self.git("rev-parse", "HEAD").returncode, 0)
        self.assertEqual(self.git("symbolic-ref", "HEAD").stdout.strip(), "refs/heads/main")
        with open(os.path.join(self.target(), ".git", "info", "exclude")) as handle:
            self.assertIn("/.debug/", handle.read())

    def test_identity_is_local_and_never_global(self):
        code, out, err = self.new()
        self.assertEqual(self.git("config", "--local", "user.email").stdout.strip(),
                         "tester@users.noreply.example.invalid")
        with open(os.path.join(self.target(), ".git", "config")) as handle:
            self.assertNotIn(SENTINEL_EMAIL, handle.read())
        self.assertNotIn(SENTINEL_EMAIL, out)

    def test_identity_required_when_not_interactive(self):
        code, out, err = run([self.target("noid")])
        self.assertEqual(code, 2)
        self.assertIn("git identity required", err)
        self.assertFalse(os.path.exists(self.target("noid")))

    def test_identity_validation(self):
        code, out, err = run([self.target("bad"), "--git-name", "A", "--git-email", "nope"])
        self.assertEqual(code, 2)
        self.assertFalse(os.path.exists(self.target("bad")))

    def test_explicit_global_identity_bypass_is_reported(self):
        code, out, err = run([self.target("g"), "--use-global-git-identity"])
        self.assertEqual(code, 0, err)
        self.assertIn("INHERITED", out)
        self.assertEqual(self.git("config", "--local", "user.email", cwd=self.target("g")).returncode, 1)

    def test_non_noreply_email_warns(self):
        code, out, err = run([self.target("w"), "--git-name", "A", "--git-email", "a@example.com"])
        self.assertEqual(code, 0, err)
        self.assertIn("not a noreply", out)

    # -- refusals -----------------------------------------------------

    def test_refuses_non_empty_target(self):
        os.makedirs(self.target("full"))
        with open(os.path.join(self.target("full"), "x"), "w") as handle:
            handle.write("x")
        code, out, err = self.new(name="full")
        self.assertEqual(code, 2)

    def test_accepts_existing_empty_target(self):
        os.makedirs(self.target("empty"))
        code, out, err = self.new(name="empty")
        self.assertEqual(code, 0, err)

    def test_refuses_target_inside_template(self):
        code, out, err = run([os.path.join(ROOT, "scratch-out"), "--git-name", "A", "--git-email", "a@b.c"])
        self.assertEqual(code, 2)
        self.assertFalse(os.path.exists(os.path.join(ROOT, "scratch-out")))

    def test_unknown_module(self):
        code, out, err = self.new("nope")
        self.assertEqual(code, 2)
        self.assertIn("unknown module", err)
        self.assertFalse(os.path.exists(self.target()))

    def test_dry_run_writes_nothing(self):
        code, out, err = run([self.target("dry"), "--with", ALL, "--dry-run"])
        self.assertEqual(code, 0, err)
        self.assertIn("Dry run", out)
        self.assertFalse(os.path.exists(self.target("dry")))

    # -- manifest and summary ----------------------------------------

    def test_manifest(self):
        self.new("cad-freecad")
        with open(os.path.join(self.target(), ".template-manifest")) as handle:
            manifest = json.load(handle)
        self.assertEqual(manifest["schema"], 1)
        self.assertEqual(manifest["modules"], ["cad", "cad-freecad"])
        self.assertIn("template_dirty", manifest)

    def test_placeholder_summary(self):
        code, out, err = self.new("cad")
        self.assertIn("Unresolved placeholders", out)
        self.assertIn("docs/cad.md", out)

    # -- --add --------------------------------------------------------

    def test_add_matches_fresh_install(self):
        self.new("cad")
        code, out, err = run(["--add", "cad-freecad", "--dir", self.target()])
        self.assertEqual(code, 0, err)
        self.new("cad-freecad", name="fresh", extra=["--name", "demo"])
        added = read_tree(self.target())
        fresh = read_tree(self.target("fresh"))
        added.pop(".template-manifest"), fresh.pop(".template-manifest")
        self.assertEqual(added.keys(), fresh.keys())
        for path in fresh:
            self.assertEqual(added[path], fresh[path], path)

    def test_add_is_idempotent(self):
        self.new("cad")
        run(["--add", "graphify", "--dir", self.target()])
        before = read_tree(self.target())
        code, out, err = run(["--add", "graphify", "--dir", self.target()])
        self.assertEqual(code, 0, err)
        self.assertIn("Nothing to add", out)
        self.assertEqual(before, read_tree(self.target()))

    def test_add_keeps_user_edits(self):
        self.new()
        path = os.path.join(self.target(), "README.md")
        with open(path, "a") as handle:
            handle.write("\nuser edit\n")
        run(["--add", "cad", "--dir", self.target()])
        with open(path) as handle:
            self.assertIn("user edit", handle.read())

    def test_add_conflicting_file_refused(self):
        self.new()
        os.makedirs(os.path.join(self.target(), "docs"), exist_ok=True)
        with open(os.path.join(self.target(), "docs", "cad.md"), "w") as handle:
            handle.write("mine\n")
        before = read_tree(self.target())
        code, out, err = run(["--add", "cad", "--dir", self.target()])
        self.assertEqual(code, 2)
        self.assertIn("differs", err)
        self.assertEqual(before, read_tree(self.target()))

    def test_add_requires_manifest(self):
        os.makedirs(self.target("legacy"))
        code, out, err = run(["--add", "cad", "--dir", self.target("legacy")])
        self.assertEqual(code, 2)
        self.assertIn("created by this installer", err)

    def test_add_updates_manifest(self):
        self.new()
        run(["--add", "cad-freecad", "--dir", self.target()])
        with open(os.path.join(self.target(), ".template-manifest")) as handle:
            self.assertEqual(json.load(handle)["modules"], ["cad", "cad-freecad"])

    def test_list(self):
        code, out, err = run(["--list"])
        self.assertEqual(code, 0)
        self.assertIn("cad-freecad (requires cad)", out)
        self.assertIn("claude (harness)", out)


class ModuleHygieneTest(unittest.TestCase):
    def test_every_fragment_has_a_marker_in_some_file(self):
        modules = install.load_modules()
        names = install.resolve(list(modules), modules)
        tree = install.assemble(names, modules)  # raises on an orphan fragment
        self.assertTrue(tree)

    def test_module_names_valid(self):
        for name, meta in install.load_modules().items():
            self.assertRegex(name, install.NAME_RE.pattern)
            for req in meta["requires"]:
                self.assertIn(req, install.load_modules())


if __name__ == "__main__":
    unittest.main()
