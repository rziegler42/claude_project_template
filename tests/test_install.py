import importlib.util
import io
import json
import os
import select
import shutil
import subprocess
import sys
import tempfile
import unittest
import unittest.mock

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
spec = importlib.util.spec_from_file_location("install", os.path.join(ROOT, "install.py"))
install = importlib.util.module_from_spec(spec)
spec.loader.exec_module(install)

SENTINEL_EMAIL = "sentinel-global@example.invalid"
HARNESS_NAMES = ["claude-workflow", "remote-runner", "freecad-scripts", "graphify-semantic", "superpowers",
                 "ask-codex", "second-opinion", "codex"]
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


def run_pty(argv, keystrokes, cwd, env, timeout=10):
    """Run install.py on a pseudo-terminal; return (exit code, terminal output).

    `keystrokes` is typed ahead: the terminal buffers it line by line, so each
    prompt reads the next line, and "\\x04" at a line start is end-of-input.
    """
    import pty
    import time

    master, slave = pty.openpty()
    proc = subprocess.Popen(
        [sys.executable, "-I", os.path.join(ROOT, "install.py")] + argv,
        stdin=slave, stdout=slave, stderr=slave, cwd=cwd, env=env, close_fds=True,
    )
    os.close(slave)
    os.write(master, keystrokes.encode())
    output = b""
    deadline = time.time() + timeout
    try:
        while time.time() < deadline:
            ready, _, _ = select.select([master], [], [], 0.2)
            if ready:
                try:
                    chunk = os.read(master, 4096)
                except OSError:
                    break
                if not chunk:
                    break
                output += chunk
            elif proc.poll() is not None:
                break
    finally:
        if proc.poll() is None:  # still blocked on a prompt: report it, do not hang
            proc.kill()
        proc.wait()
        os.close(master)
    return proc.returncode, output.decode("utf-8", "replace").replace("\r\n", "\n")


def read_tree(root):
    tree = {}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d != ".git"]
        for filename in filenames:
            full = os.path.join(dirpath, filename)
            with open(full, encoding="utf-8") as handle:
                tree[os.path.relpath(full, root).replace(os.sep, "/")] = handle.read()
    return tree


def neutrality_problems(root):
    """(path, name) pairs where tool-specific names appear outside installed harness files."""
    with open(os.path.join(root, ".template-manifest"), encoding="utf-8") as handle:
        recorded = set(json.load(handle).get("harness_files", {}))
    # The manifest lists the installed harness paths, so it is a record, not guidance.
    return [(path, needle) for path, text in read_tree(root).items()
            if path not in recorded and path != ".template-manifest"
            for needle in HARNESS_NAMES if needle in text]


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
        os.environ["XDG_CONFIG_HOME"] = os.path.join(self.work, "xdg")
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

    # -- consistent multi-item options (plan 0011) --------------------

    def created_modules(self):
        with open(os.path.join(self.target(), ".template-manifest")) as handle:
            return json.load(handle)["modules"]

    def new_argv(self, *with_args):
        return [self.target(), "--with", *with_args,
                "--git-name", "Test User", "--git-email", "tester@users.noreply.example.invalid"]

    def test_with_forms_select_the_same_modules(self):
        forms = (("claude,graphify",), ("claude", "graphify"), ("claude,", "graphify"))
        for index, form in enumerate(forms):
            with self.subTest(form=form):
                code, out, err = run([self.target("p%d" % index), *self.new_argv(*form)[1:]])
                self.assertEqual(code, 0, err)
                with open(os.path.join(self.target("p%d" % index), ".template-manifest")) as handle:
                    self.assertEqual(json.load(handle)["modules"], ["claude", "graphify"])

    def test_with_mixes_spaces_and_commas_in_order(self):
        code, out, err = run(self.new_argv("graphify,claude", "cad"))
        self.assertEqual(code, 0, err)
        self.assertEqual(sorted(self.created_modules()), ["cad", "claude", "graphify"])

    def test_with_help_uses_module_placeholder(self):
        text = install.build_parser().format_help()
        self.assertIn("--with MODULE [MODULE ...]", text)
        self.assertNotIn("WITH_", text)

    def test_target_swallowed_by_with_gets_ordering_hint(self):
        argv = ["--with", "claude", self.target(), "--git-name", "Test User",
                "--git-email", "tester@users.noreply.example.invalid"]
        captured = io.StringIO()
        with unittest.mock.patch("sys.stderr", captured), self.assertRaises(SystemExit) as raised:
            install.main(argv, out=lambda line: None)
        self.assertEqual(raised.exception.code, 2)
        self.assertIn("before --with", captured.getvalue())
        self.assertFalse(os.path.exists(self.target()))

    def test_with_still_conflicts_with_other_modes(self):
        for mode in (["--update"], ["--remove", "claude"], ["--register", self.work]):
            with self.subTest(mode=mode):
                code, out, err = run(mode + ["--with", "claude", "graphify"])
                self.assertEqual(code, 2)
                self.assertIn("--with", err)

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
        self.assertEqual(neutrality_problems(self.target()), [])

    def test_neutrality_with_a_harness_ignores_only_installed_harness_files(self):
        modules = install.load_modules()
        non_harness = [n for n, m in modules.items() if not m["harness"]]
        code, out, err = self.new(",".join(non_harness), extra=["--harness", "claude"])
        self.assertEqual(code, 0, err)
        self.assertEqual(neutrality_problems(self.target()), [])
        self.assertIn(".claude/skills/freecad-scripts/SKILL.md",
                      json.loads(read_tree(self.target())[".template-manifest"])["harness_files"])

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

    # -- post-install hints ---------------------------------------------

    def fake_modules(self, specs):
        """Point the installer at a temporary modules directory."""
        root = os.path.join(self.work, "fake-modules")
        os.makedirs(root, exist_ok=True)
        for name, meta in specs.items():
            os.makedirs(os.path.join(root, name), exist_ok=True)
            with open(os.path.join(root, name, "module.json"), "w") as handle:
                json.dump(meta, handle)
        saved = install.MODULES_DIR
        install.MODULES_DIR = root
        self.addCleanup(setattr, install, "MODULES_DIR", saved)
        return root

    def test_graphify_hint_printed_for_new_project(self):
        code, out, err = self.new("graphify")
        self.assertEqual(code, 0, err)
        self.assertIn("Next steps:", out)
        self.assertIn("graphify: ", out)
        self.assertIn("graph-doctor", out)

    def test_no_hint_when_no_selected_module_has_one(self):
        code, out, err = self.new("cad")
        self.assertNotIn("Next steps", out)

    def test_hint_printed_by_add_only_for_new_modules(self):
        self.new("")
        code, out, err = run(["--add", "graphify", "--dir", self.target()])
        self.assertIn("graph-doctor", out)
        code, out, err = run(["--add", "graphify", "--dir", self.target()])
        self.assertNotIn("graph-doctor", out)

    def test_hint_labelled_in_dry_run(self):
        code, out, err = self.new("graphify", extra=["--dry-run"])
        self.assertIn("Next steps (dry run, nothing written):", out)
        self.assertIn("graph-doctor", out)
        self.assertFalse(os.path.exists(self.target()))

    def test_required_module_hint_is_printed_once(self):
        self.fake_modules({
            "lib": {"description": "x", "hint": "start with lib"},
            "app": {"description": "y", "requires": ["lib"], "hint": "then app"},
            "quiet": {"description": "z"},
        })
        code, out, err = self.new("app")
        self.assertEqual(code, 0, err)
        self.assertEqual(out.count("start with lib"), 1)
        self.assertEqual(out.count("then app"), 1)
        self.assertNotIn("quiet", out.split("Next steps:")[1])

    def test_invalid_hints_fail_module_loading(self):
        for bad in (5, ["a"], "two\nlines", "x" * 201, "bell\x07", ""):
            with self.subTest(hint=bad):
                root = self.fake_modules({"m": {"description": "x", "hint": bad}})
                with self.assertRaises(install.InstallError):
                    install.load_modules(root)

    # -- module type, paths and data ----------------------------------------

    def test_module_info_keys_load(self):
        root = self.fake_modules({
            "kb": {"description": "x", "type": "knowledge-base",
                   "paths": {"store": "docs/kb", "index": "docs/kb/index.md"},
                   "data": {"format": 2, "tags": ["a", "b"], "nested": {"on": True, "n": None}}},
            "plain": {"description": "y"},
        })
        modules = install.load_modules(root)
        self.assertEqual(modules["kb"]["type"], "knowledge-base")
        self.assertEqual(modules["kb"]["paths"]["store"], "docs/kb")
        self.assertEqual(modules["kb"]["data"]["format"], 2)
        for key in ("type", "paths", "data"):
            self.assertNotIn(key, modules["plain"])

    def test_builtin_modules_declare_no_info(self):
        for name, meta in install.load_modules().items():
            for key in ("type", "paths", "data"):
                self.assertNotIn(key, meta, name)

    def test_invalid_module_info_fails_module_loading(self):
        deep = {}
        node = deep
        for _ in range(8):
            node["d"] = {}
            node = node["d"]
        bad_values = [
            {"type": 5}, {"type": ""}, {"type": "Bad Type"}, {"type": "x" * 65},
            {"type": None},
            {"paths": []}, {"paths": "docs"}, {"paths": {"store": 5}},
            {"paths": {"store": ""}}, {"paths": {"store": "/abs"}},
            {"paths": {"store": "../up"}}, {"paths": {"store": "a/../b"}},
            {"paths": {"store": "a//b"}}, {"paths": {"store": ".git/hooks"}},
            {"paths": {"store": "bell\x07"}}, {"paths": {"Bad Role": "docs"}},
            {"paths": {"store": "..\\..\\x"}}, {"paths": {"store": "C:\\x"}},
            {"paths": {"store": "a:b"}},
            {"paths": {"store": ".git /hooks"}}, {"paths": {"store": ".git./hooks"}},
            {"paths": {"store": "docs/.GIT. "}},
            {"paths": {"r%d" % i: "docs/%d" % i for i in range(17)}},
            {"data": []}, {"data": "x"}, {"data": {"k": float("nan")}},
            {"data": {"k": float("inf")}}, {"data": deep},
            {"data": {"k": "x" * 201}}, {"data": {"k": "bell\x07"}},
            {"data": {"": 1}}, {"data": {"k" * 65: 1}},
            {"data": {"k%d" % i: "v" * 150 for i in range(40)}},
            {"data": {"k": list(range(300))}},
        ]
        for bad in bad_values:
            with self.subTest(bad=repr(bad)[:60]):
                root = self.fake_modules({"m": dict({"description": "x"}, **bad)})
                with self.assertRaises(install.InstallError) as ctx:
                    install.load_modules(root)
                self.assertIn("module m", str(ctx.exception))

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

    # -- hardening (plan: security review, Increment B) ------------------

    def outside_dir(self, name="outside"):
        path = os.path.join(self.work, name)
        os.makedirs(path)
        return path

    def test_add_refuses_symlinked_directory(self):
        self.new("")
        outside = self.outside_dir()
        os.symlink(outside, os.path.join(self.target(), ".claude"))
        code, out, err = run(["--add", "claude", "--dir", self.target()])
        self.assertEqual(code, 2)
        self.assertIn("symlink", err)
        self.assertEqual(os.listdir(outside), [])

    def test_add_refuses_symlinked_file_and_leaves_outside_untouched(self):
        self.new("")
        outside = self.outside_dir()
        victim = os.path.join(outside, "agents.md")
        with open(victim, "w") as handle:
            handle.write("mine\n<!-- @module-slot: agents-guidance -->\n")
        link = os.path.join(self.target(), "AGENTS.md")
        os.replace(link, link + ".orig")
        os.symlink(victim, link)
        code, out, err = run(["--add", "cad", "--dir", self.target()])
        self.assertEqual(code, 2)
        self.assertIn("symlink", err)
        with open(victim) as handle:
            self.assertEqual(handle.read(), "mine\n<!-- @module-slot: agents-guidance -->\n")

    def test_add_refuses_symlinked_manifest(self):
        self.new("")
        outside = self.outside_dir()
        victim = os.path.join(outside, "manifest")
        manifest = os.path.join(self.target(), ".template-manifest")
        os.replace(manifest, victim)
        os.symlink(victim, manifest)
        with open(victim) as handle:
            before = handle.read()
        code, out, err = run(["--add", "cad", "--dir", self.target()])
        self.assertEqual(code, 2)
        with open(victim) as handle:
            self.assertEqual(handle.read(), before)

    def test_add_refuses_symlinked_project_directory(self):
        self.new("")
        link = os.path.join(self.work, "link")
        os.symlink(self.target(), link)
        code, out, err = run(["--add", "cad", "--dir", link])
        self.assertEqual(code, 2)
        self.assertIn("symlink", err)

    def cli(self, argv, timeout=10):
        try:
            return subprocess.run(
                [sys.executable, "-I", os.path.join(ROOT, "install.py")] + argv,
                capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL,
            )
        except subprocess.TimeoutExpired:
            self.fail("installer hung on a special file")

    def test_add_refuses_special_files_without_hanging(self):
        self.new("")
        os.mkfifo(os.path.join(self.target(), "docs", "pipe"))
        result = self.cli(["--add", "cad", "--dir", self.target()])
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("regular", result.stderr)

    def test_module_source_special_file_is_refused_without_hanging(self):
        import threading
        root = self.fake_modules({"pipey": {"description": "x"}})
        os.makedirs(os.path.join(root, "pipey", "files"))
        os.mkfifo(os.path.join(root, "pipey", "files", "pipe"))
        result = []

        def attempt():
            try:
                install.assemble(["pipey"], install.load_modules(root))
                result.append(None)
            except install.InstallError as exc:
                result.append(exc)

        worker = threading.Thread(target=attempt, daemon=True)
        worker.start()
        worker.join(5)
        self.assertFalse(worker.is_alive(), "reading a module FIFO hung")
        self.assertIsInstance(result[0], install.InstallError)

    def test_module_files_may_not_target_git_metadata(self):
        for rel in (".git/hooks/pre-commit", ".GIT/config", "docs/.git/x", ".Git"):
            with self.subTest(path=rel):
                root = self.fake_modules({"evil": {"description": "x"}})
                full = os.path.join(root, "evil", "files", *rel.split("/"))
                os.makedirs(os.path.dirname(full), exist_ok=True)
                with open(full, "w") as handle:
                    handle.write("#!/bin/sh\necho pwn\n")
                code, out, err = self.new("evil", name="p")
                self.assertEqual(code, 2, out)
                self.assertIn("git metadata", err)
                self.assertFalse(os.path.exists(self.target("p")))
                code, out, err = self.new("", name="q")
                self.assertEqual(code, 0, err)
                before = read_tree(self.target("q"))
                code, out, err = run(["--add", "evil", "--dir", self.target("q")])
                self.assertEqual(code, 2)
                self.assertEqual(before, read_tree(self.target("q")))
                self.assertFalse(
                    os.path.exists(os.path.join(self.target("q"), ".git", "hooks", "pre-commit")))
                import shutil
                shutil.rmtree(self.target("q"))
                shutil.rmtree(root)

    def test_ambient_git_dir_does_not_redirect_writes(self):
        evil = os.path.join(self.work, "evil")
        subprocess.run(["git", "init", "-q", evil], check=True)
        os.environ["GIT_DIR"] = os.path.join(evil, ".git")
        try:
            code, out, err = self.new("")
        finally:
            os.environ.pop("GIT_DIR")
        self.assertEqual(code, 0, err)
        self.assertEqual(self.git("config", "--local", "--get", "user.email").stdout.strip(),
                         "tester@users.noreply.example.invalid")
        stray = subprocess.run(["git", "-C", evil, "config", "--local", "--get", "user.email"],
                               capture_output=True, text=True)
        self.assertNotEqual(stray.returncode, 0, stray.stdout)

    def append_global_config(self, text):
        with open(os.environ["GIT_CONFIG_GLOBAL"], "a") as handle:
            handle.write(text)

    def test_git_status_in_template_does_not_run_fsmonitor(self):
        marker = os.path.join(self.work, "fsmonitor-ran")
        script = os.path.join(self.work, "fsmon.sh")
        with open(script, "w") as handle:
            handle.write("#!/bin/sh\ntouch '%s'\nprintf '\\0'\n" % marker)
        os.chmod(script, 0o755)
        self.append_global_config("[core]\n\tfsmonitor = %s\n" % script)
        code, out, err = self.new("", extra=["--dry-run"])
        self.assertEqual(code, 0, err)
        self.assertFalse(os.path.exists(marker), "fsmonitor program was executed")

    def test_global_template_dir_hooks_are_not_copied(self):
        hooks = os.path.join(self.work, "tmpl", "hooks")
        os.makedirs(hooks)
        with open(os.path.join(hooks, "pre-commit"), "w") as handle:
            handle.write("#!/bin/sh\necho pwn\n")
        self.append_global_config("[init]\n\ttemplateDir = %s\n" % os.path.join(self.work, "tmpl"))
        code, out, err = self.new("")
        self.assertEqual(code, 0, err)
        self.assertFalse(os.path.exists(os.path.join(self.target(), ".git", "hooks", "pre-commit")))

    def test_malformed_manifests_are_clean_refusals(self):
        deep = "[" * 100000 + "]" * 100000
        cases = ("[]", "null", "5", '"x"', "", "{", '{"modules": null}', '{"modules": "claude"}',
                 '{"modules": {"claude": 1}}', '{"modules": [["a"]]}', '{"modules": [5]}',
                 '{"modules": ["Bad Name"]}', '{"modules": [], "schema": 99}',
                 '{"modules": []}', deep)
        for raw in cases:
            with self.subTest(manifest=raw[:40]):
                self.new("", name="m")
                path = os.path.join(self.target("m"), ".template-manifest")
                with open(path, "w") as handle:
                    handle.write(raw)
                before = read_tree(self.target("m"))
                code, out, err = run(["--add", "cad", "--dir", self.target("m")])
                self.assertEqual(code, 2, err)
                self.assertIn("error:", err)
                self.assertEqual(before, read_tree(self.target("m")))
                import shutil
                shutil.rmtree(self.target("m"))

    def test_case_variant_of_template_path_is_refused(self):
        variant = ROOT.swapcase()
        if not os.path.isdir(variant):
            self.skipTest("case-sensitive filesystem")
        # --dry-run: a regression must fail the test without littering the repo.
        code, out, err = run([os.path.join(variant, "inside-test"), "--dry-run"])
        self.assertEqual(code, 2, out)
        self.assertIn("inside the template", err)

    def test_control_characters_in_names_are_refused(self):
        for value in ("a\rb", "\x1b[31mred", "a\nb", "a\x00b"):
            with self.subTest(name=value):
                code, out, err = self.new("", name="p", extra=["--name=" + value])
                self.assertEqual(code, 2, out)
                self.assertFalse(os.path.exists(self.target("p")))
                code, out, err = run([self.target("p"), "--git-name=" + value, "--git-email",
                                      "t@users.noreply.example.invalid"])
                self.assertEqual(code, 2, out)
                self.assertFalse(os.path.exists(self.target("p")))
        code, out, err = run([self.target("p"), "--git-name", "T",
                              "--git-email", "t\x1b[0m@users.noreply.example.invalid"])
        self.assertEqual(code, 2)

    def test_add_name_override_refuses_control_characters(self):
        self.new("", name="q")
        before = read_tree(self.target("q"))
        code, out, err = run(["--add", "claude", "--dir", self.target("q"), "--name=a\x1b[1m"])
        self.assertEqual(code, 2)
        self.assertEqual(before, read_tree(self.target("q")))

    def test_case_colliding_and_reserved_module_files_are_refused(self):
        for rel in ("docs/README.MD", "agents.md", ".Template-Manifest", ".template-manifest"):
            with self.subTest(path=rel):
                root = self.fake_modules({"clash": {"description": "x"}})
                full = os.path.join(root, "clash", "files", *rel.split("/"))
                os.makedirs(os.path.dirname(full), exist_ok=True)
                with open(full, "w") as handle:
                    handle.write("x\n")
                code, out, err = self.new("clash", name="p")
                self.assertEqual(code, 2, out)
                self.assertFalse(os.path.exists(self.target("p")))
                import shutil
                shutil.rmtree(root)

    # -- second review round (plan Increment C) ----------------------------

    def test_add_does_not_write_through_a_hardlinked_file(self):
        self.new("")
        outside = self.outside_dir()
        victim = os.path.join(outside, "victim.md")
        link = os.path.join(self.target(), "AGENTS.md")
        with open(link) as handle:
            original = handle.read()
        os.replace(link, victim)
        os.link(victim, link)
        run(["--add", "cad", "--dir", self.target()])
        with open(victim) as handle:
            self.assertEqual(handle.read(), original)

    def test_add_does_not_write_through_a_hardlinked_manifest(self):
        self.new("")
        outside = self.outside_dir()
        victim = os.path.join(outside, "manifest")
        link = os.path.join(self.target(), ".template-manifest")
        os.replace(link, victim)
        os.link(victim, link)
        with open(victim) as handle:
            original = handle.read()
        run(["--add", "cad", "--dir", self.target()])
        with open(victim) as handle:
            self.assertEqual(handle.read(), original)

    @unittest.skipIf(hasattr(os, "geteuid") and os.geteuid() == 0, "root ignores file modes")
    def test_add_with_unwritable_file_is_a_clean_refusal_and_writes_nothing(self):
        self.new("")
        agents = os.path.join(self.target(), "AGENTS.md")
        os.chmod(agents, 0o444)
        self.addCleanup(os.chmod, agents, 0o644)
        before = read_tree(self.target())
        code, out, err = run(["--add", "cad", "--dir", self.target()])
        self.assertEqual(code, 2, out)
        self.assertIn("error:", err)
        self.assertEqual(before, read_tree(self.target()))

    def test_symlinks_in_module_trees_are_refused(self):
        outside = self.outside_dir()
        secret = os.path.join(outside, "secret.txt")
        with open(secret, "w") as handle:
            handle.write("TOPSECRET\n")
        cases = {}
        root = self.fake_modules({"a": {"description": "x"}, "b": {"description": "x"},
                                  "c": {"description": "x"}, "d": {"description": "x"}})
        os.makedirs(os.path.join(root, "a", "slots"))
        os.symlink(secret, os.path.join(root, "a", "slots", "gitignore.md"))
        os.symlink(outside, os.path.join(root, "b", "files"))
        os.symlink(outside, os.path.join(root, "c", "slots"))
        os.replace(os.path.join(root, "d", "module.json"), os.path.join(outside, "module.json"))
        os.symlink(os.path.join(outside, "module.json"), os.path.join(root, "d", "module.json"))
        for name in "abcd":
            with self.subTest(module=name):
                with self.assertRaises(install.InstallError):
                    modules = {}
                    full = os.path.join(root, name)
                    # load only this module so one refusal does not hide the others
                    only = os.path.join(self.work, "only-" + name)
                    os.makedirs(only)
                    os.symlink(full, os.path.join(only, name))
                    install.assemble([name], install.load_modules(only))
        # a symlinked module directory itself
        only = os.path.join(self.work, "only-dir")
        os.makedirs(only)
        os.symlink(outside, os.path.join(only, "linked"))
        with self.assertRaises(install.InstallError):
            install.load_modules(only)

    def test_template_reached_through_a_symlink_still_refuses_targets_inside(self):
        link = os.path.join(self.work, "tplink")
        os.symlink(ROOT, link)
        base_link = os.path.join(self.work, "lnkbase")
        os.symlink(os.path.join(ROOT, "base"), base_link)
        result = subprocess.run(
            [sys.executable, "-I", os.path.join(link, "install.py"),
             os.path.join(base_link, "newproj"), "--dry-run"],
            capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=20,
        )
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("inside the template", result.stderr)

    # -- --skip-unsafe-entries (plan Increment D) -------------------------

    SKIP = "--skip-unsafe-entries"

    def messy_project(self):
        """A project with entries --add normally refuses; returns the outside dir."""
        self.new("")
        project, outside = self.target(), self.outside_dir()
        secret = os.path.join(outside, "secret.txt")
        with open(secret, "w") as handle:
            handle.write("TOPSECRET\n")
        os.makedirs(os.path.join(project, ".venv", "bin"))
        os.symlink(secret, os.path.join(project, ".venv", "bin", "python"))
        os.symlink(outside, os.path.join(project, "shared"))
        os.symlink(secret, os.path.join(project, "notes-link.txt"))
        os.mkfifo(os.path.join(project, "pipe"))
        with open(os.path.join(project, "big.bin"), "wb") as handle:
            handle.truncate(install.MAX_FILE_BYTES + 1)
        return outside

    def test_skip_option_extends_a_project_with_unsafe_entries(self):
        outside = self.messy_project()
        code, out, err = run(["--add", "cad", "--dir", self.target()])
        self.assertEqual(code, 2, out)
        code, out, err = run(["--add", "cad", self.SKIP, "--dir", self.target()])
        self.assertEqual(code, 0, err)
        for name in (".venv/bin/python", "shared", "notes-link.txt", "pipe", "big.bin"):
            self.assertIn(name, out)
        self.assertIn("Skipped", out)
        self.assertTrue(os.path.exists(os.path.join(self.target(), "docs", "cad.md")))
        with open(os.path.join(self.target(), "AGENTS.md")) as handle:
            self.assertIn("BEGIN module:cad", handle.read())
        self.assertEqual(sorted(os.listdir(outside)), ["secret.txt"])
        with open(os.path.join(outside, "secret.txt")) as handle:
            self.assertEqual(handle.read(), "TOPSECRET\n")

    def test_skip_option_still_refuses_a_symlinked_file_that_needs_patching(self):
        self.new("")
        outside = self.outside_dir()
        victim = os.path.join(outside, "agents.md")
        with open(victim, "w") as handle:
            handle.write("mine\n<!-- @module-slot: agents-guidance -->\n")
        link = os.path.join(self.target(), "AGENTS.md")
        os.replace(link, os.path.join(outside, "AGENTS.orig"))  # keep the marker out of the project
        os.symlink(victim, link)
        code, out, err = run(["--add", "cad", self.SKIP, "--dir", self.target()])
        self.assertEqual(code, 2)
        self.assertIn("no matching slot marker", err)
        with open(victim) as handle:
            self.assertEqual(handle.read(), "mine\n<!-- @module-slot: agents-guidance -->\n")
        self.assertFalse(os.path.exists(os.path.join(self.target(), "docs", "cad.md")))

    def test_skip_option_still_refuses_writes_through_symlinks(self):
        self.new("")
        outside = self.outside_dir()
        os.symlink(outside, os.path.join(self.target(), ".claude"))
        code, out, err = run(["--add", "claude", self.SKIP, "--dir", self.target()])
        self.assertEqual(code, 2)
        self.assertEqual(os.listdir(outside), [])
        self.new("", name="q")
        os.makedirs(os.path.join(self.target("q"), "docs"), exist_ok=True)
        existing = os.path.join(self.target("q"), "docs", "cad.md")
        victim = os.path.join(outside, "cad.md")
        with open(victim, "w") as handle:
            handle.write("outside\n")
        os.symlink(victim, existing)
        code, out, err = run(["--add", "cad", self.SKIP, "--dir", self.target("q")])
        self.assertEqual(code, 2)
        with open(victim) as handle:
            self.assertEqual(handle.read(), "outside\n")

    def test_skip_option_does_not_relax_project_or_manifest_checks(self):
        self.new("")
        link = os.path.join(self.work, "link")
        os.symlink(self.target(), link)
        code, out, err = run(["--add", "cad", self.SKIP, "--dir", link])
        self.assertEqual(code, 2)
        self.new("", name="m")
        with open(os.path.join(self.target("m"), ".template-manifest"), "w") as handle:
            handle.write("[]")
        code, out, err = run(["--add", "cad", self.SKIP, "--dir", self.target("m")])
        self.assertEqual(code, 2)

    def test_skip_option_is_rejected_for_a_new_project(self):
        code, out, err = self.new("", extra=[self.SKIP])
        self.assertEqual(code, 2)
        self.assertIn("--add", err)
        self.assertFalse(os.path.exists(self.target()))

    # -- plan-review module (plan 0004, Increment A) ----------------------

    def test_empty_plan_heading_is_a_placeholder_not_a_shared_title(self):
        code, out, err = self.new()
        self.assertEqual(code, 0, err)
        tree = read_tree(self.target())
        self.assertEqual(tree["docs/plans/next.md"].splitlines()[0],
                         "# REPLACE_WITH_PLAN_TITLE")
        readme = tree["docs/plans/README.md"]
        self.assertIn("unique title", readme)
        self.assertIn("# NNNN: Plan title", readme)

    def test_plan_review_inserts_policy_receipt_and_archive_note(self):
        code, out, err = self.new("plan-review")
        self.assertEqual(code, 0, err)
        tree = read_tree(self.target())
        agents = tree["AGENTS.md"]
        self.assertIn("BEGIN module:plan-review slot:agents-guidance", agents)
        for phrase in ("only when the owner asks", "read-only", "untrusted",
                       "leave the machine", "does not replace the owner's approval"):
            self.assertIn(phrase, agents)
        plan = tree["docs/plans/next.md"]
        self.assertIn("BEGIN module:plan-review slot:plan-review", plan)
        self.assertIn("## Second opinion", plan)
        self.assertLess(plan.index("## Second opinion"), plan.index("## Deferred work"))
        self.assertIn("BEGIN module:plan-review slot:plans-review-note",
                      tree["docs/plans/README.md"])
        self.assertIn("plan-review: ", out)

    def test_plan_review_guidance_covers_specs_and_roadmaps(self):
        self.new("plan-review")
        agents = read_tree(self.target())["AGENTS.md"]
        for phrase in ("docs/specs/", "docs/roadmaps/", "at any status",
                       "does not change the document's status", "only edit the document under review",
                       "fresh review"):
            self.assertIn(phrase, agents)
        self.assertNotIn("ask-codex", agents)

    def test_codex_guidance_names_the_spec_and_roadmap_commands(self):
        self.new("codex")
        agents = read_tree(self.target())["AGENTS.md"]
        for phrase in ("ask-codex review-spec --spec", "ask-codex review-roadmap --roadmap",
                       "`--spec`", "`--roadmap`", "docs/specs/", "docs/roadmaps/",
                       "never run `archive` to get around a bound"):
            self.assertIn(phrase, agents)

    def test_plan_review_text_absent_without_the_module(self):
        self.new("graphify,cad")
        tree = read_tree(self.target())
        for path in ("AGENTS.md", "docs/plans/next.md", "docs/plans/README.md"):
            self.assertNotIn("plan-review", tree[path].replace("@module-slot: plan-review", ""))
        self.assertNotIn("Second opinion", tree["docs/plans/next.md"])
        self.assertIn("@module-slot: plan-review", tree["docs/plans/next.md"])
        self.assertIn("@module-slot: plans-review-note", tree["docs/plans/README.md"])

    def test_add_plan_review_matches_fresh_install(self):
        self.new("graphify")
        code, out, err = run(["--add", "plan-review", "--dir", self.target()])
        self.assertEqual(code, 0, err)
        self.new("graphify,plan-review", name="fresh", extra=["--name", "demo"])
        added, fresh = read_tree(self.target()), read_tree(self.target("fresh"))
        added.pop(".template-manifest"), fresh.pop(".template-manifest")
        self.assertEqual(added.keys(), fresh.keys())
        for path in fresh:
            self.assertEqual(added[path], fresh[path], path)

    # -- codex module (plan 0005, Increment A) ----------------------------

    def test_codex_pulls_plan_review_and_inserts_guidance(self):
        code, out, err = self.new("codex")
        self.assertEqual(code, 0, err)
        self.assertIn("Modules: plan-review, codex", out)
        self.assertIn("Required modules added: plan-review", out)
        tree = read_tree(self.target())
        agents = tree["AGENTS.md"]
        self.assertIn("BEGIN module:plan-review slot:agents-guidance", agents)
        self.assertIn("BEGIN module:codex slot:agents-guidance", agents)
        for phrase in ("have Codex review the plan", "/second-opinion", "ask-codex review-plan",
                       "3 rounds by default", "never more than 5", "applied or rejected",
                       "extend", "reset", "archive", "prune", "untracked", "OpenAI"):
            self.assertIn(phrase, agents)
        plan = tree["docs/plans/next.md"]
        self.assertIn("BEGIN module:codex slot:plan-review", plan)
        self.assertIn("ask-codex archive", plan)
        self.assertLess(plan.index("module:plan-review slot:plan-review"),
                        plan.index("module:codex slot:plan-review"))
        self.assertEqual(out.count("  codex: "), 1)
        self.assertEqual(out.count("  plan-review: "), 1)

    def test_codex_text_absent_without_the_module(self):
        self.new("plan-review")
        for path, text in read_tree(self.target()).items():
            self.assertNotIn("ask-codex", text, path)
            self.assertNotIn("module:codex", text, path)

    def test_add_codex_matches_fresh_install(self):
        self.new("plan-review")
        code, out, err = run(["--add", "codex", "--dir", self.target()])
        self.assertEqual(code, 0, err)
        self.new("codex", name="fresh", extra=["--name", "demo"])
        added, fresh = read_tree(self.target()), read_tree(self.target("fresh"))
        added.pop(".template-manifest"), fresh.pop(".template-manifest")
        self.assertEqual(added.keys(), fresh.keys())
        for path in fresh:
            self.assertEqual(added[path], fresh[path], path)

    def test_codex_is_a_harness_module_and_listed_that_way(self):
        self.assertTrue(install.load_modules()["codex"]["harness"])
        code, out, err = run(["--list"])
        self.assertIn("codex (harness; requires plan-review)", out)

    def test_interrupt_is_a_quiet_exit(self):
        def interrupted(args, out):
            raise KeyboardInterrupt
        original = install.cmd_new
        install.cmd_new = interrupted
        self.addCleanup(setattr, install, "cmd_new", original)
        code, out, err = run([self.target()])
        self.assertEqual(code, 130)
        self.assertIn("interrupted", err)

    def test_list(self):
        code, out, err = run(["--list"])
        self.assertEqual(code, 0)
        self.assertIn("cad-freecad (requires cad)", out)
        self.assertIn("claude (harness)", out)


@unittest.skipUnless(os.name == "posix", "pseudo-terminal tests need POSIX")
class InteractivePromptTest(unittest.TestCase):
    EMAIL = "typed@users.noreply.example.invalid"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.work = self.tmp.name
        gitconfig = os.path.join(self.work, "global.gitconfig")
        with open(gitconfig, "w") as handle:
            handle.write("[user]\n\tname = Sentinel Global\n\temail = %s\n" % SENTINEL_EMAIL)
        self.env = dict(os.environ, HOME=self.work, GIT_CONFIG_GLOBAL=gitconfig,
                        GIT_CONFIG_SYSTEM=os.devnull,
                        XDG_CONFIG_HOME=os.path.join(self.work, "xdg"))

    def run_install(self, argv, keystrokes):
        return run_pty(argv, keystrokes, self.work, self.env)

    def local_config(self, name):
        return subprocess.run(
            ["git", "config", "--local", "--get", name],
            cwd=os.path.join(self.work, "demo"), env=self.env, text=True, capture_output=True,
        ).stdout.strip()

    def test_module_and_identity_prompts_complete(self):
        code, out = self.run_install(["demo"], "cad\nTyped User\n%s\n" % self.EMAIL)
        self.assertEqual(code, 0, out)
        self.assertIn("Modules: cad", out)
        self.assertEqual(self.local_config("user.name"), "Typed User")
        self.assertEqual(self.local_config("user.email"), self.EMAIL)
        self.assertNotIn(SENTINEL_EMAIL, out)

    def test_blank_module_answer_means_no_modules(self):
        code, out = self.run_install(["demo"], "\nTyped User\n%s\n" % self.EMAIL)
        self.assertEqual(code, 0, out)
        self.assertIn("Modules: none", out)

    def test_unknown_module_answer_is_refused_before_identity_prompt(self):
        code, out = self.run_install(["demo"], "nosuch\n")
        self.assertEqual(code, 2, out)
        self.assertIn("unknown module", out)
        self.assertNotIn("Git user.name", out)
        self.assertFalse(os.path.exists(os.path.join(self.work, "demo")))

    def test_invalid_identity_is_refused_and_nothing_written(self):
        code, out = self.run_install(["demo", "--with", "cad"], "\nnot-an-email\n")
        self.assertEqual(code, 2, out)
        self.assertIn("error:", out)
        self.assertFalse(os.path.exists(os.path.join(self.work, "demo")))

    def test_end_of_input_at_each_prompt_is_a_clean_refusal(self):
        cases = (
            ("module prompt", ["demo"], "\x04"),
            ("name prompt", ["demo", "--with", "cad"], "\x04"),
            ("email prompt", ["demo", "--with", "cad"], "Typed User\n\x04"),
        )
        for label, argv, keys in cases:
            with self.subTest(prompt=label):
                code, out = self.run_install(argv, keys)
                self.assertEqual(code, 2, out)
                self.assertNotIn("Traceback", out)
                self.assertIn("input ended", out)
                self.assertFalse(os.path.exists(os.path.join(self.work, "demo")))

    def test_bad_target_is_refused_before_any_prompt(self):
        inside = os.path.join(ROOT, "refused-target")
        code, out = self.run_install([inside], "cad\n")
        self.assertEqual(code, 2, out)
        self.assertIn("inside the template repository", out)
        self.assertNotIn("Modules (", out)
        self.assertFalse(os.path.exists(inside))

    def test_unusable_project_id_is_refused_before_identity_prompt(self):
        code, out = self.run_install(["demo", "--with", "claude", "--name=---"], "")
        self.assertEqual(code, 2, out)
        self.assertIn("project id", out)
        self.assertNotIn("Git user.name", out)
        self.assertFalse(os.path.exists(os.path.join(self.work, "demo")))


FIXTURE_MODULE = b'{"module_format": 1, "description": "Fixture store"}\n'
FIXTURE_SLOT = b"## Fixture guidance\n\nRead REPLACE_WITH_MODULE_PATH/router.md.\n"
# Computed independently of install.py with the spec's digest algorithm.
FIXTURE_DIGEST = "cf9d227a545469fbe589ff4e65d3a4b4878bd32bd1a3f14341acee82fe7da26d"


def tree_hash(root):
    """Digest of every file under root, dotfiles and .git included."""
    import hashlib
    digest = hashlib.sha256()
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames.sort()
        for filename in sorted(filenames):
            full = os.path.join(dirpath, filename)
            digest.update(os.path.relpath(full, root).encode() + b"\0")
            if os.path.isfile(full):
                with open(full, "rb") as handle:
                    digest.update(handle.read())
            else:
                digest.update(b"special")
    return digest.hexdigest()


def make_store(parent, name="my_kb", slots=None, module=FIXTURE_MODULE):
    """Write a valid external-module descriptor and return the store path."""
    store = os.path.join(parent, name)
    slot_dir = os.path.join(store, "template-module", "slots")
    os.makedirs(slot_dir)
    if module is not None:
        with open(os.path.join(store, "template-module", "module.json"), "wb") as handle:
            handle.write(module)
    for slot, data in (slots if slots is not None else {"agents-guidance": FIXTURE_SLOT}).items():
        with open(os.path.join(slot_dir, slot + ".md"), "wb") as handle:
            handle.write(data)
    return store


class ExternalModuleTest(unittest.TestCase):
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
        os.environ["XDG_CONFIG_HOME"] = os.path.join(self.work, "xdg")
        self.addCleanup(self._restore_env)
        self.builtin = set(install.load_modules())

    def _restore_env(self):
        os.environ.clear()
        os.environ.update(self.saved)

    def target(self, name="proj"):
        return os.path.join(self.work, name)

    def store(self, **kwargs):
        return make_store(self.work, **kwargs)

    def load(self, value, name="kb", target=None):
        return install.load_external(name, value, target or self.target(), self.builtin)

    def new(self, with_, name="proj", extra=None):
        argv = [self.target(name), "--with", with_,
                "--git-name", "Test User", "--git-email", "tester@users.noreply.example.invalid"]
        return run(argv + (extra or []))

    def manifest(self, name="proj"):
        with open(os.path.join(self.target(name), ".template-manifest")) as handle:
            return json.load(handle)

    def write_manifest(self, data, name="proj"):
        with open(os.path.join(self.target(name), ".template-manifest"), "w") as handle:
            json.dump(data, handle)

    # -- parsing and digest -------------------------------------------

    def test_parse_entries(self):
        self.assertEqual(
            install.parse_entries(["claude", "kb=~/x", "a=b=c"]),
            [("claude", None), ("kb", "~/x"), ("a", "b=c")],
        )
        for bad in ("=x", "kb="):
            with self.subTest(bad=bad):
                with self.assertRaises(install.InstallError):
                    install.parse_entries([bad])

    def test_digest_matches_pinned_literal(self):
        self.assertEqual(self.load(self.store())["digest"], FIXTURE_DIGEST)
        other = make_store(self.work, name="other", slots={"agents-guidance": FIXTURE_SLOT + b"x"})
        self.assertNotEqual(self.load(other)["digest"], FIXTURE_DIGEST)

    def test_digest_orders_fragments_by_slot_name_not_file_name(self):
        # Slots "a" and "a-b" sort the other way round by file name ("a-b.md" < "a.md").
        store = self.store(slots={"a": b"A\n", "a-b": b"B\n"})
        self.assertEqual(
            self.load(store)["digest"],
            "c38f3b1542d3cccda110afc639646990ed4b6fa1332da7a5e9783dac94f99964",
        )

    # -- loading and verification -------------------------------------

    def test_load_external_valid(self):
        meta = self.load(self.store())
        self.assertEqual(meta["description"], "Fixture store")
        self.assertEqual(meta["module_format"], 1)
        self.assertTrue(meta["external"])
        self.assertEqual(meta["requires"], [])
        self.assertEqual(meta["order"], install.EXTERNAL_ORDER)
        fragment = meta["slots"]["agents-guidance"]
        self.assertIn("Read ../my_kb/router.md.", fragment)
        self.assertNotIn("REPLACE_WITH_MODULE", fragment)

    def test_load_external_absolute_path_when_parents_differ(self):
        elsewhere = os.path.join(self.work, "elsewhere")
        os.makedirs(elsewhere)
        store = make_store(elsewhere)
        fragment = self.load(store)["slots"]["agents-guidance"]
        self.assertIn("Read %s/router.md." % os.path.realpath(store), fragment)

    def test_module_name_placeholder_substituted(self):
        store = self.store(slots={"agents-guidance": b"name is REPLACE_WITH_MODULE_NAME\n"})
        self.assertIn("name is kb", self.load(store)["slots"]["agents-guidance"])

    def test_tilde_is_expanded(self):
        store = self.store()
        os.environ["HOME"] = self.work
        self.assertEqual(self.load("~/my_kb")["path"], os.path.realpath(store))

    def test_symlinked_ancestor_is_accepted(self):
        real = os.path.join(self.work, "real")
        os.makedirs(real)
        store = make_store(real)
        link = os.path.join(self.work, "link")
        os.symlink(real, link)
        self.assertEqual(self.load(os.path.join(link, "my_kb"))["path"], os.path.realpath(store))

    def assertRefused(self, value, name="kb", target=None, fragment=None):
        with self.assertRaises(install.InstallError) as ctx:
            self.load(value, name=name, target=target)
        if fragment:
            self.assertIn(fragment, str(ctx.exception))
        return str(ctx.exception)

    def test_refuses_bad_stores(self):
        def module(data):
            return lambda: self.store(module=data)

        def slot(data, name="agents-guidance"):
            return lambda: self.store(slots={name: data})

        def mutate(fn):
            def build():
                store = self.store()
                fn(store)
                return store
            return build

        tdir = lambda store: os.path.join(store, "template-module")

        def link_module(store):
            path = os.path.join(tdir(store), "module.json")
            os.rename(path, path + ".real")
            os.symlink(path + ".real", path)

        def link_slot(store):
            path = os.path.join(tdir(store), "slots", "agents-guidance.md")
            os.rename(path, os.path.join(tdir(store), "real.md"))
            os.symlink(os.path.join(tdir(store), "real.md"), path)

        cases = {
            "no descriptor": lambda: os.makedirs(os.path.join(self.work, "bare")) or os.path.join(self.work, "bare"),
            "missing": lambda: os.path.join(self.work, "nope"),
            "module.json symlink": mutate(link_module),
            "slot symlink": mutate(link_slot),
            "slot fifo": mutate(lambda s: os.mkfifo(os.path.join(tdir(s), "slots", "fifo.md"))),
            "unexpected slots entry": mutate(
                lambda s: open(os.path.join(tdir(s), "slots", "README.txt"), "w").close()),
            "bad slot name": slot(b"x\n", name="Bad_Slot"),
            "module.json not an object": module(b"[]"),
            "module.json not json": module(b"{"),
            "unknown key": module(b'{"module_format": 1, "description": "d", "order": 3}'),
            "mistyped description": module(b'{"module_format": 1, "description": 5}'),
            "bool format": module(b'{"module_format": true, "description": "d"}'),
            "unknown format": module(b'{"module_format": 3, "description": "d"}'),
            "empty description": module(b'{"module_format": 1, "description": ""}'),
            "long description": module(json.dumps(
                {"module_format": 1, "description": "d" * 201}).encode()),
            "multiline description": module(b'{"module_format": 1, "description": "a\\nb"}'),
            "long hint": module(json.dumps(
                {"module_format": 1, "description": "d", "hint": "h" * 201}).encode()),
            "null hint": module(b'{"module_format": 1, "description": "d", "hint": null}'),
            "non-utf8 fragment": slot(b"\xff\xfe\n"),
            "nul fragment": slot(b"a\0b\n"),
            "oversized fragment": slot(b"a" * (64 * 1024 + 1)),
            "slot marker in fragment": slot(b"x <!-- @module-slot: agents-guidance -->\n"),
            "begin line in fragment": slot(b"<!-- BEGIN module:x slot:y -->\n"),
            "end line in fragment": slot(b"text END module:x slot:y\n"),
        }
        import shutil
        for label, build in cases.items():
            with self.subTest(case=label):
                for leftover in ("my_kb", "bare"):
                    shutil.rmtree(os.path.join(self.work, leftover), ignore_errors=True)
                self.assertRefused(build())

    def test_refuses_seventeen_fragments(self):
        slots = {"s%02d" % i: b"x\n" for i in range(17)}
        self.assertRefused(self.store(slots=slots))

    def test_unknown_format_message_names_both_versions(self):
        store = self.store(module=b'{"module_format": 7, "description": "d"}')
        message = self.assertRefused(store)
        self.assertIn("7", message)
        self.assertIn("supports 1, 2", message)

    def test_format_two_declares_type_paths_and_data(self):
        store = self.store(module=json.dumps({
            "module_format": 2, "description": "d", "type": "knowledge-base",
            "paths": {"index": "docs/kb/index.md"}, "data": {"kinds": ["note"]},
        }).encode())
        meta = self.load(store)
        self.assertEqual(meta["module_format"], 2)
        self.assertEqual(meta["type"], "knowledge-base")
        self.assertEqual(meta["paths"], {"index": "docs/kb/index.md"})
        self.assertEqual(meta["data"], {"kinds": ["note"]})

    def test_format_two_without_info_keys_loads(self):
        meta = self.load(self.store(module=b'{"module_format": 2, "description": "d"}'))
        self.assertEqual(meta["module_format"], 2)
        for key in install.INFO_KEYS:
            self.assertNotIn(key, meta)

    def test_format_one_still_refuses_info_keys(self):
        for key, value in (("type", "x"), ("paths", {}), ("data", {})):
            with self.subTest(key=key):
                shutil.rmtree(os.path.join(self.work, "my_kb"), ignore_errors=True)
                store = self.store(module=json.dumps(
                    {"module_format": 1, "description": "d", key: value}).encode())
                self.assertRefused(store)

    def test_format_two_refuses_invalid_info(self):
        cases = {
            "uppercase type": {"type": "KB"},
            "long type": {"type": "a" * 65},
            "non-object paths": {"paths": ["docs"]},
            "absolute path": {"paths": {"store": "/etc"}},
            "traversal path": {"paths": {"store": "../x"}},
            "backslash path": {"paths": {"store": "a\\b"}},
            "non-object data": {"data": [1]},
            "deep data": {"data": {"a": {"b": {"c": {"d": {"e": 1}}}}}},
            "long data string": {"data": {"a": "x" * 201}},
            "unknown key": {"order": 3},
        }
        for label, extra in cases.items():
            with self.subTest(case=label):
                shutil.rmtree(os.path.join(self.work, "my_kb"), ignore_errors=True)
                meta = {"module_format": 2, "description": "d"}
                meta.update(extra)
                message = self.assertRefused(self.store(module=json.dumps(meta).encode()))
                self.assertIn("kb", message)

    def test_format_three_reports_the_format_even_with_info_keys(self):
        store = self.store(module=json.dumps(
            {"module_format": 3, "description": "d", "type": "kb"}).encode())
        message = self.assertRefused(store)
        self.assertIn("module_format 3", message)
        self.assertNotIn("unknown module.json keys", message)

    def test_refusal_does_not_echo_content(self):
        store = self.store(module=b'{"module_format": 1, "description": "d", "SECRETVALUE": 1}')
        self.assertNotIn("SECRETVALUE", self.assertRefused(store))

    def test_refuses_bad_names(self):
        store = self.store()
        self.assertRefused(store, name="cad")
        self.assertRefused(store, name="Bad")
        self.assertRefused(store, name="-x")
        self.assertRefused(store, name="kb\n")

    def test_refuses_template_and_target_containment(self):
        store = self.store()
        self.assertRefused(os.path.join(install.ROOT, "modules"), fragment="template")
        self.assertRefused(install.ROOT, fragment="template")
        self.assertRefused(store, target=store, fragment="target")
        self.assertRefused(store, target=self.work, fragment="target")

    def test_containment_uses_real_paths_in_both_directions(self):
        store = self.store()
        link = os.path.join(self.work, "into-template")
        os.symlink(os.path.join(install.ROOT, "modules"), link)
        self.assertRefused(os.path.join(link, "x"), fragment="template")
        self.assertRefused(os.path.dirname(install.ROOT), fragment="template")
        self.assertRefused(store, target=os.path.join(store, "inner"), fragment="target")
        self.assertRefused(os.path.dirname(store), target=store, fragment="target")

    def test_target_case_variant_is_refused(self):
        store = self.store()
        variant = self.work.swapcase()
        if not os.path.exists(variant):
            self.skipTest("case-sensitive filesystem")
        self.assertRefused(store, target=variant, fragment="target")

    def test_unreadable_store_directory_is_an_install_error(self):
        if os.geteuid() == 0:
            self.skipTest("permissions are not enforced for root")
        store = self.store()
        slots = os.path.join(store, "template-module", "slots")
        os.chmod(slots, 0)
        self.addCleanup(os.chmod, slots, 0o755)
        self.assertRefused(store)

    def test_comma_in_store_path_fails_in_with_and_works_in_add(self):
        store = self.store(name="a,b")
        code, out, err = self.new("kb=" + store)
        self.assertEqual(code, 2)
        self.assertFalse(os.path.exists(self.target()))
        self.assertEqual(self.new("graphify")[0], 0)
        self.assertEqual(self.add("kb=" + store)[0], 0)

    # -- trust-model review findings (plan 0008) ----------------------

    def test_placeholder_cannot_complete_a_reserved_marker(self):
        store = self.store(slots={"agents-guidance": b"<!-- @module-slREPLACE_WITH_MODULE_NAME: x -->\n"})
        self.assertRefused(store, name="ot", fragment="reserved marker")
        store = self.store(
            name="other", slots={"agents-guidance": b"<!-- BEGIN modREPLACE_WITH_MODULE_NAME:x -->\n"}
        )
        self.assertRefused(store, name="ule", fragment="reserved marker")

    def alias_of(self, store):
        alias = os.path.join(os.path.dirname(store), os.path.basename(store).upper())
        if not (os.path.exists(alias) and os.path.samefile(alias, store)):
            self.skipTest("filesystem is case sensitive")
        return alias

    def test_same_store_under_a_case_alias_is_one_store(self):
        store = self.store()
        alias = self.alias_of(store)
        with self.assertRaises(install.InstallError) as ctx:
            install.load_externals([("n1", store), ("n2", alias)], self.target(), self.builtin)
        self.assertIn("name the same store", str(ctx.exception))

    def test_non_printable_real_path_is_refused(self):
        hostile = os.path.join(self.work, "evil\x1b[2Jdir")
        os.mkdir(hostile)
        make_store(hostile)
        link = os.path.join(self.work, "lk")
        os.symlink(hostile, link)
        message = self.assertRefused(os.path.join(link, "my_kb"), fragment="printable")
        self.assertNotIn("\x1b", message)

    def test_dotdot_through_a_symlink_resolves_physically(self):
        os.makedirs(os.path.join(self.work, "a", "b"))
        good = make_store(os.path.join(self.work, "a"), name="good")
        make_store(self.work, name="good", slots={"agents-guidance": b"WRONG STORE\n"})
        link = os.path.join(self.work, "lnk")
        os.symlink(os.path.join(self.work, "a", "b"), link)
        meta = self.load(os.path.join(link, "..", "good"))
        self.assertEqual(meta["path"], os.path.realpath(good))
        self.assertNotIn("WRONG STORE", meta["slots"]["agents-guidance"])

    def test_name_pattern_rejects_a_trailing_newline(self):
        store = self.store(slots={"agents-guidance\n": b"x\n"})
        self.assertRefused(store, fragment="unexpected entry")
        self.new("graphify")
        self.write_manifest({"schema": 1, "modules": ["claude\n"]})
        code, out, err = run(["--add", "graphify", "--dir", self.target()])
        self.assertEqual(code, 2)
        self.assertIn("malformed", err)

    def test_unsupported_format_message_does_not_echo_a_huge_number(self):
        digits = "9" * 4000
        store = self.store(module=('{"module_format": %s, "description": "d"}' % digits).encode())
        message = self.assertRefused(store, fragment="module_format")
        self.assertNotIn("9999999999", message)

    def test_fragment_count_is_checked_before_reading_fragments(self):
        store = self.store(slots={"s%d" % n: b"x\n" for n in range(install.FRAGMENT_MAX_COUNT + 1)})
        real, reads = install.read_regular, []

        def spy(path, *args):
            reads.append(path)
            return real(path, *args)

        install.read_regular = spy
        self.addCleanup(setattr, install, "read_regular", real)
        self.assertRefused(store, fragment="more than")
        self.assertEqual([p for p in reads if os.sep + "slots" + os.sep in p], [])

    def test_refuses_symlinked_store(self):
        store = self.store()
        link = os.path.join(self.work, "linked")
        os.symlink(store, link)
        self.assertRefused(link)

    def test_dot_names_the_current_directory(self):
        store = self.store()
        cwd = os.getcwd()
        self.addCleanup(os.chdir, cwd)
        os.chdir(store)
        for value in (".", "./", "./."):
            with self.subTest(value=value):
                self.assertEqual(self.load(value)["path"], os.path.realpath(store))

    def test_refuses_symlinked_store_with_trailing_dot_components(self):
        store = self.store()
        link = os.path.join(self.work, "linked")
        os.symlink(store, link)
        for suffix in ("/", "/.", "/./.", "//./"):
            with self.subTest(suffix=suffix):
                self.assertRefused(link + suffix, fragment="symlink")

    def test_refuses_git_component_in_store_path(self):
        hidden = os.path.join(self.work, ".git")
        os.makedirs(hidden)
        self.assertRefused(make_store(hidden))

    # -- new project --------------------------------------------------

    def test_with_name_path_installs_fragment(self):
        store = self.store(module=b'{"module_format": 1, "description": "Fixture store",'
                                  b' "hint": "register me"}\n')
        code, out, err = self.new("graphify,kb=" + store)
        self.assertEqual(code, 0, err)
        agents = read_tree(self.target())["AGENTS.md"]
        begin = "<!-- BEGIN module:kb slot:agents-guidance -->"
        self.assertIn(begin, agents)
        self.assertIn("<!-- END module:kb slot:agents-guidance -->", agents)
        self.assertIn("Read ../my_kb/router.md.", agents)
        self.assertLess(agents.index("BEGIN module:graphify slot:agents-guidance"),
                        agents.index(begin))
        self.assertIn("kb: register me", out)
        self.assertIn("@module-slot: agents-guidance", agents)

    def test_fragment_without_trailing_newline_or_with_crlf(self):
        store = self.store(slots={"agents-guidance": b"line one\r\nlast line"})
        code, out, err = self.new("kb=" + store)
        self.assertEqual(code, 0, err)
        lines = read_tree(self.target())["AGENTS.md"].split("\n")
        self.assertIn("<!-- END module:kb slot:agents-guidance -->", lines)

    def test_two_external_modules_make_two_blocks(self):
        one, two = self.store(name="one"), self.store(name="two")
        code, out, err = self.new("a=%s,b=%s" % (one, two))
        self.assertEqual(code, 0, err)
        agents = read_tree(self.target())["AGENTS.md"]
        self.assertIn("BEGIN module:a slot:agents-guidance", agents)
        self.assertIn("BEGIN module:b slot:agents-guidance", agents)
        self.assertLess(agents.index("module:a slot"), agents.index("module:b slot"))

    def test_manifest_records_external(self):
        store = self.store()
        self.assertEqual(self.new("graphify,kb=" + store)[0], 0)
        manifest = self.manifest()
        self.assertEqual(manifest["modules"], ["graphify"])
        self.assertEqual(manifest["external_modules"],
                         {"kb": {"module_format": 1, "digest": FIXTURE_DIGEST}})
        # The store location lives only in module_info, never in the digest record.
        self.assertNotIn(os.path.basename(store), json.dumps(manifest["external_modules"]))
        self.assertEqual(manifest["module_info"], {"kb": {"store": "../my_kb"}})

    def test_builtin_only_manifest_has_no_external_key(self):
        self.assertEqual(self.new("graphify")[0], 0)
        self.assertNotIn("external_modules", self.manifest())

    def test_dry_run_with_external_writes_nothing(self):
        store = self.store(module=b'{"module_format": 1, "description": "d", "hint": "h1"}')
        before = tree_hash(store)
        code, out, err = self.new("kb=" + store, extra=["--dry-run"])
        self.assertEqual(code, 0, err)
        self.assertFalse(os.path.exists(self.target()))
        self.assertIn("would write AGENTS.md", out)
        self.assertIn("kb: h1", out)
        self.assertEqual(tree_hash(store), before)

    def test_new_project_refusals_write_nothing(self):
        one = self.store(name="one")
        cases = {
            "duplicate name": "kb=%s,kb=%s" % (one, self.store(name="two")),
            "same real path twice": "a=%s,b=%s" % (one, one),
            "slot without marker": "kb=" + self.store(
                name="orphan", slots={"no-such-slot": b"x\n"}),
            "unknown bare name": "no_such_module",
            "builtin name": "cad=" + one,
        }
        for label, with_ in cases.items():
            with self.subTest(case=label):
                code, out, err = self.new(with_)
                self.assertEqual(code, 2, out)
                self.assertFalse(os.path.exists(self.target()))

    def test_store_files_dir_is_never_copied(self):
        store = self.store()
        for rel in ("files/top.txt", "template-module/files/inner.txt"):
            path = os.path.join(store, *rel.split("/"))
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w") as handle:
                handle.write("x")
        self.assertEqual(self.new("kb=" + store)[0], 0)
        tree = read_tree(self.target())
        self.assertNotIn("top.txt", " ".join(tree))
        self.assertNotIn("inner.txt", " ".join(tree))

    def test_hostile_store_runs_nothing(self):
        store = self.store()
        marker = os.path.join(self.work, "ran")
        script = os.path.join(self.work, "helper.sh")
        with open(script, "w") as handle:
            handle.write("#!/bin/sh\ntouch %s\n" % marker)
        os.chmod(script, 0o755)
        os.makedirs(os.path.join(store, ".git"))
        with open(os.path.join(store, ".git", "config"), "w") as handle:
            handle.write("[core]\n\tfsmonitor = %s\n\thooksPath = %s\n" % (script, self.work))
        os.environ["GIT_DIR"] = os.path.join(store, ".git")
        os.environ["GIT_WORK_TREE"] = store
        before = tree_hash(store)
        from unittest import mock
        with mock.patch.object(install.subprocess, "run", wraps=install.subprocess.run) as spy:
            self.assertEqual(self.new("kb=" + store)[0], 0)
        self.assertFalse(os.path.exists(marker))
        self.assertEqual(tree_hash(store), before)
        real_store = os.path.realpath(store)
        for call in spy.call_args_list:
            self.assertNotIn(real_store, str(call))
            self.assertNotIn(store, str(call))

    # -- --add --------------------------------------------------------

    def add(self, *entries, name="proj", extra=None):
        return run(["--add"] + list(entries) + ["--dir", self.target(name)] + (extra or []))

    def test_add_name_path_to_existing_project(self):
        self.assertEqual(self.new("graphify")[0], 0)
        before = read_tree(self.target())["README.md"]
        code, out, err = self.add("kb=" + self.store())
        self.assertEqual(code, 0, err)
        tree = read_tree(self.target())
        self.assertIn("BEGIN module:kb slot:agents-guidance", tree["AGENTS.md"])
        self.assertEqual(tree["README.md"], before)
        self.assertEqual(self.manifest()["external_modules"]["kb"]["digest"], FIXTURE_DIGEST)
        self.assertEqual(self.manifest()["modules"], ["graphify"])

    def test_add_matches_fresh_install(self):
        store = self.store()
        self.assertEqual(self.new("graphify")[0], 0)
        self.assertEqual(self.add("kb=" + store)[0], 0)
        self.assertEqual(self.new("graphify,kb=" + store, name="fresh")[0], 0)
        self.assertEqual(read_tree(self.target())["AGENTS.md"],
                         read_tree(self.target("fresh"))["AGENTS.md"])

    def test_add_refuses_fragment_without_marker(self):
        self.assertEqual(self.new("graphify")[0], 0)
        before = read_tree(self.target())
        orphan = self.store(slots={"no-such-slot": b"x\n"})
        code, out, err = self.add("kb=" + orphan)
        self.assertEqual(code, 2)
        self.assertEqual(read_tree(self.target()), before)

    def test_add_recorded_external_is_already_installed(self):
        store = self.store()
        self.assertEqual(self.new("kb=" + store)[0], 0)
        before = read_tree(self.target())
        for entry in ("kb", "kb=" + os.path.join(self.work, "gone")):
            with self.subTest(entry=entry):
                code, out, err = self.add(entry)
                self.assertEqual(code, 0, err)
                self.assertIn("already installed", out)
                self.assertEqual(read_tree(self.target()), before)

    def test_add_second_external_keeps_first_entry(self):
        self.assertEqual(self.new("a=" + self.store(name="one"))[0], 0)
        first = self.manifest()["external_modules"]["a"]
        self.assertEqual(self.add("b=" + self.store(name="two"))[0], 0)
        entries = self.manifest()["external_modules"]
        self.assertEqual(entries["a"], first)
        self.assertEqual(sorted(entries), ["a", "b"])

    def test_add_builtin_after_external_does_not_resolve_store_again(self):
        store = self.store()
        self.assertEqual(self.new("kb=" + store)[0], 0)
        import shutil
        shutil.rmtree(store)
        code, out, err = self.add("graphify")
        self.assertEqual(code, 0, err)
        manifest = self.manifest()
        self.assertEqual(manifest["modules"], ["graphify"])
        self.assertIn("kb", manifest["external_modules"])
        agents = read_tree(self.target())["AGENTS.md"]
        self.assertEqual(agents.count("BEGIN module:kb slot:agents-guidance"), 1)

    def test_manifest_external_validation(self):
        good = {"module_format": 1, "digest": FIXTURE_DIGEST}
        bad = {
            "not an object": [],
            "bad name": {"Bad": good},
            "builtin name": {"cad": good},
            "unknown format": {"kb": {"module_format": 3, "digest": FIXTURE_DIGEST}},
            "bool format": {"kb": {"module_format": True, "digest": FIXTURE_DIGEST}},
            "short digest": {"kb": {"module_format": 1, "digest": "ab"}},
            "digest with newline": {"kb": {"module_format": 1, "digest": FIXTURE_DIGEST + "\n"}},
            "name with newline": {"kb\n": good},
            "uppercase digest": {"kb": {"module_format": 1, "digest": FIXTURE_DIGEST.upper()}},
            "entry not an object": {"kb": "x"},
        }
        self.assertEqual(self.new("graphify")[0], 0)
        base = self.manifest()
        for label, value in bad.items():
            with self.subTest(case=label):
                self.write_manifest(dict(base, external_modules=value))
                code, out, err = self.add("cad")
                self.assertEqual(code, 2, out)
        self.write_manifest(dict(base, external_modules={"kb": good}))
        self.assertEqual(self.add("cad")[0], 0)

    def test_add_skip_unsafe_entries_with_external(self):
        self.assertEqual(self.new("graphify")[0], 0)
        os.symlink(self.work, os.path.join(self.target(), "linked"))
        self.assertEqual(self.add("kb=" + self.store())[0], 2)
        code, out, err = self.add("kb=" + self.store(name="again"),
                                  extra=["--skip-unsafe-entries"])
        self.assertEqual(code, 0, err)
        self.assertIn("linked", out)


class RegistryTest(unittest.TestCase):
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
        os.environ["HOME"] = self.work
        os.environ.pop("XDG_CONFIG_HOME", None)
        self.addCleanup(self._restore_env)
        self.reg = os.path.join(self.work, "cfg", "registry.json")
        self.builtin = set(install.load_modules())

    def _restore_env(self):
        os.environ.clear()
        os.environ.update(self.saved)

    def store(self, **kwargs):
        return make_store(self.work, **kwargs)

    def target(self, name="proj"):
        return os.path.join(self.work, name)

    def stores(self):
        if not os.path.exists(self.reg):
            return {}
        with open(self.reg) as handle:
            return {n: e["path"] for n, e in json.load(handle)["stores"].items()}

    def write_registry(self, raw, path=None):
        path = path or self.reg
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as handle:
            handle.write(raw if isinstance(raw, bytes) else json.dumps(raw).encode())

    def register(self, *argv):
        return run(["--register"] + list(argv) + ["--registry", self.reg])

    def new(self, with_, name="proj"):
        return run([self.target(name), "--with", with_, "--registry", self.reg,
                    "--git-name", "Test User", "--git-email", "tester@users.noreply.example.invalid"])

    def add(self, *entries, name="proj"):
        return run(["--add"] + list(entries) + ["--dir", self.target(name), "--registry", self.reg])

    # -- Increment A: the registry file -------------------------------

    def test_registry_path_default_and_xdg(self):
        default = os.path.join(self.work, ".config", "claude-project-template", "registry.json")
        self.assertEqual(install.registry_path(), default)
        os.environ["XDG_CONFIG_HOME"] = os.path.join(self.work, "xdg")
        self.assertEqual(
            install.registry_path(),
            os.path.join(self.work, "xdg", "claude-project-template", "registry.json"),
        )
        os.environ["XDG_CONFIG_HOME"] = "relative/dir"
        self.assertEqual(install.registry_path(), default)
        self.assertEqual(install.registry_path(self.reg), self.reg)

    def test_empty_registry_override_is_refused(self):
        with self.assertRaises(install.InstallError):
            install.registry_path("")

    def test_load_missing_is_empty(self):
        self.assertEqual(install.load_registry(self.reg), {})

    def test_save_then_load_round_trips(self):
        install.save_registry(self.reg, {"b_kb": "/abs/b", "a_kb": "/abs/a"})
        with open(self.reg) as handle:
            self.assertEqual(
                json.load(handle),
                {"schema": 1, "stores": {"a_kb": {"path": "/abs/a"}, "b_kb": {"path": "/abs/b"}}},
            )
        self.assertEqual(os.stat(os.path.dirname(self.reg)).st_mode & 0o077, 0)
        self.assertEqual(install.load_registry(self.reg), {"a_kb": "/abs/a", "b_kb": "/abs/b"})

    def test_load_refuses_malformed_registries(self):
        good = {"schema": 1, "stores": {"kb": {"path": "/abs/kb"}}}
        cases = {
            "invalid json": b"{",
            "not an object": [],
            "schema 2": dict(good, schema=2),
            "schema true": dict(good, schema=True),
            "unknown top-level key": dict(good, extra=1),
            "stores not an object": {"schema": 1, "stores": []},
            "bad name": {"schema": 1, "stores": {"Bad": {"path": "/abs/x"}}},
            "name with newline": {"schema": 1, "stores": {"kb\n": {"path": "/abs/x"}}},
            "entry not an object": {"schema": 1, "stores": {"kb": "/abs/x"}},
            "entry unknown key": {"schema": 1, "stores": {"kb": {"path": "/abs/x", "x": 1}}},
            "relative path": {"schema": 1, "stores": {"kb": {"path": "rel/x"}}},
            "multi-line path": {"schema": 1, "stores": {"kb": {"path": "/abs/x\ny"}}},
            "oversized": b" " * (1024 * 1024 + 1),
        }
        for label, raw in cases.items():
            with self.subTest(case=label):
                path = os.path.join(self.work, label.replace(" ", "_"), "registry.json")
                self.write_registry(raw, path)
                with self.assertRaises(install.InstallError) as ctx:
                    install.load_registry(path)
                self.assertIn("registry", str(ctx.exception))

    def test_load_and_save_refuse_symlinks_and_special_files(self):
        real = os.path.join(self.work, "real")
        self.write_registry({"schema": 1, "stores": {}}, os.path.join(real, "registry.json"))
        link_dir = os.path.join(self.work, "link-dir")
        os.symlink(real, link_dir)
        link_file_dir = os.path.join(self.work, "file-link")
        os.makedirs(link_file_dir)
        os.symlink(os.path.join(real, "registry.json"), os.path.join(link_file_dir, "registry.json"))
        fifo_dir = os.path.join(self.work, "fifo")
        os.makedirs(fifo_dir)
        os.mkfifo(os.path.join(fifo_dir, "registry.json"))
        dir_dir = os.path.join(self.work, "dirdir")
        os.makedirs(os.path.join(dir_dir, "registry.json"))
        for label, folder in (("dir", link_dir), ("file", link_file_dir),
                              ("fifo", fifo_dir), ("directory", dir_dir)):
            path = os.path.join(folder, "registry.json")
            with self.subTest(case=label, op="load"):
                with self.assertRaises(install.InstallError):
                    install.load_registry(path)
            with self.subTest(case=label, op="save"):
                with self.assertRaises(install.InstallError):
                    install.save_registry(path, {"kb": "/abs/kb"})
        with open(os.path.join(real, "registry.json")) as handle:
            self.assertEqual(json.load(handle), {"schema": 1, "stores": {}})

    # -- Increment B: --register and --unregister ---------------------

    def test_register_defaults_name_to_directory_name(self):
        store = self.store()
        code, out, err = self.register(store)
        self.assertEqual(code, 0, err)
        self.assertEqual(self.stores(), {"my_kb": os.path.realpath(store)})
        self.assertIn("my_kb", out)
        self.assertIn("Fixture store", out)

    def test_register_name_override_tilde_and_relative(self):
        store = self.store()
        self.assertEqual(self.register(store, "--name", "work_kb")[0], 0)
        third = self.store(name="third")
        self.assertEqual(self.register("~/third")[0], 0)
        self.addCleanup(os.chdir, os.getcwd())
        os.chdir(self.work)
        fourth = self.store(name="fourth")
        self.assertEqual(self.register("fourth")[0], 0)
        self.assertEqual(
            self.stores(),
            {"work_kb": os.path.realpath(store), "third": os.path.realpath(third),
             "fourth": os.path.realpath(fourth)},
        )

    def test_register_same_name_same_path_is_noop(self):
        store = self.store()
        self.assertEqual(self.register(store)[0], 0)
        with open(self.reg, "rb") as handle:
            before = handle.read()
        code, out, err = self.register(store)
        self.assertEqual(code, 0, err)
        with open(self.reg, "rb") as handle:
            self.assertEqual(handle.read(), before)

    def test_register_refusals_leave_registry_unchanged(self):
        store = self.store()
        other = self.store(name="other")
        self.assertEqual(self.register(store)[0], 0)
        with open(self.reg, "rb") as handle:
            before = handle.read()
        elsewhere = os.path.join(self.work, "elsewhere")
        os.makedirs(elsewhere)
        same_name_elsewhere = make_store(elsewhere, name="my_kb")
        bad_dir = make_store(self.work, name="bad dir")
        bad_store = os.path.join(self.work, "bare")
        os.makedirs(bad_store)
        linked = os.path.join(self.work, "linked")
        os.symlink(store, linked)
        cases = {
            "same name other path": ([same_name_elsewhere], "my_kb"),
            "same path other name": ([store, "--name", "second"], "my_kb"),
            "builtin name": ([other, "--name", "cad"], "built-in"),
            "bad directory name": ([bad_dir], "--name"),
            "no descriptor": ([bad_store, "--name", "bare_kb"], "template-module"),
            "symlinked store": ([linked, "--name", "link_kb"], "symlink"),
            "inside template": ([os.path.join(install.ROOT, "modules"), "--name", "tpl"], "template"),
        }
        for label, (argv, needle) in cases.items():
            with self.subTest(case=label):
                code, out, err = self.register(*argv)
                self.assertEqual(code, 2, out)
                self.assertIn(needle, err)
                with open(self.reg, "rb") as handle:
                    self.assertEqual(handle.read(), before)
        self.assertIn("unregister", self.register(same_name_elsewhere)[2])

    def test_register_dry_run_writes_nothing(self):
        store = self.store()
        code, out, err = self.register(store, "--dry-run")
        self.assertEqual(code, 0, err)
        self.assertFalse(os.path.exists(os.path.dirname(self.reg)))
        self.assertIn("Dry run", out)

    def test_unregister_dry_run_removes_nothing(self):
        store = self.store()
        self.assertEqual(self.register(store)[0], 0)
        before = self.stores()
        code, out, err = run(["--unregister", "my_kb", "--dry-run", "--registry", self.reg])
        self.assertEqual(code, 0, err)
        self.assertEqual(self.stores(), before)
        self.assertIn("Would unregister", out)
        self.assertIn("Dry run", out)

    def test_register_refuses_the_same_store_under_a_case_alias(self):
        store = self.store(name="alias_kb")
        alias = os.path.join(self.work, "ALIAS_KB")
        if not (os.path.exists(alias) and os.path.samefile(alias, store)):
            self.skipTest("filesystem is case sensitive")
        self.assertEqual(self.register(store, "--name", "ra")[0], 0)
        before = self.stores()
        code, out, err = self.register(alias, "--name", "rb")
        self.assertEqual(code, 2, out)
        self.assertIn("already registered", err)
        self.assertEqual(self.stores(), before)

    def test_register_refuses_a_non_printable_real_path(self):
        hostile = os.path.join(self.work, "evil\x1b[2Jdir")
        os.mkdir(hostile)
        make_store(hostile)
        link = os.path.join(self.work, "lk")
        os.symlink(hostile, link)
        code, out, err = self.register(os.path.join(link, "my_kb"))
        self.assertEqual(code, 2, out)
        self.assertIn("printable", err)
        self.assertNotIn("\x1b", out + err)
        self.assertFalse(os.path.exists(self.reg))

    def test_register_and_unregister_leave_the_store_untouched(self):
        store = self.store()
        os.makedirs(os.path.join(store, ".git"))
        before = tree_hash(store)
        self.assertEqual(self.register(store)[0], 0)
        self.assertEqual(self.register(store, "--dry-run")[0], 0)
        self.assertEqual(tree_hash(store), before)
        self.assertEqual(run(["--unregister", "my_kb", "--registry", self.reg])[0], 0)
        self.assertEqual(tree_hash(store), before)
        self.assertEqual(self.stores(), {})

    def test_unregister_works_when_the_store_is_gone(self):
        import shutil
        store = self.store()
        self.assertEqual(self.register(store)[0], 0)
        shutil.rmtree(store)
        code, out, err = run(["--unregister", "my_kb", "--registry", self.reg])
        self.assertEqual(code, 0, err)
        self.assertEqual(self.stores(), {})

    def test_unregister_unknown_succeeds_and_builtin_is_refused(self):
        code, out, err = run(["--unregister", "no_such", "--registry", self.reg])
        self.assertEqual(code, 0, err)
        self.assertIn("not registered", out)
        self.assertEqual(run(["--unregister", "cad", "--registry", self.reg])[0], 2)

    def test_unregister_keeps_existing_projects(self):
        store = self.store()
        self.assertEqual(self.register(store)[0], 0)
        self.assertEqual(self.new("my_kb")[0], 0)
        before = read_tree(self.target())
        self.assertEqual(run(["--unregister", "my_kb", "--registry", self.reg])[0], 0)
        self.assertEqual(read_tree(self.target()), before)

    def test_mode_flags_are_exclusive(self):
        store = self.store()
        for argv in (
            ["--register", store, self.target()],
            ["--register", store, "--with", "cad"],
            ["--register", store, "--list"],
            ["--register", store, "--add", "cad"],
            ["--unregister", "my_kb", "--list"],
            ["--unregister", "my_kb", "--register", store],
            ["--register", store, "--dir", self.work, "--with", "cad"],
        ):
            with self.subTest(argv=argv):
                self.assertEqual(run(argv + ["--registry", self.reg])[0], 2)
        self.assertFalse(os.path.exists(self.reg))

    def test_old_list_and_add_precedence_is_unchanged(self):
        self.assertEqual(self.new("graphify")[0], 0)
        listing = run(["--list", "--registry", self.reg])[1]
        for argv in (
            [self.target("other"), "--list"],
            ["--list", "--with", "cad"],
            ["--list", "--add", "cad"],
        ):
            with self.subTest(argv=argv):
                code, out, err = run(argv + ["--registry", self.reg])
                self.assertEqual((code, out), (0, listing), err)
        code, out, err = run([self.target("other"), "--add", "cad", "--dir", self.target(),
                              "--registry", self.reg])
        self.assertEqual(code, 0, err)
        self.assertIn("cad", self.manifest_modules())

    def manifest_modules(self, name="proj"):
        with open(os.path.join(self.target(name), ".template-manifest")) as handle:
            return json.load(handle)["modules"]

    def test_empty_register_and_unregister_values_are_refused(self):
        for argv in (["--register", ""], ["--unregister", ""]):
            with self.subTest(argv=argv):
                self.assertEqual(run(argv + ["--registry", self.reg])[0], 2)
        self.assertFalse(os.path.exists(self.reg))

    def test_register_missing_path_is_refused(self):
        code, out, err = self.register(os.path.join(self.work, "nope"))
        self.assertEqual(code, 2)
        self.assertFalse(os.path.exists(self.reg))

    def test_register_and_unregister_refuse_a_symlinked_registry(self):
        real = os.path.join(self.work, "real")
        os.makedirs(real)
        os.symlink(real, os.path.join(self.work, "cfg"))
        store = self.store()
        self.assertEqual(self.register(store)[0], 2)
        self.assertEqual(run(["--unregister", "my_kb", "--registry", self.reg])[0], 2)
        self.assertEqual(os.listdir(real), [])

    def test_register_without_registry_flag_writes_the_default_location(self):
        store = self.store()
        code, out, err = run(["--register", store])
        self.assertEqual(code, 0, err)
        default = os.path.join(self.work, ".config", "claude-project-template", "registry.json")
        with open(default) as handle:
            self.assertEqual(sorted(json.load(handle)["stores"]), ["my_kb"])

    def test_list_with_malformed_registry_still_shows_built_ins_then_fails(self):
        self.write_registry(b"{")
        code, out, err = run(["--list", "--registry", self.reg])
        self.assertEqual(code, 2)
        self.assertIn("graphify:", out)
        self.assertIn(self.reg, err)

    # -- Increment C: --list, bare names, collisions ------------------

    def test_list_without_registry_is_unchanged(self):
        code, out, err = run(["--list", "--registry", self.reg])
        self.assertEqual(code, 0, err)
        self.assertNotIn("Registered stores", out)
        self.assertEqual(out, run(["--list"])[1])

    def test_list_shows_registered_stores_with_status(self):
        import shutil
        ok = self.store(name="ok_kb")
        gone = self.store(name="gone_kb")
        broken = self.store(name="broken_kb")
        linked_target = self.store(name="real_kb")
        for store in (ok, gone, broken, linked_target):
            self.assertEqual(self.register(store)[0], 0)
        self.write_registry({"schema": 1, "stores": dict(
            {n: {"path": p} for n, p in self.stores().items()},
            graphify={"path": ok},
        )})
        shutil.rmtree(gone)
        os.unlink(os.path.join(broken, "template-module", "module.json"))
        shutil.rmtree(linked_target)
        os.symlink(ok, linked_target)
        code, out, err = run(["--list", "--registry", self.reg])
        self.assertEqual(code, 0, err)
        lines = {line.split()[0]: line for line in out.split("Registered stores:")[1].splitlines()
                 if line.strip()}
        self.assertIn("[ok]", lines["ok_kb"])
        self.assertIn("Fixture store", lines["ok_kb"])
        self.assertIn("[missing]", lines["gone_kb"])
        self.assertIn("[invalid:", lines["broken_kb"])
        self.assertIn("[invalid:", lines["real_kb"])
        self.assertIn("shadowed by a built-in module", lines["graphify"])
        self.assertIn("graphify:", out.split("Registered stores:")[0])

    def test_with_registered_name_matches_typed_path(self):
        store = self.store()
        self.assertEqual(self.register(store)[0], 0)
        self.assertEqual(self.new("graphify,my_kb")[0], 0)
        self.assertEqual(self.new("graphify,my_kb=" + store, name="typed")[0], 0)
        self.assertEqual(read_tree(self.target())["AGENTS.md"],
                         read_tree(self.target("typed"))["AGENTS.md"])
        with open(os.path.join(self.target(), ".template-manifest")) as one, \
                open(os.path.join(self.target("typed"), ".template-manifest")) as two:
            self.assertEqual(json.load(one)["external_modules"], json.load(two)["external_modules"])

    def test_two_registered_stores_in_one_project(self):
        for name in ("one", "two"):
            self.assertEqual(self.register(self.store(name=name))[0], 0)
        self.assertEqual(self.new("one,two")[0], 0)
        agents = read_tree(self.target())["AGENTS.md"]
        self.assertIn("BEGIN module:one slot:agents-guidance", agents)
        self.assertIn("BEGIN module:two slot:agents-guidance", agents)

    def test_add_registered_name(self):
        self.assertEqual(self.register(self.store())[0], 0)
        self.assertEqual(self.new("graphify")[0], 0)
        code, out, err = self.add("my_kb")
        self.assertEqual(code, 0, err)
        self.assertIn("BEGIN module:my_kb slot:agents-guidance", read_tree(self.target())["AGENTS.md"])

    def test_add_recorded_name_does_not_open_registry(self):
        self.assertEqual(self.register(self.store())[0], 0)
        self.assertEqual(self.new("my_kb")[0], 0)
        self.write_registry(b"{")
        code, out, err = self.add("my_kb")
        self.assertEqual(code, 0, err)
        self.assertIn("already installed", out)

    def test_registered_name_with_a_different_typed_path_is_refused(self):
        store = self.store()
        other = self.store(name="other")
        self.assertEqual(self.register(store)[0], 0)
        code, out, err = self.new("my_kb=" + other)
        self.assertEqual(code, 2)
        self.assertFalse(os.path.exists(self.target()))
        self.assertIn("registered at", err)
        self.assertEqual(self.new("my_kb=" + store)[0], 0)

    def test_builtin_only_run_never_opens_the_registry(self):
        self.write_registry(b"{")
        code, out, err = self.new("graphify,claude")
        self.assertEqual(code, 0, err)
        self.assertEqual(self.add("cad")[0], 0)
        os.unlink(self.reg)
        os.symlink(self.work, self.reg)
        self.assertEqual(self.new("cad", name="again")[0], 0)

    def test_unknown_name_lists_registered_names(self):
        self.assertEqual(self.register(self.store())[0], 0)
        code, out, err = self.new("no_such")
        self.assertEqual(code, 2)
        self.assertIn("my_kb", err)
        self.assertIn("cad", err)

    def test_malformed_registry_error_names_the_file(self):
        self.write_registry(b"{")
        code, out, err = self.new("no_such")
        self.assertEqual(code, 2)
        self.assertIn(self.reg, err)
        self.assertFalse(os.path.exists(self.target()))

    def test_registered_path_is_reverified_at_use(self):
        import shutil
        store = self.store()
        self.assertEqual(self.register(store)[0], 0)
        os.unlink(os.path.join(store, "template-module", "module.json"))
        code, out, err = self.new("my_kb")
        self.assertEqual(code, 2)
        self.assertIn("module.json", err)
        self.assertIn("register it again", err)
        self.assertFalse(os.path.exists(self.target()))
        shutil.rmtree(store)
        os.symlink(self.work, store)
        code, out, err = self.new("my_kb", name="second")
        self.assertEqual(code, 2)
        self.assertIn("symlink", err)
        self.assertFalse(os.path.exists(self.target("second")))


class ProjectCase(unittest.TestCase):
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
        os.environ["XDG_CONFIG_HOME"] = os.path.join(self.work, "xdg")
        self.addCleanup(self._restore_env)

    def _restore_env(self):
        os.environ.clear()
        os.environ.update(self.saved)

    def target(self):
        return os.path.join(self.work, "proj")

    def new(self, with_):
        return run([self.target(), "--with", with_, "--git-name", "Test User",
                    "--git-email", "tester@users.noreply.example.invalid"])

    def update(self, *argv):
        return run(["--update"] + list(argv) + ["--dir", self.target()])

    def path(self, rel):
        return os.path.join(self.target(), *rel.split("/"))

    def read(self, rel):
        with open(self.path(rel), encoding="utf-8") as handle:
            return handle.read()

    def write(self, rel, text):
        with open(self.path(rel), "w", encoding="utf-8") as handle:
            handle.write(text)

    def block_lines(self, rel, module, slot):
        """Return (lines, begin index, end index) of a module block in a file."""
        lines = self.read(rel).split("\n")
        begin = [i for i, l in enumerate(lines) if "BEGIN module:%s slot:%s" % (module, slot) in l]
        end = [i for i, l in enumerate(lines) if "END module:%s slot:%s" % (module, slot) in l]
        self.assertEqual((len(begin), len(end)), (1, 1))
        return lines, begin[0], end[0]

    def tamper(self, rel, module, slot):
        lines, begin, end = self.block_lines(rel, module, slot)
        lines[begin + 1] = "TAMPERED"
        self.write(rel, "\n".join(lines))

    def fake_modules(self, slot_text):
        root = os.path.join(self.work, "fake-modules")
        os.makedirs(os.path.join(root, "demo", "slots"), exist_ok=True)
        with open(os.path.join(root, "demo", "module.json"), "w") as handle:
            json.dump({"description": "demo"}, handle)
        self.set_fragment(root, slot_text)
        saved = install.MODULES_DIR
        install.MODULES_DIR = root
        self.addCleanup(setattr, install, "MODULES_DIR", saved)
        return root

    def set_fragment(self, root, text):
        with open(os.path.join(root, "demo", "slots", "agents-guidance.md"), "w") as handle:
            handle.write(text)


class UpdateTest(ProjectCase):
    def test_unchanged_project_is_a_noop(self):
        self.assertEqual(self.new(ALL)[0], 0)
        before = tree_hash(self.target())
        code, out, err = self.update()
        self.assertEqual(code, 0, err)
        self.assertIn("Nothing to update", out)
        self.assertEqual(tree_hash(self.target()), before)

    def test_stale_block_is_replaced(self):
        self.new("graphify")
        original = self.read("AGENTS.md")
        self.tamper("AGENTS.md", "graphify", "agents-guidance")
        code, out, err = self.update()
        self.assertEqual(code, 0, err)
        self.assertEqual(self.read("AGENTS.md"), original)
        self.assertIn("AGENTS.md", out)

    def test_removed_block_is_inserted(self):
        self.new("graphify")
        lines, begin, end = self.block_lines("AGENTS.md", "graphify", "agents-guidance")
        body = lines[begin + 1:end]
        self.write("AGENTS.md", "\n".join(lines[:begin] + lines[end + 1:]))
        code, out, err = self.update()
        self.assertEqual(code, 0, err)
        lines, begin, end = self.block_lines("AGENTS.md", "graphify", "agents-guidance")
        self.assertEqual(lines[begin + 1:end], body)

    def test_nested_blocks_survive_a_refresh(self):
        self.new("cad-freecad")
        original = self.read("AGENTS.md")
        self.tamper("AGENTS.md", "cad", "agents-guidance")
        code, out, err = self.update()
        self.assertEqual(code, 0, err)
        self.assertEqual(self.read("AGENTS.md"), original)
        self.assertIn("module:cad-freecad slot:agents-cad-tool", original)

    def test_missing_module_file_is_written(self):
        self.new("graphify")
        os.remove(self.path(".graphifyignore"))
        code, out, err = self.update()
        self.assertEqual(code, 0, err)
        self.assertTrue(os.path.isfile(self.path(".graphifyignore")))
        self.assertIn(".graphifyignore", out)

    def test_differing_module_file_is_kept_and_reported(self):
        self.new("cad")
        self.write("docs/cad.md", "my edits\n")
        code, out, err = self.update()
        self.assertEqual(code, 0, err)
        self.assertEqual(self.read("docs/cad.md"), "my edits\n")
        self.assertIn("docs/cad.md", out)
        self.assertIn("not overwriting", out)

    def test_dry_run_writes_nothing(self):
        self.new("graphify")
        self.tamper("AGENTS.md", "graphify", "agents-guidance")
        before = tree_hash(self.target())
        code, out, err = self.update("--dry-run")
        self.assertEqual(code, 0, err)
        self.assertIn("would write AGENTS.md", out)
        self.assertIn("Dry run", out)
        self.assertEqual(tree_hash(self.target()), before)

    def test_named_module_only(self):
        self.new("graphify,formal")
        self.tamper("AGENTS.md", "graphify", "agents-guidance")
        self.tamper("AGENTS.md", "formal", "agents-guidance")
        code, out, err = self.update("formal")
        self.assertEqual(code, 0, err)
        text = self.read("AGENTS.md")
        self.assertEqual(text.count("TAMPERED"), 1)
        lines, begin, end = self.block_lines("AGENTS.md", "graphify", "agents-guidance")
        self.assertEqual(lines[begin + 1], "TAMPERED")

    def test_module_not_installed_is_an_error(self):
        self.new("graphify")
        code, out, err = self.update("cad")
        self.assertEqual(code, 2)
        self.assertIn("not installed", err)

    def test_upgrade_is_an_alias(self):
        self.new("graphify")
        self.tamper("AGENTS.md", "graphify", "agents-guidance")
        code, out, err = run(["--upgrade", "--dir", self.target()])
        self.assertEqual(code, 0, err)
        self.assertNotIn("TAMPERED", self.read("AGENTS.md"))

    def test_changed_fragment_is_applied_and_manifest_refreshed(self):
        root = self.fake_modules("demo v1\n")
        self.new("demo")
        self.assertIn("demo v1", self.read("AGENTS.md"))
        manifest = json.loads(self.read(".template-manifest"))
        manifest["template_commit"] = "0" * 40
        self.write(".template-manifest", json.dumps(manifest))
        self.set_fragment(root, "demo v2\n")
        code, out, err = self.update()
        self.assertEqual(code, 0, err)
        text = self.read("AGENTS.md")
        self.assertIn("demo v2", text)
        self.assertNotIn("demo v1", text)
        self.assertNotEqual(json.loads(self.read(".template-manifest"))["template_commit"], "0" * 40)

    def test_dropped_fragment_leaves_its_block_alone(self):
        root = self.fake_modules("demo v1\n")
        self.new("demo")
        os.remove(os.path.join(root, "demo", "slots", "agents-guidance.md"))
        code, out, err = self.update()
        self.assertEqual(code, 0, err)
        self.assertIn("demo v1", self.read("AGENTS.md"))
        self.assertIn("agents-guidance", out)

    def test_malformed_markers_leave_the_file_alone(self):
        self.new("graphify")
        lines, begin, end = self.block_lines("AGENTS.md", "graphify", "agents-guidance")
        broken = "\n".join(lines[:end] + lines[end + 1:])
        self.write("AGENTS.md", broken)
        code, out, err = self.update()
        self.assertEqual(code, 0, err)
        self.assertEqual(self.read("AGENTS.md"), broken)
        self.assertIn("AGENTS.md", out)
        self.assertIn("malformed", out)

    def test_edited_heading_is_restored(self):
        self.new("graphify")
        original = self.read("AGENTS.md")
        lines, begin, end = self.block_lines("AGENTS.md", "graphify", "agents-guidance")
        lines[begin + 1] = "edited heading"
        self.write("AGENTS.md", "\n".join(lines))
        code, out, err = self.update()
        self.assertEqual(code, 0, err)
        self.assertEqual(self.read("AGENTS.md"), original)

    OLD_PLAN = "# Old plan\n\n<!-- @module-slot: plan-discovery -->\n"

    def test_update_leaves_project_created_files_alone(self):
        self.new("graphify")
        self.write("docs/plans/0001-old.md", self.OLD_PLAN)
        code, out, err = self.update()
        self.assertEqual(code, 0, err)
        self.assertEqual(self.read("docs/plans/0001-old.md"), self.OLD_PLAN)

    def test_update_does_not_refresh_a_block_in_a_project_created_file(self):
        self.new("graphify")
        lines, begin, end = self.block_lines("docs/plans/next.md", "graphify", "plan-discovery")
        lines[begin + 1] = "FILLED IN"
        old = "\n".join(lines)
        self.write("docs/plans/0001-old.md", old)
        code, out, err = self.update()
        self.assertEqual(code, 0, err)
        self.assertEqual(self.read("docs/plans/0001-old.md"), old)

    def test_update_keeps_a_filled_in_block_in_next_md(self):
        self.new("graphify")
        lines, begin, end = self.block_lines("docs/plans/next.md", "graphify", "plan-discovery")
        lines[end - 1] = "Graphify: skipped - scope is enumerated."
        self.write("docs/plans/next.md", "\n".join(lines))
        before = self.read("docs/plans/next.md")
        code, out, err = self.update()
        self.assertEqual(code, 0, err)
        self.assertEqual(self.read("docs/plans/next.md"), before)

    def test_update_inserts_a_missing_block_in_next_md(self):
        self.new("graphify")
        original = self.read("docs/plans/next.md")
        lines, begin, end = self.block_lines("docs/plans/next.md", "graphify", "plan-discovery")
        self.write("docs/plans/next.md", "\n".join(lines[:begin] + lines[end + 1:]))
        code, out, err = self.update()
        self.assertEqual(code, 0, err)
        self.assertIn("module:graphify slot:plan-discovery", self.read("docs/plans/next.md"))

    def test_add_skips_project_created_files(self):
        self.new("claude")
        self.write("docs/plans/0001-old.md", self.OLD_PLAN)
        code, out, err = run(["--add", "graphify", "--dir", self.target()])
        self.assertEqual(code, 0, err)
        self.assertEqual(self.read("docs/plans/0001-old.md"), self.OLD_PLAN)
        self.assertIn("module:graphify slot:plan-discovery", self.read("docs/plans/next.md"))

    def test_add_fails_when_only_a_project_created_file_has_the_marker(self):
        self.new("claude")
        text = self.read("docs/plans/next.md")
        self.write("docs/plans/next.md",
                   text.replace("<!-- @module-slot: plan-discovery -->\n", ""))
        self.write("docs/plans/0001-old.md", self.OLD_PLAN)
        code, out, err = run(["--add", "graphify", "--dir", self.target()])
        self.assertNotEqual(code, 0)
        self.assertIn("plan-discovery", err)
        self.assertEqual(self.read("docs/plans/0001-old.md"), self.OLD_PLAN)

    # -- report of files left alone (plan 0014) -------------------------

    def test_fresh_project_reports_nothing_left_alone(self):
        self.new(ALL)
        code, out, err = self.update()
        self.assertEqual(code, 0, err)
        self.assertNotIn("kept", out)
        self.assertNotIn("not patched", out)

    def test_differing_base_file_is_kept_and_reported(self):
        self.new("graphify")
        mine = self.read("docs/plans/README.md") + "\nMy own rule.\n"
        self.write("docs/plans/README.md", mine)
        code, out, err = self.update()
        self.assertEqual(code, 0, err)
        self.assertEqual(self.read("docs/plans/README.md"), mine)
        self.assertIn("kept docs/plans/README.md (differs from the template", out)

    def test_report_appears_in_a_dry_run(self):
        self.new("graphify")
        self.write("docs/plans/README.md", "mine\n")
        before = tree_hash(self.target())
        code, out, err = self.update("--dry-run")
        self.assertEqual(code, 0, err)
        self.assertIn("kept docs/plans/README.md", out)
        self.assertEqual(tree_hash(self.target()), before)

    def test_blocks_alone_do_not_make_a_file_differ(self):
        self.new(ALL)
        code, out, err = self.update()
        self.assertNotIn("kept AGENTS.md", out)
        self.assertNotIn("kept docs/plans/next.md", out)

    def test_project_created_file_with_a_marker_is_reported(self):
        self.new("graphify")
        self.write("docs/plans/0001-old.md", self.OLD_PLAN)
        code, out, err = self.update()
        self.assertEqual(code, 0, err)
        self.assertEqual(self.read("docs/plans/0001-old.md"), self.OLD_PLAN)
        self.assertIn("skipped docs/plans/0001-old.md (project-created file with markers", out)

    def test_active_plan_is_reported_as_per_plan(self):
        self.new("graphify")
        self.write("docs/plans/next.md", "# My plan\n\nStatus: Proposed\nCreated: 2026-01-01\n")
        code, out, err = self.update()
        self.assertEqual(code, 0, err)
        self.assertIn("kept docs/plans/next.md (per-plan file", out)

    def test_projects_grown_by_add_are_stable(self):
        self.new("claude")
        for name in ("graphify", "cad", "cad-freecad", "formal"):
            self.assertEqual(run(["--add", name, "--dir", self.target()])[0], 0)
        before = tree_hash(self.target())
        code, out, err = self.update()
        self.assertEqual(code, 0, err)
        self.assertIn("Nothing to update", out)
        self.assertEqual(tree_hash(self.target()), before)

    # -- external modules -----------------------------------------------

    def store(self, **kwargs):
        return make_store(self.work, **kwargs)

    def change_store(self, store, text):
        with open(os.path.join(store, "template-module", "slots", "agents-guidance.md"), "w") as handle:
            handle.write(text)

    def recorded_digest(self):
        return json.loads(self.read(".template-manifest"))["external_modules"]["my_kb"]["digest"]

    def test_external_change_is_applied_by_path(self):
        store = self.store()
        self.assertEqual(self.new("graphify,my_kb=" + store)[0], 0)
        old = self.recorded_digest()
        self.change_store(store, "## Fixture guidance\n\nNew words.\n")
        code, out, err = self.update("my_kb=" + store)
        self.assertEqual(code, 0, err)
        text = self.read("AGENTS.md")
        self.assertIn("New words.", text)
        self.assertNotIn("router.md", text)
        self.assertNotEqual(self.recorded_digest(), old)

    def test_external_description_change_refreshes_the_digest(self):
        store = self.store()
        self.new("my_kb=" + store)
        old = self.recorded_digest()
        with open(os.path.join(store, "template-module", "module.json"), "wb") as handle:
            handle.write(b'{"module_format": 1, "description": "Reworded store"}\n')
        code, out, err = self.update("my_kb=" + store)
        self.assertEqual(code, 0, err)
        self.assertNotEqual(self.recorded_digest(), old)

    def test_external_unchanged_is_a_noop(self):
        store = self.store()
        self.new("my_kb=" + store)
        before = tree_hash(self.target())
        code, out, err = self.update("my_kb=" + store)
        self.assertEqual(code, 0, err)
        self.assertIn("Nothing to update", out)
        self.assertEqual(tree_hash(self.target()), before)

    def test_registered_external_is_found_without_naming_it(self):
        store = self.store()
        self.assertEqual(run(["--register", store])[0], 0)
        self.assertEqual(self.new("my_kb")[0], 0)
        self.change_store(store, "## Fixture guidance\n\nNew words.\n")
        code, out, err = self.update()
        self.assertEqual(code, 0, err)
        self.assertIn("New words.", self.read("AGENTS.md"))

    def test_unresolvable_external_is_skipped_with_a_note(self):
        store = self.store()
        self.new("graphify,my_kb=" + store)
        self.tamper("AGENTS.md", "graphify", "agents-guidance")
        code, out, err = self.update()
        self.assertEqual(code, 0, err)
        self.assertIn("my_kb", out)
        self.assertIn("skipped", out)
        self.assertNotIn("TAMPERED", self.read("AGENTS.md"))
        self.assertIn("router.md", self.read("AGENTS.md"))

    def test_external_not_installed_is_an_error(self):
        store = self.store()
        self.new("graphify")
        code, out, err = self.update("my_kb=" + store)
        self.assertEqual(code, 2)
        self.assertIn("not installed", err)

    def test_hostile_external_store_is_refused(self):
        store = self.store()
        self.new("my_kb=" + store)
        before = tree_hash(self.target())
        moved = store + "-real"
        os.rename(store, moved)
        os.symlink(moved, store)
        code, out, err = self.update("my_kb=" + store)
        self.assertEqual(code, 2)
        self.assertIn("symlink", err)
        self.assertEqual(tree_hash(self.target()), before)

    def test_registered_name_at_another_path_is_refused(self):
        store = self.store()
        run(["--register", store])
        self.new("my_kb")
        os.makedirs(os.path.join(self.work, "elsewhere"))
        other = make_store(os.path.join(self.work, "elsewhere"), name="my_kb")
        code, out, err = self.update("my_kb=" + other)
        self.assertEqual(code, 2)
        self.assertIn("registered", err)

    def test_conflicting_modes_are_refused(self):
        self.new("graphify")
        for extra in (["--add", "cad"], ["--with", "cad"], ["--list"], ["--unregister", "x"],
                      ["--register", self.work], [os.path.join(self.work, "other")]):
            code, out, err = run(["--update", "--dir", self.target()] + extra)
            self.assertEqual(code, 2, extra)

    def test_not_an_installer_project_is_refused(self):
        os.makedirs(self.target())
        code, out, err = self.update()
        self.assertEqual(code, 2)
        self.assertIn(".template-manifest", err)

    def test_symlink_in_project_is_refused(self):
        self.new("graphify")
        os.symlink(self.work, self.path("link"))
        code, out, err = self.update()
        self.assertEqual(code, 2)
        self.assertIn("symlink", err)


class TemplateHistoryTest(ProjectCase):
    """Rebuilding the template as installed from git history (plan 0014)."""

    def setUp(self):
        super().setUp()
        self.tpl = os.path.join(self.work, "tpl")
        for name, value in (("ROOT", self.tpl), ("BASE_DIR", os.path.join(self.tpl, "base")),
                            ("MODULES_DIR", os.path.join(self.tpl, "modules"))):
            patcher = unittest.mock.patch.object(install, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        os.makedirs(self.tpl)
        self.tpl_git("init", "-q")
        self.tpl_write("base/docs/guide.md", "# REPLACE_WITH_PROJECT_NAME guide\n\nOne.\n\nTwo.\n")
        self.tpl_write("base/AGENTS.md",
                       "# Agents\n\nRules.\n\n<!-- @module-slot: agents-guidance -->\n")
        self.tpl_write("modules/demo/module.json", '{"description": "demo"}\n')
        self.tpl_write("modules/demo/files/docs/demo.md", "Demo v1\n")
        self.tpl_write("modules/demo/slots/agents-guidance.md", "Demo guidance v1\n")
        self.c1 = self.tpl_commit("first")

    def tpl_git(self, *argv):
        result = subprocess.run(
            ["git", "-c", "user.name=T", "-c", "user.email=t@example.invalid"] + list(argv),
            cwd=self.tpl, capture_output=True, text=True, check=True)
        return result.stdout.strip()

    def tpl_write(self, rel, text):
        path = os.path.join(self.tpl, *rel.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)

    def tpl_commit(self, message):
        self.tpl_git("add", "-A")
        self.tpl_git("commit", "-q", "-m", message)
        return self.tpl_git("rev-parse", "HEAD")

    def make(self, *extra, with_=("--with", "demo")):
        return run([self.target(), *with_, "--git-name", "Test User",
                    "--git-email", "tester@users.noreply.example.invalid", *extra])

    def manifest(self):
        return json.loads(self.read(".template-manifest"))

    def edit_manifest(self, drop=(), **changes):
        data = self.manifest()
        data.update(changes)
        for key in drop:
            data.pop(key, None)
        self.write(".template-manifest", json.dumps(data))

    def project_tree(self):
        tree = read_tree(self.target())
        tree.pop(".template-manifest")
        return tree

    def edited_guide(self):
        self.write("docs/guide.md", self.read("docs/guide.md") + "\nmine\n")

    def test_rebuilt_base_equals_what_new_wrote(self):
        self.assertEqual(self.make()[0], 0)
        tree = install.render_template_at(self.c1, ["demo"], "proj")
        self.assertEqual({k: v.decode() for k, v in tree.items()}, self.project_tree())

    def test_later_module_and_fragment_changes_do_not_alter_the_base(self):
        self.make()
        self.tpl_write("modules/demo/files/docs/demo.md", "Demo v2\n")
        self.tpl_write("modules/demo/slots/agents-guidance.md", "Demo guidance v2\n")
        c2 = self.tpl_commit("second")
        tree = install.render_template_at(self.c1, ["demo"], "proj")
        self.assertEqual({k: v.decode() for k, v in tree.items()}, self.project_tree())
        self.assertNotEqual(install.render_template_at(c2, ["demo"], "proj"), tree)

    def test_changed_template_file_is_reported_as_changed(self):
        self.make()
        self.edited_guide()
        self.tpl_write("base/docs/guide.md", "# REPLACE_WITH_PROJECT_NAME guide\n\nOne.\n\nThree.\n")
        self.tpl_commit("second")
        code, out, err = self.update()
        self.assertEqual(code, 0, err)
        self.assertIn("kept docs/guide.md", out)
        self.assertIn("template changed since %s" % self.c1[:7], out)

    def test_untouched_template_file_is_reported_as_unchanged(self):
        self.make()
        self.edited_guide()
        self.tpl_write("base/AGENTS.md",
                       "# Agents\n\nNew rules.\n\n<!-- @module-slot: agents-guidance -->\n")
        self.tpl_commit("second")
        code, out, err = self.update()
        self.assertIn("kept docs/guide.md", out)
        self.assertIn("template unchanged since %s" % self.c1[:7], out.split("docs/guide.md")[1])

    def test_missing_dirty_and_unknown_commits_say_why(self):
        self.make()
        self.edited_guide()
        for changes, reason in (
            ({"template_commit": None}, "no merge base: no template commit was recorded"),
            ({"template_commit": self.c1, "template_dirty": True},
             "no merge base: it was installed from a modified template"),
            ({"template_commit": "a" * 40, "template_dirty": False},
             "no merge base: commit " + "a" * 40 + " is not a commit in this template checkout"),
        ):
            with self.subTest(reason=reason):
                self.edit_manifest(**changes)
                code, out, err = self.update()
                self.assertEqual(code, 0, err)
                self.assertIn(reason, out)

    def test_hostile_commit_values_never_reach_git(self):
        self.make()
        self.edited_guide()
        for value in ("--output=x", "HEAD~1", "HEAD", "A" * 40, self.c1[:10], self.c1 + "\n"):
            with self.subTest(value=value):
                self.edit_manifest(template_commit=value)
                with unittest.mock.patch.object(subprocess, "run", side_effect=AssertionError("git ran")):
                    code, out, err = self.update()
                self.assertEqual(code, 0, err)
                self.assertIn("no merge base: the recorded commit is not a commit id", out)

    def test_tree_and_blob_ids_are_not_commits(self):
        self.make()
        self.edited_guide()
        for spec in (self.c1 + "^{tree}", self.c1 + ":base/docs/guide.md"):
            with self.subTest(spec=spec):
                self.edit_manifest(template_commit=self.tpl_git("rev-parse", spec))
                code, out, err = self.update()
                self.assertEqual(code, 0, err)
                self.assertIn("is not a commit in this template checkout", out)

    def test_module_added_at_a_later_commit_has_no_base(self):
        self.assertEqual(self.make(with_=())[0], 0)
        self.tpl_write("base/docs/guide.md", "# REPLACE_WITH_PROJECT_NAME guide\n\nOne.\n\nThree.\n")
        c2 = self.tpl_commit("second")
        code, out, err = run(["--add", "demo", "--dir", self.target()])
        self.assertEqual(code, 0, err)
        self.assertEqual(self.manifest()["module_commits"], {"demo": c2})
        self.assertEqual(self.manifest()["template_commit"], self.c1)
        self.edited_guide()
        code, out, err = self.update()
        self.assertIn("no merge base: module demo was added at a different commit", out)

    def test_block_problem_names_external_and_unknown_blocks(self):
        block = "<!-- BEGIN module:%s slot:s -->\nx\n<!-- END module:%s slot:s -->\n"
        self.assertIn("external module ext",
                      install.block_problem("a\n" + block % ("ext", "ext"), "a\n", {"ext"}))
        self.assertIn("demo:s is not in the installed template",
                      install.block_problem("a\n" + block % ("demo", "demo"), "a\n", set()))
        self.assertIsNone(install.block_problem("a\n" + block % ("demo", "demo"),
                                                "a\n" + block % ("demo", "demo"), set()))

    def test_explicit_name_is_recorded_and_reused(self):
        self.assertEqual(self.make("--name", "Alpha")[0], 0)
        self.assertEqual(self.manifest()["project_name"], "Alpha")
        code, out, err = self.update()
        self.assertEqual(code, 0, err)
        self.assertNotIn("kept", out)

    def test_legacy_project_without_a_name_says_it_is_assumed(self):
        self.make()
        self.edit_manifest(drop=("project_name",))
        self.edited_guide()
        code, out, err = self.update()
        self.assertIn("project name assumed from the directory", out)

    def test_unmerged_file_keeps_its_own_base_across_updates(self):
        self.make()
        self.edited_guide()
        self.tpl_write("base/docs/guide.md", "# REPLACE_WITH_PROJECT_NAME guide\n\nOne.\n\nThree.\n")
        c2 = self.tpl_commit("second")
        os.remove(self.path("docs/demo.md"))
        code, out, err = self.update()
        self.assertEqual(code, 0, err)
        self.assertIn("wrote docs/demo.md", out)
        manifest = self.manifest()
        self.assertEqual((manifest["template_commit"], manifest["file_bases"]),
                         (c2, {"docs/guide.md": self.c1}))
        self.assertNotIn("module_commits", manifest)
        code, out, err = self.update()
        self.assertIn("template changed since %s" % self.c1[:7], out)
        self.write("docs/guide.md", "# proj guide\n\nOne.\n\nThree.\n")
        os.remove(self.path("docs/demo.md"))
        code, out, err = self.update()
        self.assertEqual(code, 0, err)
        self.assertNotIn("file_bases", self.manifest())

    def test_updating_one_module_keeps_bases_it_did_not_compare(self):
        self.tpl_write("modules/other/module.json", '{"description": "other"}\n')
        self.tpl_write("modules/other/files/docs/other.md", "Other\n")
        c1 = self.tpl_commit("add other")
        self.assertEqual(self.make(with_=("--with", "demo,other"))[0], 0)
        self.edit_manifest(file_bases={"docs/demo.md": c1}, module_commits={"demo": c1, "other": c1})
        os.remove(self.path("docs/other.md"))
        code, out, err = self.update("other")
        self.assertEqual(code, 0, err)
        self.assertIn("wrote docs/other.md", out)
        manifest = self.manifest()
        self.assertEqual(manifest["file_bases"], {"docs/demo.md": c1})
        self.assertEqual(manifest["module_commits"], {"demo": c1, "other": c1})
        self.assertEqual(manifest["template_commit"], c1)
        self.assertIn("partial update", out)

    # -- --update --merge --------------------------------------------

    OLD_PLAN = "# Old plan\n\n<!-- @module-slot: plan-discovery -->\n"
    GUIDE = "# REPLACE_WITH_PROJECT_NAME guide\n\nline-a\n\nline-b\n\nline-c\n\nline-d\n\nline-e\n"

    def merge_project(self):
        """A project whose base guide has lines far enough apart to merge cleanly."""
        self.tpl_write("base/docs/guide.md", self.GUIDE)
        self.tpl_write("base/docs/plans/next.md", "# REPLACE_WITH_PLAN_TITLE\n\nStatus: Empty\n")
        self.c1 = self.tpl_commit("merge base")
        self.assertEqual(self.make()[0], 0)

    def template_guide(self, old, new):
        self.tpl_write("base/docs/guide.md", self.GUIDE.replace(old, new))
        return self.tpl_commit("template edit")

    def merge(self, *argv):
        return self.update("--merge", *argv)

    def test_merge_option_is_only_for_update(self):
        for argv in (["--merge", self.target()], ["--add", "demo", "--merge"]):
            with self.subTest(argv=argv):
                code, out, err = run(argv)
                self.assertEqual(code, 2)
                self.assertIn("--merge", err)

    def test_report_alone_never_writes_a_merge(self):
        self.merge_project()
        self.template_guide("line-a", "line-a new")
        before = tree_hash(self.target())
        code, out, err = self.update()
        self.assertIn("kept docs/guide.md", out)
        self.assertEqual(tree_hash(self.target()), before)

    def test_unmodified_file_takes_the_new_template_text(self):
        self.merge_project()
        self.template_guide("line-a", "line-a new")
        code, out, err = self.merge()
        self.assertEqual(code, 0, err)
        self.assertIn("updated docs/guide.md", out)
        self.assertEqual(self.read("docs/guide.md"), self.GUIDE.replace("line-a", "line-a new")
                         .replace("REPLACE_WITH_PROJECT_NAME", "proj"))

    def test_edits_that_do_not_overlap_are_merged(self):
        self.merge_project()
        self.write("docs/guide.md", self.read("docs/guide.md").replace("line-e", "line-e mine"))
        self.template_guide("line-a", "line-a new")
        code, out, err = self.merge()
        self.assertEqual(code, 0, err)
        self.assertIn("merged docs/guide.md", out)
        text = self.read("docs/guide.md")
        self.assertIn("line-a new", text)
        self.assertIn("line-e mine", text)
        self.assertNotIn("<<<<<<<", text)

    def test_overlapping_edits_leave_the_file_alone_and_keep_its_base(self):
        self.merge_project()
        mine = self.read("docs/guide.md").replace("line-a", "line-a mine")
        self.write("docs/guide.md", mine)
        c2 = self.template_guide("line-a", "line-a new")
        os.remove(self.path("docs/demo.md"))
        code, out, err = self.merge()
        self.assertEqual(code, 0, err)
        self.assertIn("conflict docs/guide.md", out)
        self.assertEqual(self.read("docs/guide.md"), mine)
        manifest = self.manifest()
        self.assertEqual((manifest["template_commit"], manifest["file_bases"]),
                         (c2, {"docs/guide.md": self.c1}))

    def test_file_without_a_base_is_left_alone(self):
        self.merge_project()
        self.template_guide("line-a", "line-a new")
        self.edit_manifest(template_commit=None)
        before = self.read("docs/guide.md")
        code, out, err = self.merge()
        self.assertEqual(code, 0, err)
        self.assertEqual(self.read("docs/guide.md"), before)
        self.assertIn("no merge base", out)

    def test_active_plan_is_only_replaced_when_unmodified(self):
        self.merge_project()
        self.tpl_write("base/docs/plans/next.md",
                       "# REPLACE_WITH_PLAN_TITLE\n\nStatus: Empty\nNew line\n")
        self.tpl_commit("plan template")
        code, out, err = self.merge()
        self.assertIn("updated docs/plans/next.md", out)
        self.assertIn("New line", self.read("docs/plans/next.md"))
        self.write("docs/plans/next.md", "# My plan\n\nStatus: Proposed\nNew line\n")
        self.tpl_write("base/docs/plans/next.md",
                       "# REPLACE_WITH_PLAN_TITLE\n\nStatus: Empty\nNewer line\n")
        self.tpl_commit("plan template again")
        code, out, err = self.merge()
        self.assertEqual(self.read("docs/plans/next.md"),
                         "# My plan\n\nStatus: Proposed\nNew line\n")

    def test_dry_run_merge_writes_nothing_and_a_second_run_is_a_noop(self):
        self.merge_project()
        self.write("docs/guide.md", self.read("docs/guide.md").replace("line-e", "line-e mine"))
        self.template_guide("line-a", "line-a new")
        before = tree_hash(self.target())
        code, out, err = self.merge("--dry-run")
        self.assertIn("merged docs/guide.md", out)
        self.assertIn("would write docs/guide.md", out)
        self.assertEqual(tree_hash(self.target()), before)
        self.assertEqual(self.merge()[0], 0)
        merged = tree_hash(self.target())
        code, out, err = self.merge()
        self.assertIn("Nothing to update", out)
        self.assertEqual(tree_hash(self.target()), merged)
        self.assertNotIn("file_bases", self.manifest())

    def test_file_that_already_has_the_template_change_is_reported_current(self):
        self.merge_project()
        self.template_guide("line-a", "line-a new")
        self.write("docs/guide.md", self.read("docs/guide.md").replace("line-a", "line-a new") + "\nmine\n")
        before = tree_hash(self.target())
        code, out, err = self.merge()
        self.assertIn("current docs/guide.md (already contains the template's changes)", out)
        self.assertEqual(tree_hash(self.target()), before)

    def test_project_created_files_are_never_merged(self):
        self.merge_project()
        self.write("docs/plans/0001-old.md", self.OLD_PLAN)
        self.template_guide("line-a", "line-a new")
        code, out, err = self.merge()
        self.assertEqual(self.read("docs/plans/0001-old.md"), self.OLD_PLAN)
        self.assertIn("skipped docs/plans/0001-old.md", out)

    def test_merge_needs_a_recorded_or_given_project_name(self):
        self.merge_project()
        self.template_guide("line-a", "line-a new")
        self.edit_manifest(drop=("project_name",))
        before = tree_hash(self.target())
        code, out, err = self.merge()
        self.assertEqual(code, 2)
        self.assertIn("--name", err)
        self.assertEqual(tree_hash(self.target()), before)
        code, out, err = self.merge("--name", "proj")
        self.assertEqual(code, 0, err)
        self.assertIn("updated docs/guide.md", out)

    def test_partial_update_does_not_advance_the_base(self):
        self.tpl_write("modules/other/module.json", '{"description": "other"}\n')
        self.tpl_write("modules/other/files/docs/other.md",
                       "o1\n\no2\n\no3\n\no4\n\no5\n")
        c1 = self.tpl_commit("add other")
        self.assertEqual(self.make(with_=("--with", "demo,other"))[0], 0)
        self.write("docs/other.md", self.read("docs/other.md").replace("o5", "o5 mine"))
        self.tpl_write("modules/other/files/docs/other.md",
                       "o1 C2\n\no2\n\no3\n\no4\n\no5\n")
        self.tpl_commit("second")
        os.remove(self.path("docs/demo.md"))
        code, out, err = self.update("demo")
        self.assertIn("wrote docs/demo.md", out)
        self.assertEqual(self.manifest()["template_commit"], c1)
        self.tpl_write("modules/other/files/docs/other.md",
                       "o1 C2\n\no2\n\no3 C3\n\no4\n\no5\n")
        self.tpl_commit("third")
        code, out, err = self.merge()
        self.assertEqual(code, 0, err)
        text = self.read("docs/other.md")
        for expected in ("o1 C2", "o3 C3", "o5 mine"):
            self.assertIn(expected, text)

    def test_file_with_no_base_stays_without_one_after_the_commit_advances(self):
        self.merge_project()
        self.edit_manifest(template_dirty=True)
        self.write("docs/guide.md", self.read("docs/guide.md").replace("line-e", "line-e mine"))
        self.template_guide("line-a", "line-a new")
        os.remove(self.path("docs/demo.md"))
        code, out, err = self.update()
        self.assertIn("installed from a modified template", out)
        self.assertEqual(self.manifest()["file_bases"], {"docs/guide.md": None})
        self.edit_manifest(template_dirty=False)
        self.template_guide("line-b", "line-b new")
        before = self.read("docs/guide.md")
        code, out, err = self.merge()
        self.assertEqual(self.read("docs/guide.md"), before)
        self.assertIn("no merge base", out)

    def test_non_string_commits_are_reported_not_crashed_on(self):
        self.make()
        self.edited_guide()
        for value in ([1], {"a": 1}, True, 5.5, 0, ""):
            with self.subTest(value=value):
                self.edit_manifest(template_commit=value)
                code, out, err = self.update()
                self.assertEqual(code, 0, err)
                self.assertIn("no merge base", out)

    def test_block_of_a_module_the_template_dropped_is_not_lost_by_merge(self):
        self.make()
        self.write("AGENTS.md", self.read("AGENTS.md").replace("Rules.", "Rules mine."))
        shutil.rmtree(os.path.join(self.tpl, "modules", "demo"))
        self.tpl_write("base/AGENTS.md",
                       "# Agents\n\nNew rules.\n\n<!-- @module-slot: agents-guidance -->\n")
        self.tpl_commit("drop demo")
        before = self.read("AGENTS.md")
        code, out, err = self.merge()
        self.assertEqual(code, 0, err)
        self.assertEqual(self.read("AGENTS.md"), before)
        self.assertIn("would drop the block demo:agents-guidance", out)

    def test_hostile_old_module_definitions_are_no_base_not_a_crash(self):
        self.make()
        self.edited_guide()
        for name, data in (("module.json", b'{"requires": 5}'),
                           ("slots/agents-guidance.md", b"\xff\xfe")):
            with self.subTest(name=name):
                path = os.path.join(self.tpl, "modules", "demo", *name.split("/"))
                original = open(path, "rb").read()
                with open(path, "wb") as handle:
                    handle.write(data)
                commit = self.tpl_commit("hostile " + name)
                with open(path, "wb") as handle:
                    handle.write(original)
                self.tpl_commit("restore")
                self.edit_manifest(template_commit=commit)
                code, out, err = self.update()
                self.assertEqual(code, 0, err)
                self.assertIn("no merge base: it cannot be rebuilt", out)

    def test_oversized_blob_is_refused_before_it_is_read(self):
        self.make()
        with unittest.mock.patch.object(install, "MAX_FILE_BYTES", 5):
            with self.assertRaises(install.NoBase) as caught:
                install.read_template_at(self.c1)
        self.assertIn("too large", str(caught.exception))

    def test_installer_must_sit_at_the_top_of_its_checkout(self):
        self.make()
        with unittest.mock.patch.object(install, "ROOT", os.path.join(self.tpl, "modules")):
            with self.assertRaises(install.NoBase) as caught:
                install.verified_commit(self.c1)
        self.assertIn("top of a git checkout", str(caught.exception))

    def test_merge_cannot_be_limited_to_named_modules(self):
        self.merge_project()
        code, out, err = self.update("demo", "--merge")
        self.assertEqual(code, 2)
        self.assertIn("--merge", err)

    def test_merge_rejected_by_block_refresh_is_not_written(self):
        self.make()
        self.write("AGENTS.md", self.read("AGENTS.md").replace("Rules.", "Rules mine."))
        self.tpl_write("base/AGENTS.md",
                       "# Agents\n\nRules.\n\nMore.\n\n<!-- @module-slot: agents-guidance -->\n")
        self.tpl_commit("more")
        before = self.read("AGENTS.md")
        with unittest.mock.patch.object(install, "refresh_blocks", side_effect=ValueError("bad layout")):
            code, out, err = self.merge()
        self.assertEqual(code, 0, err)
        self.assertEqual(self.read("AGENTS.md"), before)
        self.assertIn("kept AGENTS.md", out)

    def test_malformed_optional_manifest_keys_are_refused(self):
        self.make()
        for changes in ({"file_bases": []}, {"file_bases": {"../x": "a" * 40}},
                        {"file_bases": {"a": "A" * 40}}, {"file_bases": {"a": 5}},
                        {"module_commits": {"demo": "zz"}},
                        {"module_commits": []}, {"project_name": 5}):
            with self.subTest(changes=changes):
                self.edit_manifest(**changes)
                code, out, err = self.update()
                self.assertEqual(code, 2)
                self.assertIn("malformed", err)


class RemoveTest(ProjectCase):
    def remove(self, *argv, extra=()):
        return run(["--remove"] + list(argv) + ["--dir", self.target()] + list(extra))

    def snapshot(self, with_):
        """Create a project in its own directory and return its files minus the manifest."""
        parent = os.path.join(self.work, "snap-" + with_.replace(",", "-"))
        os.makedirs(parent)
        target = os.path.join(parent, "proj")
        code, out, err = run([target, "--with", with_, "--git-name", "Test User",
                              "--git-email", "tester@users.noreply.example.invalid"])
        self.assertEqual(code, 0, err)
        tree = read_tree(target)
        tree.pop(".template-manifest")
        return tree

    def files(self):
        tree = read_tree(self.target())
        return tree.pop(".template-manifest"), tree

    def manifest(self):
        return json.loads(self.read(".template-manifest"))

    def store(self, **kwargs):
        return make_store(self.work, **kwargs)

    def test_remove_matches_a_project_created_without_the_module(self):
        self.assertEqual(self.new("claude,graphify")[0], 0)
        code, out, err = self.remove("graphify")
        self.assertEqual(code, 0, err)
        _, tree = self.files()
        self.assertEqual(tree, self.snapshot("claude"))
        self.assertEqual(self.manifest()["modules"], ["claude"])
        self.assertFalse(os.path.lexists(self.path(".graphifyignore")))

    def test_add_then_remove_restores_the_project(self):
        self.assertEqual(self.new("claude")[0], 0)
        before = self.files()[1]
        self.assertEqual(run(["--add", "cad", "graphify", "--dir", self.target()])[0], 0)
        self.assertEqual(self.remove("cad", "graphify")[0], 0)
        self.assertEqual(self.files()[1], before)
        self.assertFalse(os.path.lexists(self.path("docs/cad.md")))

    def test_empty_directories_are_pruned_but_not_others(self):
        self.assertEqual(self.new("claude,cad")[0], 0)
        self.assertEqual(self.remove("claude")[0], 0)
        self.assertFalse(os.path.lexists(self.path(".claude")))
        self.assertTrue(os.path.isdir(self.path("docs")))
        self.assertTrue(os.path.isdir(self.path(".git")))

    def test_edited_module_file_is_kept_and_reported(self):
        self.assertEqual(self.new("claude,graphify")[0], 0)
        self.write(".graphifyignore", "mine\n")
        code, out, err = self.remove("graphify")
        self.assertEqual(code, 0, err)
        self.assertIn("kept .graphifyignore", out)
        self.assertEqual(self.read(".graphifyignore"), "mine\n")
        self.assertNotIn("module:graphify", self.read("AGENTS.md"))
        self.assertEqual(self.manifest()["modules"], ["claude"])

    def test_dependent_module_blocks_removal(self):
        self.assertEqual(self.new("cad-freecad")[0], 0)
        before = tree_hash(self.target())
        code, out, err = self.remove("cad")
        self.assertEqual(code, 2)
        self.assertIn("cad-freecad", err)
        self.assertEqual(tree_hash(self.target()), before)

    def test_naming_module_and_dependent_removes_both(self):
        self.assertEqual(self.new("cad-freecad,claude")[0], 0)
        self.assertEqual(self.remove("cad", "cad-freecad")[0], 0)
        _, tree = self.files()
        self.assertEqual(tree, self.snapshot("claude"))

    def test_removing_the_dependent_alone_keeps_the_module(self):
        self.assertEqual(self.new("cad-freecad,claude")[0], 0)
        self.assertEqual(self.remove("cad-freecad")[0], 0)
        _, tree = self.files()
        self.assertEqual(tree, self.snapshot("cad,claude"))

    def test_not_installed_is_an_error(self):
        self.assertEqual(self.new("claude")[0], 0)
        before = tree_hash(self.target())
        for name in ("graphify", "no-such", "kb=/tmp/x", "../x"):
            with self.subTest(name=name):
                code, out, err = self.remove(name)
                self.assertEqual(code, 2)
                self.assertIn("not installed", err)
        self.assertEqual(tree_hash(self.target()), before)

    def test_malformed_markers_stop_the_run_with_nothing_written(self):
        self.assertEqual(self.new("claude,graphify,formal")[0], 0)
        lines, begin, end = UpdateTest.block_lines(self, "AGENTS.md", "graphify", "agents-guidance")
        del lines[end]
        self.write("AGENTS.md", "\n".join(lines))
        before = tree_hash(self.target())
        code, out, err = self.remove("graphify", "formal")
        self.assertEqual(code, 2)
        self.assertIn("AGENTS.md", err)
        self.assertEqual(tree_hash(self.target()), before)

    def test_unrelated_malformed_file_does_not_block_removal(self):
        self.assertEqual(self.new("claude,graphify,plan-review")[0], 0)
        rel = "docs/plans/README.md"
        lines, begin, end = UpdateTest.block_lines(self, rel, "plan-review", "plans-review-note")
        del lines[end]
        self.write(rel, "\n".join(lines))
        code, out, err = self.remove("graphify")
        self.assertEqual(code, 0, err)
        self.assertFalse(os.path.lexists(self.path(".graphifyignore")))

    def test_dry_run_writes_and_deletes_nothing(self):
        self.assertEqual(self.new("claude,graphify")[0], 0)
        before = tree_hash(self.target())
        code, out, err = self.remove("graphify", extra=["--dry-run"])
        self.assertEqual(code, 0, err)
        self.assertIn("would delete .graphifyignore", out)
        self.assertIn("would write AGENTS.md", out)
        self.assertIn("Dry run", out)
        self.assertEqual(tree_hash(self.target()), before)

    def test_conflicting_modes(self):
        self.assertEqual(self.new("claude,graphify")[0], 0)
        before = tree_hash(self.target())
        for extra in (["--add", "cad"], ["--update"], ["--with", "cad"], ["--list"],
                      ["--register", self.work], ["--unregister", "x"], [self.work + "/other"]):
            with self.subTest(extra=extra):
                code, out, err = run(["--remove", "graphify", "--dir", self.target()] + extra)
                self.assertEqual(code, 2)
        for extra in (["--add", "cad"], ["--update"]):
            with self.subTest(order=extra):
                code, out, err = run(extra + ["--remove", "graphify", "--dir", self.target()])
                self.assertNotEqual(code, 0)
        self.assertEqual(tree_hash(self.target()), before)

    def test_not_an_installer_project(self):
        os.makedirs(self.target())
        code, out, err = self.remove("graphify")
        self.assertEqual(code, 2)
        self.assertIn(".template-manifest", err)

    def test_symlink_in_project_is_refused(self):
        self.assertEqual(self.new("claude,graphify")[0], 0)
        os.symlink("AGENTS.md", self.path("link"))
        before = tree_hash(self.target())
        code, out, err = self.remove("graphify")
        self.assertEqual(code, 2)
        self.assertEqual(tree_hash(self.target()), before)

    def test_parent_swapped_for_a_symlink_after_the_check_is_refused(self):
        self.assertEqual(self.new("claude,cad")[0], 0)
        outside = os.path.join(self.work, "outside")
        os.makedirs(outside)
        victim = os.path.join(outside, "cad.md")
        shutil.copy(self.path("docs/cad.md"), victim)
        original = install.check_write_paths

        def swapped(root, rels):
            original(root, rels)
            os.rename(self.path("docs"), self.path("docs.moved"))
            os.symlink(outside, self.path("docs"))

        install.check_write_paths = swapped
        self.addCleanup(setattr, install, "check_write_paths", original)
        code, out, err = self.remove("cad")
        self.assertEqual(code, 2)
        self.assertTrue(os.path.exists(victim))

    def test_without_safe_deletion_files_are_kept(self):
        self.assertEqual(self.new("claude,graphify")[0], 0)
        saved = install.can_delete_safely
        install.can_delete_safely = lambda: False
        self.addCleanup(setattr, install, "can_delete_safely", saved)
        code, out, err = self.remove("graphify")
        self.assertEqual(code, 0, err)
        self.assertIn("kept .graphifyignore", out)
        self.assertTrue(os.path.exists(self.path(".graphifyignore")))
        self.assertNotIn("module:graphify", self.read("AGENTS.md"))

    def test_module_no_longer_provided_keeps_files(self):
        root = os.path.join(self.work, "fake-modules")
        shutil.copytree(os.path.join(install.MODULES_DIR), root)
        saved = install.MODULES_DIR
        install.MODULES_DIR = root
        self.addCleanup(setattr, install, "MODULES_DIR", saved)
        self.assertEqual(self.new("claude,graphify")[0], 0)
        shutil.rmtree(os.path.join(root, "graphify"))
        code, out, err = self.remove("graphify")
        self.assertEqual(code, 0, err)
        self.assertIn("no longer provided", out)
        self.assertTrue(os.path.exists(self.path(".graphifyignore")))
        self.assertNotIn("module:graphify", self.read("AGENTS.md"))
        self.assertEqual(self.manifest()["modules"], ["claude"])

    def test_edited_block_stops_the_run_with_nothing_written(self):
        self.assertEqual(self.new("claude,graphify,formal")[0], 0)
        lines, begin, end = UpdateTest.block_lines(self, "AGENTS.md", "graphify", "agents-guidance")
        edited = lines[:end] + ["my own note"] + lines[end:]
        moved = [lines[begin]] + lines[:begin] + lines[begin + 1:]
        for label, content in (("line added", edited), ("BEGIN moved up", moved)):
            with self.subTest(label):
                self.write("AGENTS.md", "\n".join(content))
                before = tree_hash(self.target())
                code, out, err = self.remove("graphify")
                self.assertEqual(code, 2)
                self.assertIn("--update", err)
                self.assertEqual(tree_hash(self.target()), before)

    def test_crlf_file_with_blocks_stops_the_run(self):
        self.assertEqual(self.new("claude,graphify")[0], 0)
        with open(self.path("AGENTS.md"), "rb") as handle:
            data = handle.read()
        with open(self.path("AGENTS.md"), "wb") as handle:
            handle.write(data.replace(b"\n", b"\r\n"))
        before = tree_hash(self.target())
        code, out, err = self.remove("graphify")
        self.assertEqual(code, 2)
        self.assertIn("AGENTS.md", err)
        self.assertEqual(tree_hash(self.target()), before)
        self.assertIn("graphify", self.manifest()["modules"])

    def test_skipped_entries_are_called_out(self):
        self.assertEqual(self.new("claude,graphify")[0], 0)
        os.symlink("AGENTS.md", self.path("link"))
        code, out, err = self.remove("graphify", extra=["--skip-unsafe-entries"])
        self.assertEqual(code, 0, err)
        self.assertIn("may still hold", out)

    def modules_copy(self):
        root = os.path.join(self.work, "fake-modules")
        shutil.copytree(install.MODULES_DIR, root)
        saved = install.MODULES_DIR
        install.MODULES_DIR = root
        self.addCleanup(setattr, install, "MODULES_DIR", saved)
        return root

    def test_module_claiming_a_base_file_does_not_delete_it(self):
        self.assertEqual(self.new("claude,graphify")[0], 0)
        root = self.modules_copy()
        with open(self.path("CONTRIBUTING.md"), "rb") as handle:
            data = handle.read()
        with open(os.path.join(root, "graphify", "files", "CONTRIBUTING.md"), "wb") as handle:
            handle.write(data)
        code, out, err = self.remove("graphify")
        self.assertEqual(code, 0, err)
        self.assertTrue(os.path.exists(self.path("CONTRIBUTING.md")))

    def test_file_shipped_by_two_removed_modules_is_deleted_once(self):
        self.assertEqual(self.new("claude,graphify,formal")[0], 0)
        root = self.modules_copy()
        for name in ("graphify", "formal"):
            os.makedirs(os.path.join(root, name, "files"), exist_ok=True)
            with open(os.path.join(root, name, "files", "shared.txt"), "w") as handle:
                handle.write("same\n")
        self.write("shared.txt", "same\n")
        code, out, err = self.remove("graphify", "formal")
        self.assertEqual(code, 0, err)
        self.assertFalse(os.path.lexists(self.path("shared.txt")))
        self.assertEqual(self.manifest()["modules"], ["claude"])

    # -- external modules -----------------------------------------------

    def test_external_module_is_removed_without_its_store(self):
        store = self.store()
        self.assertEqual(self.new("claude,my_kb=" + store)[0], 0)
        shutil.rmtree(store)
        code, out, err = self.remove("my_kb")
        self.assertEqual(code, 0, err)
        manifest = self.manifest()
        self.assertEqual(manifest["modules"], ["claude"])
        self.assertNotIn("external_modules", manifest)
        _, tree = self.files()
        self.assertEqual(tree, self.snapshot("claude"))

    def test_removal_keeps_other_external_entries(self):
        self.assertEqual(self.new("claude,a=" + self.store(name="one") + ",b=" + self.store(name="two"))[0], 0)
        kept = self.manifest()["external_modules"]["b"]
        self.assertEqual(self.remove("a")[0], 0)
        manifest = self.manifest()
        self.assertEqual(manifest["external_modules"], {"b": kept})
        self.assertNotIn("module:a ", self.read("AGENTS.md"))
        self.assertIn("module:b ", self.read("AGENTS.md"))

    def test_builtin_and_external_removed_together(self):
        self.assertEqual(self.new("claude,graphify,my_kb=" + self.store())[0], 0)
        self.assertEqual(self.remove("graphify", "my_kb")[0], 0)
        _, tree = self.files()
        self.assertEqual(tree, self.snapshot("claude"))

    def test_registry_is_not_consulted_or_changed(self):
        store = self.store()
        self.assertEqual(run(["--register", store])[0], 0)
        self.assertEqual(self.new("claude,my_kb")[0], 0)
        registry = os.path.join(self.work, "xdg", "claude-project-template", "registry.json")
        with open(registry, "rb") as handle:
            before = handle.read()
        self.assertEqual(self.remove("my_kb")[0], 0)
        with open(registry, "rb") as handle:
            self.assertEqual(handle.read(), before)


class ModuleInfoTest(ProjectCase):
    KB = {"description": "kb", "type": "knowledge-base",
          "paths": {"store": "docs/kb"}, "data": {"format": 1}}

    def setUp(self):
        super().setUp()
        self.root = os.path.join(self.work, "info-modules")
        self.module("kb", self.KB)
        self.module("plain", {"description": "plain"})
        saved = install.MODULES_DIR
        install.MODULES_DIR = self.root
        self.addCleanup(setattr, install, "MODULES_DIR", saved)

    def module(self, name, meta):
        os.makedirs(os.path.join(self.root, name), exist_ok=True)
        with open(os.path.join(self.root, name, "module.json"), "w") as handle:
            json.dump(meta, handle)

    def manifest(self):
        return json.loads(self.read(".template-manifest"))

    def set_manifest(self, **changes):
        manifest = self.manifest()
        manifest.update(changes)
        self.write(".template-manifest", json.dumps(manifest))

    def test_new_records_only_declaring_modules(self):
        self.assertEqual(self.new("kb,plain")[0], 0)
        self.assertEqual(self.manifest()["module_info"], {
            "kb": {"type": "knowledge-base", "paths": {"store": "docs/kb"},
                   "data": {"format": 1}}})

    def test_no_declaring_module_means_no_key(self):
        self.assertEqual(self.new("plain")[0], 0)
        self.assertNotIn("module_info", self.manifest())

    def test_partial_declaration_records_only_what_is_declared(self):
        self.module("kb", {"description": "kb", "type": "knowledge-base"})
        self.assertEqual(self.new("kb")[0], 0)
        self.assertEqual(self.manifest()["module_info"], {"kb": {"type": "knowledge-base"}})

    def test_add_records_new_declaring_modules_and_keeps_others(self):
        self.new("plain")
        code, out, err = run(["--add", "kb", "--dir", self.target()])
        self.assertEqual(code, 0, err)
        self.assertEqual(list(self.manifest()["module_info"]), ["kb"])
        self.module("other", {"description": "o", "type": "other-kind"})
        self.module("kb", dict(self.KB, data={"format": 2}))
        code, out, err = run(["--add", "other", "--dir", self.target()])
        self.assertEqual(code, 0, err)
        info = self.manifest()["module_info"]
        self.assertEqual(info["kb"]["data"], {"format": 1})
        self.assertEqual(info["other"], {"type": "other-kind"})

    def test_remove_drops_the_entry_and_then_the_key(self):
        self.new("kb,plain")
        self.module("other", {"description": "o", "type": "other-kind"})
        run(["--add", "other", "--dir", self.target()])
        self.assertEqual(run(["--remove", "kb", "--dir", self.target()])[0], 0)
        self.assertEqual(list(self.manifest()["module_info"]), ["other"])
        self.assertEqual(run(["--remove", "other", "--dir", self.target()])[0], 0)
        self.assertNotIn("module_info", self.manifest())

    def test_full_update_refreshes_metadata_only_change(self):
        self.new("kb,plain")
        self.module("kb", dict(self.KB, paths={"store": "docs/kb", "index": "docs/kb/i.md"}))
        before = self.manifest()
        code, out, err = self.update("--dry-run")
        self.assertEqual(code, 0, err)
        self.assertNotIn("Nothing to update", out)
        self.assertIn("would write .template-manifest", out)
        self.assertEqual(self.manifest(), before)
        code, out, err = self.update()
        self.assertEqual(code, 0, err)
        self.assertNotIn("Nothing to update", out)
        self.assertEqual(self.manifest()["module_info"]["kb"]["paths"],
                         {"store": "docs/kb", "index": "docs/kb/i.md"})

    def test_full_update_adds_and_drops_entries(self):
        self.new("kb,plain")
        self.module("kb", {"description": "kb"})
        self.assertEqual(self.update()[0], 0)
        self.assertNotIn("module_info", self.manifest())
        self.module("kb", self.KB)
        self.assertEqual(self.update()[0], 0)
        self.assertIn("kb", self.manifest()["module_info"])

    def test_named_module_update_leaves_module_info(self):
        self.new("kb,plain")
        self.module("kb", dict(self.KB, data={"format": 9}))
        before = self.read(".template-manifest")
        code, out, err = self.update("plain")
        self.assertEqual(code, 0, err)
        self.assertIn("Nothing to update", out)
        self.assertEqual(self.read(".template-manifest"), before)

    def test_unchanged_info_is_a_noop(self):
        self.new("kb,plain")
        before = tree_hash(self.target())
        code, out, err = self.update()
        self.assertIn("Nothing to update", out)
        self.assertEqual(tree_hash(self.target()), before)

    def test_entry_of_a_module_the_template_dropped_is_kept(self):
        self.new("kb,plain")
        before = self.manifest()["module_info"]
        shutil.rmtree(os.path.join(self.root, "kb"))
        self.assertEqual(self.update()[0], 0)
        self.assertEqual(self.manifest()["module_info"], before)

    def test_older_manifest_without_the_key_loads(self):
        self.new("plain")
        self.assertEqual(self.update()[0], 0)
        self.assertEqual(run(["--add", "kb", "--dir", self.target()])[0], 0)

    def test_hostile_module_info_is_refused_on_load(self):
        self.new("kb,plain")
        deep = {}
        node = deep
        for _ in range(8):
            node["d"] = {}
            node = node["d"]
        bad_values = [
            [], "x", {"kb": []}, {"kb": {}}, {"kb": {"extra": 1}},
            {"kb": {"type": 5}}, {"kb": {"paths": {"s": "../x"}}},
            {"kb": {"paths": {"s": "/abs"}}}, {"kb": {"data": deep}},
            {"kb": {"paths": {"s": "a\\b"}}}, {"kb": {"paths": {"s": "C:x"}}},
            {"kb": {"paths": {"s": ".git /x"}}},
            {"kb": {"data": {"k": "bell\x07"}}}, {"Bad Name": {"type": "x"}},
            {"missing": {"type": "x"}},
        ]
        for bad in bad_values:
            with self.subTest(bad=repr(bad)[:60]):
                self.set_manifest(module_info=bad)
                code, out, err = self.update()
                self.assertEqual(code, 2)
                self.assertIn("module_info", err)

    def test_oversized_module_info_is_refused(self):
        self.new("kb,plain")
        self.set_manifest(module_info={"kb%d" % i: {"type": "t"}
                                       for i in range(install.MANIFEST_MAP_MAX + 1)})
        code, out, err = self.update()
        self.assertEqual(code, 2)


FORMAT_TWO_MODULE = json.dumps({
    "module_format": 2, "description": "Fixture store", "type": "knowledge-base",
    "paths": {"index": "docs/kb/index.md"}, "data": {"kinds": ["note"]},
}).encode()


class ExternalModuleInfoTest(ProjectCase):
    def store(self, **kwargs):
        return make_store(self.work, **kwargs)

    def manifest(self):
        return json.loads(self.read(".template-manifest"))

    def set_manifest(self, manifest):
        self.write(".template-manifest", json.dumps(manifest))

    def add(self, entry):
        return run(["--add", entry, "--dir", self.target()])

    def test_store_ok_accepts_only_the_two_forms(self):
        for good in ("../my_kb", "../kb.v2", "/srv/kb", "/Users/me/projects/my_kb"):
            with self.subTest(good=good):
                self.assertTrue(install.store_ok(good))
        for bad in ("", ".", "..", "./name", "foo/bar", "../a/b", "../..", "../", "../.",
                    "/", "//x", "/a//b", "/a/", "/a/../b", "/a/./b", "../.git", "/x/.git",
                    "/x/.git /y", "../a\\b", "../a:b", "/a\\b", "C:/x", "../\x07",
                    "../" + "a" * 600, 5, None, ["../x"]):
            with self.subTest(bad=bad if not isinstance(bad, str) else bad[:20]):
                self.assertFalse(install.store_ok(bad))

    def test_format_one_external_records_only_its_store(self):
        self.assertEqual(self.new("my_kb=" + self.store())[0], 0)
        self.assertEqual(self.manifest()["module_info"], {"my_kb": {"store": "../my_kb"}})

    def test_format_two_external_records_declared_info_and_store(self):
        self.assertEqual(self.new("my_kb=" + self.store(module=FORMAT_TWO_MODULE))[0], 0)
        self.assertEqual(self.manifest()["module_info"], {"my_kb": {
            "store": "../my_kb", "type": "knowledge-base",
            "paths": {"index": "docs/kb/index.md"}, "data": {"kinds": ["note"]}}})

    def test_store_elsewhere_is_recorded_absolute(self):
        elsewhere = os.path.join(self.work, "elsewhere")
        os.makedirs(elsewhere)
        store = make_store(elsewhere)
        self.assertEqual(self.new("my_kb=" + store)[0], 0)
        self.assertEqual(self.manifest()["module_info"]["my_kb"]["store"], os.path.realpath(store))

    def test_builtin_only_project_has_no_module_info(self):
        self.assertEqual(self.new("graphify")[0], 0)
        self.assertNotIn("module_info", self.manifest())

    def test_add_records_the_external_and_keeps_other_entries(self):
        self.assertEqual(self.new("graphify")[0], 0)
        code, out, err = self.add("my_kb=" + self.store(module=FORMAT_TWO_MODULE))
        self.assertEqual(code, 0, err)
        self.assertEqual(list(self.manifest()["module_info"]), ["my_kb"])
        other = make_store(self.work, name="second")
        self.assertEqual(self.add("second=" + other)[0], 0)
        info = self.manifest()["module_info"]
        self.assertEqual(sorted(info), ["my_kb", "second"])
        self.assertEqual(info["second"], {"store": "../second"})

    def test_remove_drops_the_entry_and_then_the_key(self):
        self.new("my_kb=" + self.store())
        self.assertEqual(run(["--add", "second=" + make_store(self.work, name="second"),
                              "--dir", self.target()])[0], 0)
        self.assertEqual(run(["--remove", "my_kb", "--dir", self.target()])[0], 0)
        self.assertEqual(list(self.manifest()["module_info"]), ["second"])
        self.assertEqual(run(["--remove", "second", "--dir", self.target()])[0], 0)
        self.assertNotIn("module_info", self.manifest())

    def test_named_update_adds_a_missing_store_for_an_unchanged_descriptor(self):
        store = self.store()
        self.new("my_kb=" + store)
        manifest = self.manifest()
        del manifest["module_info"]
        self.set_manifest(manifest)
        code, out, err = self.update("my_kb=" + store, "--dry-run")
        self.assertEqual(code, 0, err)
        self.assertIn("would write .template-manifest", out)
        self.assertNotIn("module_info", self.manifest())
        self.assertEqual(self.update("my_kb=" + store)[0], 0)
        self.assertEqual(self.manifest()["module_info"], {"my_kb": {"store": "../my_kb"}})

    def test_full_update_corrects_a_stale_store(self):
        store = self.store()
        self.assertEqual(run(["--register", store])[0], 0)
        self.new("my_kb")
        manifest = self.manifest()
        manifest["module_info"]["my_kb"]["store"] = "../old"
        self.set_manifest(manifest)
        code, out, err = self.update()
        self.assertEqual(code, 0, err)
        self.assertNotIn("Nothing to update", out)
        self.assertEqual(self.manifest()["module_info"]["my_kb"]["store"], "../my_kb")

    def test_update_refreshes_declared_info(self):
        store = self.store(module=FORMAT_TWO_MODULE)
        self.new("my_kb=" + store)
        changed = json.loads(FORMAT_TWO_MODULE)
        changed["data"] = {"kinds": ["note", "page"]}
        with open(os.path.join(store, "template-module", "module.json"), "w") as handle:
            json.dump(changed, handle)
        self.assertEqual(self.update("my_kb=" + store)[0], 0)
        self.assertEqual(self.manifest()["module_info"]["my_kb"]["data"],
                         {"kinds": ["note", "page"]})

    def test_unverifiable_external_keeps_its_entry_on_full_update(self):
        self.new("graphify,my_kb=" + self.store(module=FORMAT_TWO_MODULE))
        before = self.manifest()["module_info"]
        code, out, err = self.update()
        self.assertEqual(code, 0, err)
        self.assertIn("skipped", out)
        self.assertEqual(self.manifest()["module_info"], before)

    def test_unchanged_external_is_a_noop(self):
        store = self.store(module=FORMAT_TWO_MODULE)
        self.new("my_kb=" + store)
        before = tree_hash(self.target())
        code, out, err = self.update("my_kb=" + store)
        self.assertIn("Nothing to update", out)
        self.assertEqual(tree_hash(self.target()), before)

    def test_hostile_external_entries_are_refused_on_load(self):
        self.new("graphify,my_kb=" + self.store())
        deep = {}
        node = deep
        for _ in range(8):
            node["d"] = {}
            node = node["d"]
        bad_values = [
            {"my_kb": {}}, {"my_kb": {"type": "x"}}, {"my_kb": {"store": 5}},
            {"my_kb": {"store": "foo/bar"}}, {"my_kb": {"store": "../a/b"}},
            {"my_kb": {"store": "."}}, {"my_kb": {"store": ""}},
            {"my_kb": {"store": "../.git"}}, {"my_kb": {"store": "../a\\b"}},
            {"my_kb": {"store": "../" + "a" * 600}},
            {"my_kb": {"store": "../my_kb", "extra": 1}},
            {"my_kb": {"store": "../my_kb", "type": "BAD"}},
            {"my_kb": {"store": "../my_kb", "paths": {"s": "/abs"}}},
            {"my_kb": {"store": "../my_kb", "data": deep}},
            {"graphify": {"store": "../my_kb", "type": "x"}},
            {"unknown": {"store": "../x"}}, {"Bad_Name": {"store": "../x"}},
        ]
        for bad in bad_values:
            with self.subTest(bad=repr(bad)[:70]):
                manifest = self.manifest()
                manifest["module_info"] = bad
                self.set_manifest(manifest)
                code, out, err = self.update()
                self.assertEqual(code, 2)
                self.assertIn("module_info", err)

    def test_valid_absolute_store_entry_loads(self):
        self.new("graphify,my_kb=" + self.store())
        manifest = self.manifest()
        manifest["module_info"]["my_kb"]["store"] = "/srv/kb"
        self.set_manifest(manifest)
        self.assertEqual(self.update("graphify")[0], 0)

    def test_store_path_that_cannot_be_recorded_is_refused(self):
        odd = make_store(self.work, name="odd:name")
        code, out, err = self.new("odd=" + odd)
        self.assertEqual(code, 2)
        self.assertIn("odd", err)
        self.assertFalse(os.path.exists(self.target()))


class HarnessTreeTest(unittest.TestCase):
    """Plan 0018 increment A: the built-in harness tree reader (specification, "Layout")."""

    SKILL = "---\nname: x\ndescription: d\n---\nbody\n"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.module = {"name": "m", "path": os.path.join(self.tmp.name, "m")}
        os.makedirs(self.module["path"])

    def put(self, rel, data="x\n"):
        full = os.path.join(self.module["path"], "harness", "claude", *rel.split("/"))
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "wb") as handle:
            handle.write(data if isinstance(data, bytes) else data.encode("utf-8"))

    def read(self, reserved=frozenset()):
        return install.read_harness_tree(self.module, "claude", reserved=reserved)

    def refused(self, *needles):
        with self.assertRaises(install.InstallError) as ctx:
            self.read()
        for needle in needles:
            self.assertIn(needle, str(ctx.exception))
        return str(ctx.exception)

    def test_installed_paths_and_units(self):
        self.put("skills/x/SKILL.md", self.SKILL)
        self.put("skills/x/notes.md", "n\n")
        self.put("agents/a.md", "---\nname: agent-a\n---\nbody\n")
        self.put("commands/c.md", "plain\n")
        self.put("remote-runner.toml", "k = 1\n")
        self.put("root/CLAUDE.md", "@AGENTS.md\n")
        self.put("harness.json", '{"roles": {"extractor": "agents/a.md"}}')
        files, units = self.read()
        self.assertEqual(sorted(files), [
            ".claude/agents/a.md", ".claude/commands/c.md", ".claude/remote-runner.toml",
            ".claude/skills/x/SKILL.md", ".claude/skills/x/notes.md", "CLAUDE.md"])
        self.assertEqual(units, {".claude/skills/x": "x", ".claude/agents/a.md": "agent-a",
                                 ".claude/commands/c.md": "c"})

    def test_module_without_the_harness_directory_has_nothing(self):
        self.assertEqual(self.read(), ({}, {}))

    def test_unknown_harness_name_is_refused(self):
        with self.assertRaises(install.InstallError) as ctx:
            install.read_harness_tree(self.module, "nope")
        self.assertIn("harness", str(ctx.exception))

    def test_directory_for_an_unknown_harness_is_refused_without_echoing_a_long_name(self):
        long_name = "z" * 40
        os.makedirs(os.path.join(self.module["path"], "harness", long_name))
        message = self.refused("module m")
        self.assertNotIn(long_name, message)
        os.rmdir(os.path.join(self.module["path"], "harness", long_name))
        os.makedirs(os.path.join(self.module["path"], "harness", "opencode"))
        self.refused("opencode")

    def test_symlinked_harness_directories_are_refused(self):
        outside = os.path.join(self.tmp.name, "outside")
        os.makedirs(outside)
        os.makedirs(os.path.join(self.module["path"], "harness"))
        os.symlink(outside, os.path.join(self.module["path"], "harness", "claude"))
        self.refused("symlink")

    def test_disallowed_source_entries_are_refused(self):
        for rel in ("settings.json", "settings.local.json", "hooks/run.sh", ".mcp.json",
                    "README.md", "root/AGENTS.md", "root/sub/CLAUDE.md", "other/x.md"):
            with self.subTest(rel=rel):
                self.tmp.cleanup()
                self.setUp()
                self.put(rel)
                self.refused()

    def test_a_directory_named_like_a_root_file_or_declaration_is_refused(self):
        os.makedirs(os.path.join(self.module["path"], "harness", "claude", "harness.json"))
        self.refused("harness.json")

    def test_harness_json_rules(self):
        cases = {
            "not json": "{",
            "a list": "[]",
            "unknown key": '{"roles": {}, "extra": 1}',
            "roles not an object": '{"roles": []}',
            "bad role id": '{"roles": {"Bad": "agents/a.md"}}',
            "target not a string": '{"roles": {"r": 1}}',
            "target unsafe": '{"roles": {"r": "../x"}}',
            "target dot git": '{"roles": {"r": ".git/x"}}',
            "target backslash": '{"roles": {"r": "agents\\\\a.md"}}',
            "target with colon": '{"roles": {"r": "agents/a:b.md"}}',
            "target missing": '{"roles": {"r": "agents/missing.md"}}',
            "target a directory": '{"roles": {"r": "agents"}}',
            "too many roles": json_roles(17),
            "too large": '{"roles": {}, "pad": "%s"}' % ("x" * 17000),
        }
        for label, text in cases.items():
            with self.subTest(label=label):
                self.tmp.cleanup()
                self.setUp()
                self.put("agents/a.md", "a\n")
                self.put("harness.json", text)
                self.refused("harness.json")

    def test_a_role_may_map_to_a_root_file(self):
        self.put("root/CLAUDE.md", "x\n")
        self.put("harness.json", '{"roles": {"entry": "root/CLAUDE.md"}}')
        self.assertIn("CLAUDE.md", self.read()[0])

    def test_harness_json_exactly_at_its_limits_is_accepted_and_not_installed(self):
        self.put("agents/a.md", "a\n")
        self.put("harness.json", json_roles(16))
        files, _ = self.read()
        self.assertNotIn(".claude/harness.json", files)
        self.assertEqual(list(files), [".claude/agents/a.md"])

    def test_path_rules(self):
        for rel in ("skills/x/.git/y.md", "skills/x/a\\b.md", "skills/x/a:b.md",
                    "skills/" + "/".join("d" * 1 for _ in range(8)) + "/f.md"):
            with self.subTest(rel=rel):
                self.tmp.cleanup()
                self.setUp()
                self.put(rel)
                self.refused()

    def test_depth_eight_is_the_limit(self):
        self.put("skills/x/a/b/c/d/e/f.md")  # 8 components
        self.assertIn(".claude/skills/x/a/b/c/d/e/f.md", self.read()[0])

    def test_fold_orders_nfc_casefold_nfc(self):
        self.assertEqual(install.fold("Ϊ́"), install.fold("ΐ"))
        self.assertEqual(install.fold("Skills/É"), install.fold("skills/é"))

    def test_aliases_are_refused(self):
        with self.assertRaises(install.InstallError):
            install.check_unique(["skills/Foo/SKILL.md", "skills/foo/SKILL.md"])
        with self.assertRaises(install.InstallError):
            install.check_unique(["skills/é/SKILL.md", "skills/é/SKILL.md"])
        with self.assertRaises(install.InstallError):
            install.check_unique(["skills/ΐ/SKILL.md", "skills/Ϊ́/SKILL.md"])
        install.check_unique(["skills/a/SKILL.md", "skills/b/SKILL.md"])

    def test_symlink_and_fifo_in_the_tree_are_refused(self):
        self.put("skills/x/SKILL.md", self.SKILL)
        base = os.path.join(self.module["path"], "harness", "claude", "skills", "x")
        os.symlink("SKILL.md", os.path.join(base, "link.md"))
        self.refused("symlink")
        os.unlink(os.path.join(base, "link.md"))
        os.mkfifo(os.path.join(base, "fifo.md"))
        self.refused("not a regular file")

    def test_count_limits_abort_before_any_file_is_read(self):
        for n in range(129):
            self.put("skills/s/f%03d.md" % n)
        with unittest.mock.patch.object(install, "read_regular") as reader:
            self.refused("128")
        reader.assert_not_called()

    def test_one_hundred_twenty_eight_files_are_accepted(self):
        for n in range(128):
            self.put("skills/s/f%03d.md" % n)
        self.assertEqual(len(self.read()[0]), 128)

    def test_a_directory_with_too_many_entries_is_refused_before_reading(self):
        base = os.path.join(self.module["path"], "harness", "claude", "skills")
        os.makedirs(base)
        for n in range(129):
            os.mkdir(os.path.join(base, "d%03d" % n))
        with unittest.mock.patch.object(install, "read_regular") as reader:
            self.refused("128")
        reader.assert_not_called()

    def test_file_size_limits(self):
        self.put("skills/x/big.md", "a" * (256 * 1024 + 1))
        self.refused("256")
        self.tmp.cleanup()
        self.setUp()
        self.put("skills/x/ok.md", "a" * (256 * 1024))
        self.assertEqual(len(self.read()[0]), 1)

    def test_tree_size_limit(self):
        for n in range(9):
            self.put("skills/x/f%d.md" % n, "a" * (250 * 1024))
        self.refused("2 MiB")

    def test_files_must_be_utf8_text_without_nul(self):
        for data in (b"a\0b", b"\xff\xfe", ):
            with self.subTest(data=data):
                self.tmp.cleanup()
                self.setUp()
                self.put("skills/x/f.md", data)
                self.refused("text")

    def test_marker_strings_are_refused(self):
        for text in ("@module-slot: a", "<!-- BEGIN module:x slot:y -->", "END module:x"):
            with self.subTest(text=text):
                self.tmp.cleanup()
                self.setUp()
                self.put("skills/x/f.md", "line\n" + text + "\n")
                self.refused("marker")

    def test_installed_path_equal_to_a_reserved_path_is_refused(self):
        self.put("root/CLAUDE.md", "x\n")
        with self.assertRaises(install.InstallError) as ctx:
            self.read(reserved={install.fold("claude.md")})
        self.assertIn("CLAUDE.md", str(ctx.exception))
        self.read(reserved={"unrelated"})

    def test_frontmatter_name_and_unit_name_defaults(self):
        self.put("skills/dir/SKILL.md", "---\ndescription: d\n---\nbody\n")
        self.put("agents/a.md", "---\nname: renamed\n---\nb\n")
        self.put("commands/plain.md", "no frontmatter\n")
        _, units = self.read()
        self.assertEqual(units, {".claude/skills/dir": "dir", ".claude/agents/a.md": "renamed",
                                 ".claude/commands/plain.md": "plain"})

    def test_two_units_with_the_same_name_are_refused(self):
        self.put("skills/one/SKILL.md", "---\nname: same\n---\n")
        self.put("agents/two.md", "---\nname: Same\n---\n")
        self.refused("same")


def json_roles(count):
    return json.dumps({"roles": {"role-%d" % n: "agents/a.md" for n in range(count)}})


SHA = "a" * 64


class HarnessManifestTest(unittest.TestCase):
    """Plan 0018 increment B: the manifest record (specification, "Manifest")."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.project = self.tmp.name

    def manifest(self, **changes):
        data = {"schema": 2, "template_commit": None, "template_dirty": False,
                "modules": ["demo", "other"], "harness": "claude",
                "harness_files": {".claude/skills/x/SKILL.md": {"sha256": SHA, "modules": ["demo"]}}}
        data.update(changes)
        for key in [k for k, v in data.items() if v is DROP]:
            del data[key]
        return data

    def load(self, data):
        with open(os.path.join(self.project, ".template-manifest"), "w") as handle:
            json.dump(data, handle)
        return install.load_manifest(self.project, set())

    def refused(self, data):
        with self.assertRaises(install.InstallError) as ctx:
            self.load(data)
        return str(ctx.exception)

    def files(self, mapping):
        return self.manifest(harness_files=mapping)

    def test_a_valid_record_loads(self):
        loaded = self.load(self.manifest())
        self.assertEqual(loaded["harness"], "claude")

    def test_an_empty_record_is_valid_with_a_harness(self):
        self.assertEqual(self.load(self.manifest(harness_files={}))["harness_files"], {})

    def test_schema_one_without_harness_keys_still_loads(self):
        data = self.manifest(schema=1, harness=DROP, harness_files=DROP)
        self.assertEqual(self.load(data)["schema"], 1)

    def test_schema_and_keys_must_agree(self):
        self.refused(self.manifest(harness=DROP, harness_files=DROP))  # schema 2, no harness
        self.refused(self.manifest(harness_files=DROP))                 # schema 2, no record
        self.refused(self.manifest(schema=1))                           # schema 1 with harness
        self.refused(self.manifest(schema=1, harness=DROP))             # schema 1 with record
        self.refused(self.manifest(schema=True))
        self.refused(self.manifest(schema=3))
        self.refused(self.manifest(schema=2.0))

    def test_harness_must_be_a_known_name(self):
        for value in ("opencode", "", 1, None, ["claude"], "Claude"):
            with self.subTest(value=value):
                self.refused(self.manifest(harness=value))

    def test_keys_must_be_destinations_of_the_harness(self):
        good = {"sha256": SHA, "modules": ["demo"]}
        for key in ("README.md", ".claude/settings.json", "src/main.py", ".template-manifest",
                    "/abs/x", "../x", ".claude/../x", ".claude/skills",
                    ".claude/hooks/x.sh", ".claude/remote-runner.toml/x", "CLAUDE.md/x",
                    ".claude/skills/.git/x", ".claude\\skills\\x\\f.md", "",
                    ".claude/skills/" + "a" * 260):
            with self.subTest(key=key):
                self.refused(self.files({key: good}))
        for key in ("CLAUDE.md", ".claude/remote-runner.toml", ".claude/skills/x/SKILL.md",
                    ".claude/skills/loose.md", ".claude/agents/a.md", ".claude/commands/c.md"):
            with self.subTest(key=key):
                self.load(self.files({key: good}))

    def test_case_and_unicode_duplicate_keys_are_refused(self):
        good = {"sha256": SHA, "modules": ["demo"]}
        self.refused(self.files({".claude/skills/x/SKILL.md": good, ".claude/skills/X/SKILL.md": good}))
        self.refused(self.files({".claude/skills/é/a.md": good, ".claude/skills/é/a.md": good}))

    def test_values_must_be_exact(self):
        key = ".claude/skills/x/SKILL.md"
        bad = [
            {"sha256": SHA}, {"modules": ["demo"]}, {"sha256": SHA, "modules": ["demo"], "x": 1},
            {"sha256": "A" * 64, "modules": ["demo"]}, {"sha256": "a" * 63, "modules": ["demo"]},
            {"sha256": 1, "modules": ["demo"]}, {"sha256": SHA, "modules": []},
            {"sha256": SHA, "modules": "demo"}, {"sha256": SHA, "modules": ["other", "demo"]},
            {"sha256": SHA, "modules": ["demo", "demo"]}, {"sha256": SHA, "modules": ["missing"]},
            {"sha256": SHA, "modules": ["Bad Name"]}, {"sha256": SHA, "modules": [1]},
            [], "x", None,
        ]
        for value in bad:
            with self.subTest(value=value):
                self.refused(self.files({key: value}))

    def test_a_supplier_may_be_an_external_module(self):
        data = self.manifest(
            external_modules={"my_kb": {"module_format": 1, "digest": SHA}},
            harness_files={".claude/skills/x/SKILL.md": {"sha256": SHA, "modules": ["my_kb"]}})
        self.load(data)

    def test_record_size_limits(self):
        good = {"sha256": SHA, "modules": ["demo"]}
        many = {".claude/skills/s/f%04d.md" % n: good for n in range(4001)}
        self.refused(self.files(many))
        exact = {".claude/skills/s/f%04d.md" % n: good for n in range(4000)}
        self.load(self.files(exact))
        wide = {".claude/skills/" + ("k%d" % n).ljust(250, "x"): good for n in range(2200)}
        self.assertGreater(len(json.dumps(wide)), 512 * 1024)
        self.refused(self.files(wide))

    def test_a_manifest_over_the_limit_is_refused_before_writing(self):
        manifest = self.manifest(file_bases={"f%d" % n: None for n in range(10000)},
                                 project_name="p" * 200)
        manifest["module_info"] = {}
        manifest["pad"] = "x" * install.MAX_MANIFEST_BYTES
        with self.assertRaises(install.InstallError):
            install.encode_manifest(manifest)
        self.assertEqual(install.encode_manifest({"schema": 1})[-1:], b"\n")

    def test_manifest_bytes_writes_schema_two_only_with_a_harness(self):
        plain = json.loads(install.manifest_bytes(["demo"], None, False))
        self.assertEqual(plain["schema"], 1)
        self.assertNotIn("harness", plain)
        record = {".claude/agents/a.md": {"sha256": SHA, "modules": ["demo"]}}
        withh = json.loads(install.manifest_bytes(["demo"], None, False, harness="claude",
                                                  harness_files=record))
        self.assertEqual((withh["schema"], withh["harness"], withh["harness_files"]),
                         (2, "claude", record))
        empty = json.loads(install.manifest_bytes(["demo"], None, False, harness="claude",
                                                  harness_files={}))
        self.assertEqual(empty["harness_files"], {})


DROP = object()


class HarnessCase(ProjectCase):
    """Fixture built-in modules with harness directories (plan 0018)."""

    SKILL = "---\nname: x\ndescription: d\n---\nSkill body for REPLACE_WITH_PROJECT_NAME\n"

    def setUp(self):
        super().setUp()
        self.mods = os.path.join(self.work, "hmods")
        os.makedirs(self.mods)
        saved = install.MODULES_DIR
        install.MODULES_DIR = self.mods
        self.addCleanup(setattr, install, "MODULES_DIR", saved)

    def module(self, name, harness=None, files=None, **meta):
        base = os.path.join(self.mods, name)
        os.makedirs(base, exist_ok=True)
        with open(os.path.join(base, "module.json"), "w") as handle:
            json.dump(dict({"description": name}, **meta), handle)
        for kind, tree in (("harness/claude", harness or {}), ("files", files or {})):
            for rel, text in tree.items():
                full = os.path.join(base, *kind.split("/"), *rel.split("/"))
                os.makedirs(os.path.dirname(full), exist_ok=True)
                with open(full, "wb") as handle:
                    handle.write(text if isinstance(text, bytes) else text.encode("utf-8"))

    def demo(self):
        self.module("demo", harness={
            "skills/x/SKILL.md": self.SKILL,
            "agents/a.md": "---\nname: agent-a\n---\nagent\n",
            "commands/c.md": "command\n",
            "root/CLAUDE.md": "@AGENTS.md\n",
        })

    def new_h(self, with_, *extra):
        return run([self.target(), "--with", with_, "--git-name", "Test User",
                    "--git-email", "tester@users.noreply.example.invalid", *extra])

    def manifest(self):
        return json.loads(self.read(".template-manifest"))

    def add(self, *names, extra=()):
        return run(["--add", *names, "--dir", self.target(), *extra])

    def set_manifest(self, **changes):
        data = self.manifest()
        data.update(changes)
        self.write(".template-manifest", json.dumps(data))

    def sha(self, rel):
        import hashlib
        with open(self.path(rel), "rb") as handle:
            return hashlib.sha256(handle.read()).hexdigest()

    def project_with(self, **modules):
        for name, harness in modules.items():
            self.module(name, harness=harness)
        self.assertEqual(self.new_h(",".join(modules), "--harness", "claude")[0], 0)


class HarnessAddUpdateTest(HarnessCase):
    """Plan 0018 increment D: --harness with --add and --update."""

    # -- the command matrix --------------------------------------------

    def test_add_activates_a_harness_for_every_installed_module(self):
        self.demo()
        self.module("other", harness={"agents/o.md": "other\n"})
        self.module("plain")
        self.assertEqual(self.new_h("demo,plain")[0], 0)
        self.assertFalse(os.path.exists(self.path(".claude")))
        code, out, err = self.add("other", extra=["--harness", "claude"])
        self.assertEqual(code, 0, err)
        manifest = self.manifest()
        self.assertEqual((manifest["schema"], manifest["harness"]), (2, "claude"))
        self.assertEqual(sorted(manifest["harness_files"]), [
            ".claude/agents/a.md", ".claude/agents/o.md", ".claude/commands/c.md",
            ".claude/skills/x/SKILL.md", "CLAUDE.md"])
        self.assertIn("plain: no claude files", out)

    def test_add_uses_the_recorded_harness_and_refuses_a_different_one(self):
        self.demo()
        self.module("other", harness={"agents/o.md": "other\n"})
        self.assertEqual(self.new_h("demo", "--harness", "claude")[0], 0)
        before = self.read(".template-manifest")
        code, out, err = self.add("other", extra=["--harness", "opencode"])
        self.assertEqual(code, 2)
        self.assertEqual(self.read(".template-manifest"), before)
        self.assertFalse(os.path.exists(self.path(".claude/agents/o.md")))
        self.assertEqual(self.add("other")[0], 0)
        self.assertIn(".claude/agents/o.md", self.manifest()["harness_files"])

    def test_add_with_the_same_value_installs_the_new_module(self):
        self.demo()
        self.module("other", harness={"agents/o.md": "other\n"})
        self.assertEqual(self.new_h("demo", "--harness", "claude")[0], 0)
        self.assertEqual(self.add("other", extra=["--harness", "claude"])[0], 0)
        self.assertTrue(os.path.exists(self.path(".claude/agents/o.md")))

    def test_add_without_a_harness_installs_only_the_neutral_part(self):
        self.demo()
        self.module("other", harness={"agents/o.md": "other\n"}, files={"n.txt": "n\n"})
        self.assertEqual(self.new_h("demo")[0], 0)
        self.assertEqual(self.add("other")[0], 0)
        self.assertEqual(self.read("n.txt"), "n\n")
        self.assertFalse(os.path.exists(self.path(".claude")))
        self.assertNotIn("harness", self.manifest())

    def test_unknown_harness_value_is_refused_before_any_write(self):
        self.demo()
        self.module("other")
        self.assertEqual(self.new_h("demo")[0], 0)
        before = self.read(".template-manifest")
        for value in ("nope", "x" * 40):
            code, out, err = self.add("other", extra=["--harness", value])
            self.assertEqual(code, 2)
            self.assertNotIn("x" * 40, err)
        self.assertEqual(self.read(".template-manifest"), before)

    def test_update_never_introduces_a_harness(self):
        self.demo()
        self.assertEqual(self.new_h("demo")[0], 0)
        self.assertEqual(self.update()[0], 0)
        self.assertFalse(os.path.exists(self.path(".claude")))
        before = self.read(".template-manifest")
        code, out, err = self.update("--harness", "claude")
        self.assertEqual(code, 2)
        self.assertEqual(self.read(".template-manifest"), before)

    def test_update_accepts_only_the_recorded_harness(self):
        self.demo()
        self.assertEqual(self.new_h("demo", "--harness", "claude")[0], 0)
        self.assertEqual(self.update("--harness", "claude")[0], 0)
        self.assertEqual(self.update("--harness", "opencode")[0], 2)
        self.assertEqual(self.update("--harness", "x" * 40)[0], 2)

    def test_the_activation_names_an_external_module_it_does_not_read(self):
        self.demo()
        store = make_store(self.work, name="my_kb")
        self.assertEqual(self.new_h("demo,my_kb=" + store)[0], 0)
        self.module("other")
        code, out, err = self.add("other", extra=["--harness", "claude"])
        self.assertEqual(code, 0, err)
        self.assertIn("my_kb", out)
        self.assertEqual(self.manifest()["harness"], "claude")

    # -- collisions against existing files -----------------------------

    def activate_over(self, files):
        self.demo()
        self.module("other")
        self.assertEqual(self.new_h("demo")[0], 0)
        for rel, text in files.items():
            os.makedirs(os.path.dirname(self.path(rel)), exist_ok=True)
            self.write(rel, text)
        return self.add("other", extra=["--harness", "claude"])

    def test_a_new_path_is_written_and_an_identical_one_adopted(self):
        code, out, err = self.activate_over({"CLAUDE.md": "@AGENTS.md\n"})
        self.assertEqual(code, 0, err)
        record = self.manifest()["harness_files"]
        self.assertEqual(record["CLAUDE.md"]["modules"], ["demo"])
        self.assertIn(".claude/agents/a.md", record)
        self.assertNotIn("conflict", out)

    def test_a_differing_file_is_a_conflict_and_is_not_recorded(self):
        code, out, err = self.activate_over({".claude/commands/c.md": "mine\n"})
        self.assertEqual(code, 0, err)
        self.assertEqual(self.read(".claude/commands/c.md"), "mine\n")
        self.assertIn("conflict .claude/commands/c.md", out)
        self.assertIn("1 conflict(s)", out)
        self.assertNotIn(".claude/commands/c.md", self.manifest()["harness_files"])
        self.assertIn(".claude/agents/a.md", self.manifest()["harness_files"])

    def test_a_skill_unit_with_a_conflicting_file_is_skipped_whole(self):
        self.demo()
        self.module("demo", harness={
            "skills/x/SKILL.md": self.SKILL, "skills/x/extra.md": "extra\n",
            "agents/a.md": "agent\n"})
        self.module("other")
        self.assertEqual(self.new_h("demo")[0], 0)
        os.makedirs(self.path(".claude/skills/x"))
        self.write(".claude/skills/x/extra.md", "mine\n")
        code, out, err = self.add("other", extra=["--harness", "claude"])
        self.assertEqual(code, 0, err)
        self.assertFalse(os.path.exists(self.path(".claude/skills/x/SKILL.md")))
        record = self.manifest()["harness_files"]
        self.assertFalse([k for k in record if k.startswith(".claude/skills/x")])
        self.assertIn(".claude/agents/a.md", record)

    def test_extra_files_in_a_skill_directory_are_left_alone(self):
        self.demo()
        self.module("other")
        self.assertEqual(self.new_h("demo")[0], 0)
        os.makedirs(self.path(".claude/skills/x"))
        self.write(".claude/skills/x/mine.md", "mine\n")
        code, out, err = self.add("other", extra=["--harness", "claude"])
        self.assertEqual(code, 0, err)
        self.assertNotIn("conflict", out)
        self.assertEqual(self.read(".claude/skills/x/mine.md"), "mine\n")
        self.assertTrue(os.path.exists(self.path(".claude/skills/x/SKILL.md")))

    def test_a_symlink_or_a_directory_at_a_destination_is_a_conflict(self):
        self.demo()
        self.module("other")
        self.assertEqual(self.new_h("demo")[0], 0)
        os.makedirs(self.path(".claude/agents"))
        os.symlink(os.path.join(self.work, "elsewhere"), self.path(".claude/agents/a.md"))
        os.makedirs(self.path(".claude/commands/c.md"))
        refused = self.add("other", extra=["--harness", "claude"])
        self.assertEqual(refused[0], 2)  # the project scan refuses the symlink
        code, out, err = self.add("other", extra=["--harness", "claude", "--skip-unsafe-entries"])
        self.assertEqual(code, 0, err)
        self.assertIn("conflict .claude/agents/a.md", out)
        self.assertIn("conflict .claude/commands/c.md", out)
        self.assertTrue(os.path.islink(self.path(".claude/agents/a.md")))
        record = self.manifest()["harness_files"]
        self.assertNotIn(".claude/agents/a.md", record)
        self.assertNotIn(".claude/commands/c.md", record)

    def test_a_case_alias_is_a_conflict(self):
        self.demo()
        self.module("other")
        self.assertEqual(self.new_h("demo")[0], 0)
        self.write("Claude.md", "alias\n")
        code, out, err = self.add("other", extra=["--harness", "claude"])
        self.assertEqual(code, 0, err)
        self.assertIn("conflict CLAUDE.md", out)
        self.assertNotIn("CLAUDE.md", self.manifest()["harness_files"])

    def test_add_dry_run_writes_nothing(self):
        self.demo()
        self.module("other")
        self.assertEqual(self.new_h("demo")[0], 0)
        before = self.read(".template-manifest")
        code, out, err = self.add("other", extra=["--harness", "claude", "--dry-run"])
        self.assertEqual(code, 0, err)
        self.assertIn("would write .claude/agents/a.md", out)
        self.assertEqual(self.read(".template-manifest"), before)
        self.assertFalse(os.path.exists(self.path(".claude")))

    # -- --update ------------------------------------------------------

    def test_update_replaces_an_unedited_file_and_updates_its_hash(self):
        self.project_with(demo={"agents/a.md": "v1\n"})
        self.module("demo", harness={"agents/a.md": "v2\n"})
        code, out, err = self.update()
        self.assertEqual(code, 0, err)
        self.assertEqual(self.read(".claude/agents/a.md"), "v2\n")
        self.assertEqual(self.manifest()["harness_files"][".claude/agents/a.md"]["sha256"],
                         self.sha(".claude/agents/a.md"))

    def test_update_keeps_an_edited_file_and_reports_it(self):
        self.project_with(demo={"agents/a.md": "v1\n"})
        self.write(".claude/agents/a.md", "mine\n")
        recorded = self.manifest()["harness_files"]
        self.module("demo", harness={"agents/a.md": "v2\n"})
        code, out, err = self.update()
        self.assertEqual(code, 0, err)
        self.assertEqual(self.read(".claude/agents/a.md"), "mine\n")
        self.assertIn("conflict .claude/agents/a.md", out)
        self.assertEqual(self.manifest()["harness_files"], recorded)

    def test_update_moves_co_suppliers_only_together(self):
        self.project_with(one={"agents/a.md": "v1\n"}, two={"agents/a.md": "v1\n"})
        self.module("one", harness={"agents/a.md": "v2\n"})
        code, out, err = self.update("one")
        self.assertEqual(code, 0, err)
        self.assertEqual(self.read(".claude/agents/a.md"), "v1\n")
        self.assertIn("conflict", out)
        self.assertEqual(self.manifest()["harness_files"][".claude/agents/a.md"]["sha256"],
                         self.sha(".claude/agents/a.md"))
        self.module("two", harness={"agents/a.md": "v2\n"})
        code, out, err = self.update()
        self.assertEqual(code, 0, err)
        self.assertEqual(self.read(".claude/agents/a.md"), "v2\n")
        self.assertEqual(self.manifest()["harness_files"][".claude/agents/a.md"]["modules"],
                         ["one", "two"])

    def test_update_adopts_new_bytes_after_an_interruption(self):
        self.project_with(demo={"agents/a.md": "v1\n"})
        self.module("demo", harness={"agents/a.md": "v2\n"})
        self.write(".claude/agents/a.md", "v2\n")  # written, but the manifest still says v1
        code, out, err = self.update()
        self.assertEqual(code, 0, err)
        self.assertNotIn("conflict", out)
        self.assertEqual(self.manifest()["harness_files"][".claude/agents/a.md"]["sha256"],
                         self.sha(".claude/agents/a.md"))
        code, out, err = self.update()
        self.assertIn("Nothing to update", out)

    def test_update_writes_a_newly_shipped_file_and_never_deletes_a_dropped_one(self):
        self.project_with(demo={"agents/a.md": "v1\n"})
        self.module("demo", harness={"agents/b.md": "new\n"})
        code, out, err = self.update()
        self.assertEqual(code, 0, err)
        self.assertEqual(self.read(".claude/agents/b.md"), "new\n")
        self.assertEqual(self.read(".claude/agents/a.md"), "v1\n")
        record = self.manifest()["harness_files"]
        self.assertIn(".claude/agents/a.md", record)
        self.assertIn(".claude/agents/b.md", record)

    def test_update_rewrites_a_missing_recorded_file(self):
        self.project_with(demo={"agents/a.md": "v1\n"})
        os.unlink(self.path(".claude/agents/a.md"))
        self.assertEqual(self.update()[0], 0)
        self.assertEqual(self.read(".claude/agents/a.md"), "v1\n")

    def test_update_dry_run_writes_nothing(self):
        self.project_with(demo={"agents/a.md": "v1\n"})
        self.module("demo", harness={"agents/a.md": "v2\n"})
        before = self.read(".template-manifest")
        code, out, err = self.update("--dry-run")
        self.assertEqual(code, 0, err)
        self.assertIn("would write .claude/agents/a.md", out)
        self.assertEqual(self.read(".claude/agents/a.md"), "v1\n")
        self.assertEqual(self.read(".template-manifest"), before)

    def test_update_files_are_created_644(self):
        self.project_with(demo={"agents/a.md": "v1\n"})
        os.chmod(self.path(".claude/agents/a.md"), 0o755)
        self.module("demo", harness={"agents/a.md": "v2\n"})
        self.assertEqual(self.update()[0], 0)
        self.assertEqual(os.stat(self.path(".claude/agents/a.md")).st_mode & 0o777, 0o644)


class HarnessRemoveTest(HarnessCase):
    """Plan 0018 increment E: --remove of modules that supplied harness files."""

    def remove(self, *names, extra=()):
        return run(["--remove", *names, "--dir", self.target(), *extra])

    def test_a_sole_supplier_is_deleted_with_its_emptied_directories(self):
        self.demo()
        self.assertEqual(self.new_h("demo", "--harness", "claude")[0], 0)
        code, out, err = self.remove("demo")
        self.assertEqual(code, 0, err)
        for rel in (".claude", "CLAUDE.md"):
            self.assertFalse(os.path.exists(self.path(rel)), rel)
        manifest = self.manifest()
        self.assertEqual((manifest["schema"], manifest["harness"], manifest["harness_files"]),
                         (2, "claude", {}))

    def test_an_edited_file_is_kept_and_its_record_dropped(self):
        self.demo()
        self.assertEqual(self.new_h("demo", "--harness", "claude")[0], 0)
        self.write(".claude/commands/c.md", "mine\n")
        code, out, err = self.remove("demo")
        self.assertEqual(code, 0, err)
        self.assertEqual(self.read(".claude/commands/c.md"), "mine\n")
        self.assertIn("kept .claude/commands/c.md", out)
        self.assertEqual(self.manifest()["harness_files"], {})
        self.assertFalse(os.path.exists(self.path(".claude/agents/a.md")))

    def test_a_missing_file_only_drops_its_record(self):
        self.demo()
        self.assertEqual(self.new_h("demo", "--harness", "claude")[0], 0)
        os.unlink(self.path(".claude/commands/c.md"))
        self.assertEqual(self.remove("demo")[0], 0)
        self.assertEqual(self.manifest()["harness_files"], {})

    def test_a_co_supplied_file_stays_until_its_last_supplier_goes(self):
        self.project_with(one={"agents/a.md": "same\n"}, two={"agents/a.md": "same\n"})
        self.assertEqual(self.remove("one")[0], 0)
        self.assertEqual(self.read(".claude/agents/a.md"), "same\n")
        self.assertEqual(self.manifest()["harness_files"][".claude/agents/a.md"]["modules"], ["two"])
        self.assertEqual(self.remove("two")[0], 0)
        self.assertFalse(os.path.exists(self.path(".claude/agents/a.md")))

    def test_a_path_a_remaining_module_ships_is_never_deleted(self):
        self.module("one", harness={"agents/a.md": "same\n"})
        self.module("two")
        self.assertEqual(self.new_h("one,two", "--harness", "claude")[0], 0)
        self.module("two", files={".claude/agents/a.md": "same\n"})
        code, out, err = self.remove("one")
        self.assertEqual(code, 0, err)
        self.assertEqual(self.read(".claude/agents/a.md"), "same\n")
        self.assertNotIn(".claude/agents/a.md", self.manifest()["harness_files"])

    def test_a_forged_record_deletes_only_a_matching_regular_file(self):
        self.demo()
        self.assertEqual(self.new_h("demo", "--harness", "claude")[0], 0)
        os.makedirs(self.path(".claude/agents"), exist_ok=True)
        self.write(".claude/agents/mine.md", "user file\n")
        record = self.manifest()["harness_files"]
        record[".claude/agents/mine.md"] = {"sha256": "0" * 64, "modules": ["demo"]}
        self.set_manifest(harness_files=record)
        self.assertEqual(self.remove("demo")[0], 0)
        self.assertEqual(self.read(".claude/agents/mine.md"), "user file\n")

    def test_a_forged_key_outside_the_harness_is_refused_untouched(self):
        self.demo()
        self.assertEqual(self.new_h("demo", "--harness", "claude")[0], 0)
        record = self.manifest()["harness_files"]
        record["README.md"] = {"sha256": self.sha("CLAUDE.md"), "modules": ["demo"]}
        self.set_manifest(harness_files=record)
        before = self.read("AGENTS.md")
        code, out, err = self.remove("demo")
        self.assertEqual(code, 2)
        self.assertEqual(self.read("AGENTS.md"), before)
        self.assertTrue(os.path.exists(self.path(".claude/agents/a.md")))

    def test_a_directory_valued_record_does_not_block_the_run(self):
        self.demo()
        self.assertEqual(self.new_h("demo", "--harness", "claude")[0], 0)
        os.makedirs(self.path(".claude/agents/folder"))
        record = self.manifest()["harness_files"]
        record[".claude/agents/folder"] = {"sha256": "0" * 64, "modules": ["demo"]}
        self.set_manifest(harness_files=record)
        code, out, err = self.remove("demo")
        self.assertEqual(code, 0, err)
        self.assertTrue(os.path.isdir(self.path(".claude/agents/folder")))
        self.assertNotIn(".claude/agents/folder", self.manifest()["harness_files"])

    def test_removal_reads_no_harness_tree(self):
        self.demo()
        self.module("other", harness={"agents/o.md": "o\n"})
        self.assertEqual(self.new_h("demo,other", "--harness", "claude")[0], 0)
        self.module("other", harness={"hooks/run.sh": "bad\n"})  # a tree that would now be refused
        code, out, err = self.remove("demo")
        self.assertEqual(code, 0, err)
        self.assertIn(".claude/agents/o.md", self.manifest()["harness_files"])

    def test_remove_dry_run_changes_nothing(self):
        self.demo()
        self.assertEqual(self.new_h("demo", "--harness", "claude")[0], 0)
        before = self.read(".template-manifest")
        code, out, err = self.remove("demo", extra=["--dry-run"])
        self.assertEqual(code, 0, err)
        self.assertIn("would delete .claude/agents/a.md", out)
        self.assertTrue(os.path.exists(self.path(".claude/agents/a.md")))
        self.assertEqual(self.read(".template-manifest"), before)

    def test_a_project_without_a_harness_is_removed_as_before(self):
        self.demo()
        self.module("plain")
        self.assertEqual(self.new_h("demo,plain")[0], 0)
        self.assertEqual(self.remove("plain")[0], 0)
        self.assertNotIn("harness", self.manifest())


class HarnessFindingsTest(HarnessCase):
    """Plan 0018 increment G: regression tests for the adversarial review's findings."""

    def test_remove_does_not_delete_a_path_twice(self):
        self.module("m", files={".claude/agents/x.md": "x\n"})
        self.assertEqual(self.new_h("m", "--harness", "claude")[0], 0)
        record = self.manifest()["harness_files"]
        record[".claude/agents/x.md"] = {"sha256": self.sha(".claude/agents/x.md"), "modules": ["m"]}
        self.set_manifest(harness_files=record)
        code, out, err = run(["--remove", "m", "--dir", self.target()])
        self.assertEqual(code, 0, err)
        self.assertFalse(os.path.exists(self.path(".claude/agents/x.md")))
        self.assertEqual(self.manifest()["modules"], [])

    def test_a_too_long_installed_path_is_refused_at_install(self):
        self.module("long", harness={"skills/%s/SKILL.md" % ("a" * 240): "x\n"})
        code, out, err = self.new_h("long", "--harness", "claude")
        self.assertEqual(code, 2)
        self.assertIn("256", err)
        self.assertFalse(os.path.exists(self.target()))

    def test_the_writer_enforces_the_record_limits(self):
        good = {"sha256": SHA, "modules": ["demo"]}
        many = {".claude/skills/s/f%04d.md" % n: good for n in range(4001)}
        with self.assertRaises(install.InstallError):
            install.encode_manifest({"schema": 2, "harness": "claude", "harness_files": many})
        with self.assertRaises(install.InstallError):
            install.encode_manifest({"schema": 2, "harness": "claude",
                                     "harness_files": {".claude/agents/" + "a" * 250: good}})
        install.encode_manifest({"schema": 2, "harness": "claude", "modules": ["demo"],
                                 "harness_files": {".claude/agents/a.md": good}})

    def test_aliases_between_modules_fail_before_any_write(self):
        self.module("m1", harness={"skills/Foo/SKILL.md": "---\nname: foo-a\n---\n"})
        self.module("m2", harness={"skills/foo/SKILL.md": "---\nname: foo-b\n---\n"})
        code, out, err = self.new_h("m1,m2", "--harness", "claude")
        self.assertEqual(code, 2)
        self.assertIn("folding", err)
        self.assertFalse(os.path.exists(self.target()))

    def test_a_path_any_installed_module_ships_is_reserved(self):
        self.module("owner", files={"CLAUDE.md": "mine\n"})
        self.module("late", harness={"root/CLAUDE.md": "theirs\n"})
        self.assertEqual(self.new_h("owner", "--harness", "claude")[0], 0)
        before = self.read(".template-manifest")
        code, out, err = run(["--add", "late", "--dir", self.target()])
        self.assertEqual(code, 2)
        self.assertEqual(self.read(".template-manifest"), before)
        self.assertEqual(self.read("CLAUDE.md"), "mine\n")

    def test_an_unknown_or_symlinked_harness_directory_is_refused_without_the_option(self):
        self.module("odd")
        os.makedirs(os.path.join(self.mods, "odd", "harness", "other"))
        code, out, err = self.new_h("odd")
        self.assertEqual(code, 2)
        self.assertFalse(os.path.exists(self.target()))
        self.module("linked")
        os.makedirs(os.path.join(self.work, "elsewhere"))
        os.symlink(os.path.join(self.work, "elsewhere"), os.path.join(self.mods, "linked", "harness"))
        code, out, err = self.new_h("linked")
        self.assertEqual(code, 2)
        self.module("plain")
        self.assertEqual(self.new_h("plain")[0], 0)
        code, out, err = run(["--add", "odd", "--dir", self.target()])
        self.assertEqual(code, 2)

    def test_remove_ignores_markers_in_kept_harness_files(self):
        self.demo()
        self.assertEqual(self.new_h("demo", "--harness", "claude")[0], 0)
        self.write(".claude/commands/c.md", "<!-- BEGIN module:demo slot:x -->\nmine\n")
        code, out, err = run(["--remove", "demo", "--dir", self.target()])
        self.assertEqual(code, 0, err)
        self.assertIn("mine", self.read(".claude/commands/c.md"))

    def test_markers_formed_by_substitution_are_refused(self):
        self.module("m", harness={"agents/a.md": "REPLACE_WITH_PROJECT_NAME:x slot:y\n"})
        code, out, err = self.new_h("m", "--harness", "claude", "--name", "BEGIN module")
        self.assertEqual(code, 2)
        self.assertIn("marker", err)
        self.assertFalse(os.path.exists(self.target()))

    def test_a_rewritten_path_keeps_its_other_recorded_suppliers(self):
        self.project_with(one={"agents/a.md": "same\n"}, two={"agents/a.md": "same\n"})
        os.unlink(self.path(".claude/agents/a.md"))
        self.assertEqual(self.update("one")[0], 0)
        self.assertEqual(self.read(".claude/agents/a.md"), "same\n")
        self.assertEqual(self.manifest()["harness_files"][".claude/agents/a.md"]["modules"],
                         ["one", "two"])

    def test_read_regular_never_returns_more_than_its_limit(self):
        path = os.path.join(self.work, "grown")
        with open(path, "wb") as handle:
            handle.write(b"x" * 100)
        real = os.lstat(path)
        small = unittest.mock.Mock(st_mode=real.st_mode, st_size=10)
        with unittest.mock.patch.object(install.os, "lstat", return_value=small):
            with self.assertRaises(install.InstallError):
                install.read_regular(path, 50)
        self.assertEqual(install.read_regular(path, 100), b"x" * 100)


class HarnessSecondPassTest(HarnessCase):
    """Plan 0018 increment G: the second review pass, and the coverage it found missing."""

    def interrupt_manifest_write(self):
        """Make the manifest rename fail, after every other file was written."""
        real = install.os.replace

        def failing(src, dst, *args, **kwargs):
            if os.path.basename(dst) == ".template-manifest":
                raise OSError(5, "simulated kill")
            return real(src, dst, *args, **kwargs)

        return unittest.mock.patch.object(install.os, "replace", side_effect=failing)

    def test_a_stale_record_key_cannot_alias_a_new_path(self):
        self.module("r", harness={"agents/X.md": "v1\n"})
        self.assertEqual(self.new_h("r", "--harness", "claude")[0], 0)
        os.unlink(self.path(".claude/agents/X.md"))
        source = os.path.join(self.mods, "r", "harness", "claude", "agents")
        os.rename(os.path.join(source, "X.md"), os.path.join(source, "x.md"))  # the module renames it
        with open(os.path.join(source, "x.md"), "w") as handle:
            handle.write("v2\n")
        code, out, err = self.update()
        self.assertEqual(code, 0, err)
        self.assertIn("conflict .claude/agents/x.md", out)
        keys = list(self.manifest()["harness_files"])
        self.assertEqual(keys, [".claude/agents/X.md"])
        self.assertEqual(self.update()[0], 0)  # the project is not wedged

    def test_the_writer_refuses_a_record_the_loader_would_refuse(self):
        good = {"sha256": SHA, "modules": ["demo"]}
        aliased = {".claude/agents/X.md": good, ".claude/agents/x.md": good}
        with self.assertRaises(install.InstallError):
            install.encode_manifest({"schema": 2, "harness": "claude", "modules": ["demo"],
                                     "harness_files": aliased})

    def test_a_forged_record_does_not_delete_a_file_the_files_rule_kept(self):
        self.module("m", files={".claude/agents/y.md": "orig\n"})
        self.assertEqual(self.new_h("m", "--harness", "claude")[0], 0)
        self.write(".claude/agents/y.md", "edited\n")
        record = self.manifest()["harness_files"]
        record[".claude/agents/y.md"] = {"sha256": self.sha(".claude/agents/y.md"), "modules": ["m"]}
        self.set_manifest(harness_files=record)
        code, out, err = run(["--remove", "m", "--dir", self.target()])
        self.assertEqual(code, 0, err)
        self.assertEqual(self.read(".claude/agents/y.md"), "edited\n")

    def test_an_interrupted_update_reruns_to_a_consistent_state(self):
        self.project_with(demo={"agents/a.md": "v1\n"})
        self.module("demo", harness={"agents/a.md": "v2\n"})
        with self.interrupt_manifest_write():
            self.assertEqual(self.update()[0], 2)
        self.assertEqual(self.read(".claude/agents/a.md"), "v2\n")  # written, manifest still old
        self.assertEqual(self.update()[0], 0)
        self.assertEqual(self.manifest()["harness_files"][".claude/agents/a.md"]["sha256"],
                         self.sha(".claude/agents/a.md"))
        self.assertIn("Nothing to update", self.update()[1])

    def test_an_interrupted_activation_reruns_to_a_consistent_state(self):
        self.demo()
        self.module("other")
        self.assertEqual(self.new_h("demo")[0], 0)
        with self.interrupt_manifest_write():
            self.assertEqual(self.add("other", extra=["--harness", "claude"])[0], 2)
        self.assertNotIn("harness", self.manifest())
        self.assertTrue(os.path.exists(self.path(".claude/agents/a.md")))
        code, out, err = self.add("other", extra=["--harness", "claude"])
        self.assertEqual(code, 0, err)
        self.assertEqual(self.manifest()["harness"], "claude")
        self.assertNotIn("conflict", out)
        self.assertIn(".claude/agents/a.md", self.manifest()["harness_files"])

    def test_an_interrupted_remove_reruns_to_a_consistent_state(self):
        self.demo()
        self.assertEqual(self.new_h("demo", "--harness", "claude")[0], 0)
        with self.interrupt_manifest_write():
            self.assertEqual(run(["--remove", "demo", "--dir", self.target()])[0], 2)
        self.assertEqual(self.manifest()["modules"], ["demo"])
        code, out, err = run(["--remove", "demo", "--dir", self.target()])
        self.assertEqual(code, 0, err)
        self.assertEqual(self.manifest()["harness_files"], {})
        self.assertEqual(self.manifest()["modules"], [])

    def test_update_replaces_a_setuid_file_with_a_plain_one_under_umask_zero(self):
        self.project_with(demo={"agents/a.md": "v1\n"})
        os.chmod(self.path(".claude/agents/a.md"), 0o4755)
        self.module("demo", harness={"agents/a.md": "v2\n"})
        old = os.umask(0)
        self.addCleanup(os.umask, old)
        self.assertEqual(self.update()[0], 0)
        self.assertEqual(os.stat(self.path(".claude/agents/a.md")).st_mode & 0o7777, 0o644)

    def test_a_bad_built_in_tree_does_not_block_list_or_remove(self):
        self.demo()
        self.module("plain")
        self.assertEqual(self.new_h("demo,plain", "--harness", "claude")[0], 0)
        os.makedirs(os.path.join(self.mods, "plain", "harness", "other"))
        self.assertEqual(run(["--list"])[0], 0)
        self.assertEqual(run(["--remove", "demo", "--dir", self.target()])[0], 0)

    def test_an_older_installer_refuses_a_schema_two_project(self):
        probe = subprocess.run(["git", "-C", ROOT, "cat-file", "-e", "30f08e5:install.py"],
                               capture_output=True)
        if probe.returncode:
            self.skipTest("the pre-harness commit is not in this checkout")
        old = os.path.join(self.work, "old")
        shutil.copytree(os.path.join(ROOT, "base"), os.path.join(old, "base"))
        shutil.copytree(os.path.join(ROOT, "modules"), os.path.join(old, "modules"))
        source = subprocess.run(["git", "-C", ROOT, "show", "30f08e5:install.py"],
                                capture_output=True, check=True).stdout
        with open(os.path.join(old, "install.py"), "wb") as handle:
            handle.write(source)
        self.demo()
        self.assertEqual(self.new_h("demo", "--harness", "claude")[0], 0)
        before = self.read(".template-manifest")
        for argv in (["--update", "--dry-run"], ["--update"], ["--add", "plain"], ["--remove", "demo"]):
            result = subprocess.run([sys.executable, "-I", os.path.join(old, "install.py"), *argv,
                                     "--dir", self.target()], capture_output=True, text=True)
            self.assertEqual(result.returncode, 2, argv)
            self.assertIn("malformed", result.stderr)
        self.assertEqual(self.read(".template-manifest"), before)
        self.assertTrue(os.path.exists(self.path(".claude/agents/a.md")))


class DeclarationTest(unittest.TestCase):
    """Plan 0020 increment A: helpers, workers and global_config in module.json."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = self.tmp.name

    def load(self, **keys):
        os.makedirs(os.path.join(self.root, "m"), exist_ok=True)
        with open(os.path.join(self.root, "m", "module.json"), "w") as handle:
            json.dump(dict({"description": "m"}, **keys), handle)
        return install.load_modules(self.root)["m"]

    def refused(self, **keys):
        with self.assertRaises(install.InstallError) as ctx:
            self.load(**keys)
        self.assertIn("module m", str(ctx.exception))

    def test_valid_declarations_are_kept_on_the_record(self):
        meta = self.load(helpers=["ask-codex", "claude-workflow"],
                         workers={"chunk-extractor": "reads the listed files, writes one chunk"},
                         global_config=True)
        self.assertEqual(meta["helpers"], ["ask-codex", "claude-workflow"])
        self.assertEqual(meta["workers"], {"chunk-extractor": "reads the listed files, writes one chunk"})
        self.assertIs(meta["global_config"], True)

    def test_a_module_without_them_has_empty_declarations(self):
        meta = self.load()
        self.assertEqual((meta["helpers"], meta["workers"], meta["global_config"]), ([], {}, False))

    def test_global_config_false_is_accepted(self):
        self.assertIs(self.load(global_config=False)["global_config"], False)

    def test_helpers_rules(self):
        for value in ("ask-codex", {"a": 1}, [1], [None], [""], [".hidden"], ["-lead"],
                      ["has space"], ["a/b"], ["x" * 65], ["name\n"], ["dup", "dup"],
                      ["h%d" % n for n in range(17)], ["tab\tname"], ["\u00e9"]):
            with self.subTest(value=value):
                self.refused(helpers=value)

    def test_helpers_exactly_at_the_limits_are_accepted(self):
        self.load(helpers=["h%d" % n for n in range(16)])
        self.load(helpers=["a" + "b" * 63])
        self.load(helpers=["A.b_c-1"])

    def test_workers_rules(self):
        ok = "reads files, writes one output"
        for value in ([], "x", {"Bad": ok}, {"1bad": ok}, {"r": ""}, {"r": "x" * 201},
                      {"r": "two\nlines"}, {"r": "bell\u0007"}, {"r": 5}, {"r": None},
                      {"r%d" % n: ok for n in range(17)}, {"r" * 65: ok}, {"": ok}):
            with self.subTest(value=value):
                self.refused(workers=value)

    def test_workers_exactly_at_the_limits_are_accepted(self):
        self.load(workers={"r%d" % n: "c" for n in range(16)})
        self.load(workers={"r" * 64: "x" * 200})

    def test_global_config_must_be_a_boolean(self):
        for value in (1, 0, "true", None, [], {}):
            with self.subTest(value=value):
                self.refused(global_config=value)

    def test_every_real_module_passes_the_declaration_rules(self):
        for name, meta in install.load_modules().items():
            self.assertIsNone(install.declarations_problem(meta), name)


class MarkerTest(unittest.TestCase):
    """Plan 0020 increment B: the global-configuration marker (specification, "Declarations")."""

    MISSING_BAD = "missing (unreadable or invalid marker)"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = os.path.join(self.tmp.name, "cfg")
        os.makedirs(self.dir)
        self.path = os.path.join(self.dir, "global-config.json")

    def put(self, data):
        with open(self.path, "wb") as handle:
            handle.write(data if isinstance(data, bytes) else data.encode("utf-8"))

    def state(self):
        return install.read_marker("claude", self.dir)

    def test_a_valid_marker_is_present(self):
        self.put('{"schema": 1}')
        self.assertEqual(self.state(), "present")
        self.put('{"schema": 1, "name": "claude_global_config", "extra": [1, 2]}')
        self.assertEqual(self.state(), "present")

    def test_an_absent_marker_is_missing(self):
        self.assertEqual(self.state(), "missing")
        self.assertEqual(install.read_marker("claude", os.path.join(self.tmp.name, "nowhere")), "missing")

    def test_every_other_state_is_missing_and_invalid(self):
        os.symlink(os.path.join(self.dir, "target.json"), self.path)
        with open(os.path.join(self.dir, "target.json"), "w") as handle:
            handle.write('{"schema": 1}')
        cases = {
            "symlink": None,
            "not json": "{",
            "a list": "[1]",
            "a string": '"x"',
            "schema true": '{"schema": true}',
            "schema float": '{"schema": 1.0}',
            "schema string": '{"schema": "1"}',
            "schema two": '{"schema": 2}',
            "no schema": "{}",
            "not utf-8": b'{"schema": 1, "x": "\xff"}',
            "nul": b'{"schema": 1}\0',
            "deeply nested": "[" * 100000 + "]" * 100000,
            "too big": '{"schema": 1, "pad": "%s"}' % ("x" * 5000),
        }
        for label, data in cases.items():
            with self.subTest(label=label):
                if data is not None:
                    if os.path.lexists(self.path):
                        os.unlink(self.path)
                    self.put(data)
                self.assertEqual(self.state(), self.MISSING_BAD)

    def test_a_directory_and_a_fifo_are_invalid(self):
        os.mkdir(self.path)
        self.assertEqual(self.state(), self.MISSING_BAD)
        os.rmdir(self.path)
        os.mkfifo(self.path)
        self.assertEqual(self.state(), self.MISSING_BAD)

    def test_four_kib_exactly_is_accepted_and_one_more_is_not(self):
        body = '{"schema": 1, "pad": "%s"}'
        fill = 4096 - len(body % "")
        self.put(body % ("x" * fill))
        self.assertEqual(os.path.getsize(self.path), 4096)
        self.assertEqual(self.state(), "present")
        self.put(body % ("x" * (fill + 1)))
        self.assertEqual(self.state(), self.MISSING_BAD)

    def test_a_size_that_grew_after_lstat_is_still_bounded(self):
        self.put('{"schema": 1, "pad": "%s"}' % ("x" * 5000))
        real = os.lstat(self.path)
        small = unittest.mock.Mock(st_mode=real.st_mode, st_size=10)
        with unittest.mock.patch.object(install.os, "lstat", return_value=small):
            self.assertEqual(self.state(), self.MISSING_BAD)

    def test_a_symlink_to_a_device_is_refused_without_reading_it(self):
        os.symlink("/dev/zero", self.path)
        self.assertEqual(self.state(), self.MISSING_BAD)

    def test_odd_override_values_are_missing_and_never_raise(self):
        for value in ("\0", "/tmp/\0x", "/tmp/new\nline", "/" + "x" * 70000, "~", ""):
            with self.subTest(value=value[:20]):
                self.assertEqual(install.read_marker("claude", value), "missing")

    def test_a_symlinked_parent_directory_is_followed(self):
        self.put('{"schema": 1}')
        link = os.path.join(self.tmp.name, "link")
        os.symlink(self.dir, link)
        self.assertEqual(install.read_marker("claude", link), "present")

    def test_the_marker_is_found_through_the_password_database_not_home(self):
        home = os.path.join(self.tmp.name, "home")
        os.makedirs(os.path.join(home, ".claude"))
        with open(os.path.join(home, ".claude", "global-config.json"), "w") as handle:
            handle.write('{"schema": 1}')
        elsewhere = os.path.join(self.tmp.name, "elsewhere")
        os.makedirs(os.path.join(elsewhere, ".claude"))
        fake = unittest.mock.Mock()
        fake.getpwuid.return_value = unittest.mock.Mock(pw_dir=home)
        with unittest.mock.patch.object(install, "pwd", fake), \
                unittest.mock.patch.dict(os.environ, {"HOME": elsewhere}):
            self.assertEqual(install.read_marker("claude"), "present")
        with unittest.mock.patch.object(install, "pwd", fake), \
                unittest.mock.patch.dict(os.environ, {"HOME": home}):
            fake.getpwuid.return_value = unittest.mock.Mock(pw_dir=elsewhere)
            self.assertEqual(install.read_marker("claude"), "missing")

    def test_a_relative_empty_or_unavailable_home_is_missing(self):
        for home in ("", "relative/home", None):
            with self.subTest(home=home):
                fake = unittest.mock.Mock()
                fake.getpwuid.return_value = unittest.mock.Mock(pw_dir=home)
                with unittest.mock.patch.object(install, "pwd", fake):
                    self.assertEqual(install.read_marker("claude"), "missing")
        with unittest.mock.patch.object(install, "pwd", None):
            self.assertEqual(install.read_marker("claude"), "missing")
        broken = unittest.mock.Mock()
        broken.getpwuid.side_effect = KeyError("no entry")
        with unittest.mock.patch.object(install, "pwd", broken):
            self.assertEqual(install.read_marker("claude"), "missing")

    def test_an_empty_or_relative_override_is_missing(self):
        self.put('{"schema": 1}')
        for value in ("", "cfg", os.path.relpath(self.dir)):
            with self.subTest(value=value):
                self.assertEqual(install.read_marker("claude", value), "missing")

    def test_the_option_is_refused_with_the_other_actions(self):
        for argv in (["--list"], ["--register", self.tmp.name], ["--unregister", "nope"],
                     ["--remove", "demo", "--dir", self.tmp.name]):
            with self.subTest(argv=argv):
                code, out, err = run(argv + ["--global-config", self.dir])
                self.assertEqual(code, 2)
                self.assertIn("--global-config", err)


class HelperTest(unittest.TestCase):
    """Plan 0020 increment B: helper detection on PATH, never running anything."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.bin = os.path.join(self.tmp.name, "bin")
        os.makedirs(self.bin)
        self.sentinel = os.path.join(self.tmp.name, "ran")
        saved = os.environ.get("PATH")
        self.addCleanup(lambda: os.environ.__setitem__("PATH", saved) if saved is not None
                        else os.environ.pop("PATH", None))

    def tool(self, name, mode=0o755, where=None):
        path = os.path.join(where or self.bin, name)
        with open(path, "w") as handle:
            handle.write("#!/bin/sh\ntouch %s\n" % self.sentinel)
        os.chmod(path, mode)
        return path

    def test_an_executable_file_is_present(self):
        self.tool("ask-codex")
        os.environ["PATH"] = self.bin
        self.assertTrue(install.find_helper("ask-codex"))
        self.assertFalse(install.find_helper("other"))

    def test_it_is_found_in_a_later_directory_and_never_run(self):
        later = os.path.join(self.tmp.name, "later")
        os.makedirs(later)
        self.tool("remote-runner", where=later)
        os.environ["PATH"] = os.pathsep.join([self.bin, later])
        self.assertTrue(install.find_helper("remote-runner"))
        self.assertFalse(os.path.exists(self.sentinel))

    def test_a_file_without_the_execute_bit_is_missing(self):
        self.tool("plain", mode=0o644)
        os.environ["PATH"] = self.bin
        self.assertFalse(install.find_helper("plain"))

    def test_a_directory_or_fifo_of_that_name_is_missing(self):
        os.mkdir(os.path.join(self.bin, "adir"))
        os.mkfifo(os.path.join(self.bin, "afifo"))
        os.environ["PATH"] = self.bin
        self.assertFalse(install.find_helper("adir"))
        self.assertFalse(install.find_helper("afifo"))

    def test_a_symlink_to_an_executable_counts_and_a_broken_one_does_not(self):
        real = self.tool("real", where=self.tmp.name)
        os.symlink(real, os.path.join(self.bin, "linked"))
        os.symlink(os.path.join(self.tmp.name, "gone"), os.path.join(self.bin, "dangling"))
        os.environ["PATH"] = self.bin
        self.assertTrue(install.find_helper("linked"))
        self.assertFalse(install.find_helper("dangling"))

    def test_relative_and_empty_path_entries_are_ignored(self):
        self.tool("tool")
        cwd = os.getcwd()
        self.addCleanup(os.chdir, cwd)
        os.chdir(self.bin)
        for path in ("", ".", "bin", os.pathsep, os.pathsep + "relative", ".." + os.pathsep + "."):
            os.environ["PATH"] = path
            self.assertFalse(install.find_helper("tool"), path)
        os.environ["PATH"] = os.pathsep + self.bin
        self.assertTrue(install.find_helper("tool"))

    def test_a_symlink_loop_is_missing(self):
        os.symlink(os.path.join(self.bin, "b"), os.path.join(self.bin, "a"))
        os.symlink(os.path.join(self.bin, "a"), os.path.join(self.bin, "b"))
        os.environ["PATH"] = self.bin
        self.assertFalse(install.find_helper("a"))

    def test_an_unset_path_finds_nothing(self):
        self.tool("tool")
        os.environ.pop("PATH", None)
        self.assertFalse(install.find_helper("tool"))


class HarnessPilotTest(ProjectCase):
    """Plan 0019: the real cad-freecad module ships the freecad-scripts skill."""

    SKILL = ".claude/skills/freecad-scripts"
    REFERENCES = ["assembly-and-3mf", "curves-and-curved-shapes", "geometry-and-shapes",
                  "gui-and-interface", "images-to-cad", "mesh-reverse-engineering",
                  "parametric-objects", "partdesign-and-parameters", "scripting-fundamentals",
                  "workbenches-and-advanced"]

    def files_expected(self):
        return sorted([self.SKILL + "/SKILL.md", self.SKILL + "/scripts/mesh_report.py"]
                      + [self.SKILL + "/references/%s.md" % name for name in self.REFERENCES])

    def tree(self):
        return install.read_harness_tree(install.load_modules()["cad-freecad"], "claude")

    def test_the_module_ships_exactly_the_skill(self):
        files, units = self.tree()
        self.assertEqual(sorted(files), self.files_expected())
        self.assertEqual(units, {self.SKILL: "freecad-scripts"})

    def test_no_file_points_at_the_global_install(self):
        files, _ = self.tree()
        for path, data in files.items():
            self.assertNotIn(b"~/.claude", data, path)
        skill = files[self.SKILL + "/SKILL.md"].decode("utf-8")
        self.assertIn(self.SKILL + "/scripts/mesh_report.py", skill)
        mesh = files[self.SKILL + "/references/mesh-reverse-engineering.md"].decode("utf-8")
        self.assertIn(self.SKILL + "/scripts", mesh)

    def test_the_skill_is_well_inside_the_limits(self):
        files, _ = self.tree()
        self.assertLess(sum(len(d) for d in files.values()), install.HARNESS_MAX_TREE_BYTES // 4)
        self.assertLess(max(len(d) for d in files.values()), install.HARNESS_MAX_FILE_BYTES // 4)

    def new_pilot(self, with_, *extra):
        return run([self.target(), "--with", with_, "--git-name", "Test User",
                    "--git-email", "tester@users.noreply.example.invalid", *extra])

    def manifest(self):
        return json.loads(self.read(".template-manifest"))

    def test_new_with_the_harness_installs_and_records_the_skill(self):
        code, out, err = self.new_pilot("cad-freecad", "--harness", "claude")
        self.assertEqual(code, 0, err)
        for rel in self.files_expected():
            self.assertTrue(os.path.isfile(self.path(rel)), rel)
        manifest = self.manifest()
        self.assertEqual((manifest["schema"], manifest["harness"]), (2, "claude"))
        self.assertEqual(sorted(manifest["harness_files"]), self.files_expected())
        for entry in manifest["harness_files"].values():
            self.assertEqual(entry["modules"], ["cad-freecad"])
        self.assertEqual(os.stat(self.path(self.SKILL + "/scripts/mesh_report.py")).st_mode & 0o111, 0)
        self.assertNotIn("Unresolved placeholders:\n  .claude", out)

    def test_the_hint_points_at_the_option(self):
        code, out, err = self.new_pilot("cad-freecad")
        self.assertEqual(code, 0, err)
        self.assertIn("cad-freecad: pass --harness claude", out)
        shutil.rmtree(self.target())
        self.assertEqual(self.new_pilot("cad")[0], 0)
        code, out, err = run(["--add", "cad-freecad", "--dir", self.target(), "--dry-run"])
        self.assertEqual(code, 0, err)
        self.assertIn("cad-freecad: pass --harness claude", out)

    def test_new_without_the_harness_installs_nothing_extra(self):
        self.assertEqual(self.new_pilot("cad-freecad")[0], 0)
        self.assertFalse(os.path.exists(self.path(".claude")))
        manifest = self.manifest()
        self.assertEqual(manifest["schema"], 1)
        self.assertNotIn("harness_files", manifest)

    def test_add_with_the_harness_installs_the_skill_for_an_installed_module(self):
        self.assertEqual(self.new_pilot("cad-freecad")[0], 0)
        code, out, err = run(["--add", "graphify", "--harness", "claude", "--dir", self.target()])
        self.assertEqual(code, 0, err)
        self.assertEqual(sorted(self.manifest()["harness_files"]), self.files_expected())

    def test_update_leaves_an_unedited_tree_alone_and_keeps_an_edit(self):
        self.assertEqual(self.new_pilot("cad-freecad", "--harness", "claude")[0], 0)
        code, out, err = self.update()
        self.assertEqual(code, 0, err)
        self.assertNotIn("conflict", out)
        reference = self.SKILL + "/references/images-to-cad.md"
        self.write(reference, "my notes\n")
        code, out, err = self.update()
        self.assertEqual(code, 0, err)
        self.assertIn("conflict " + reference, out)
        self.assertEqual(self.read(reference), "my notes\n")

    def test_remove_deletes_the_unedited_skill_and_the_emptied_directories(self):
        self.assertEqual(self.new_pilot("cad-freecad", "--harness", "claude")[0], 0)
        kept = self.SKILL + "/references/images-to-cad.md"
        self.write(kept, "my notes\n")
        code, out, err = run(["--remove", "cad-freecad", "--dir", self.target()])
        self.assertEqual(code, 0, err)
        self.assertEqual(os.listdir(self.path(self.SKILL)), ["references"])
        self.assertEqual(os.listdir(self.path(self.SKILL + "/references")), ["images-to-cad.md"])
        self.assertEqual(self.manifest()["harness_files"], {})
        self.write(kept, "")
        os.unlink(self.path(kept))
        self.assertEqual(self.new_pilot("cad-freecad", "--harness", "claude")[0], 2)  # target exists

    def test_remove_with_no_edits_leaves_no_skill_directory(self):
        self.assertEqual(self.new_pilot("cad-freecad", "--harness", "claude")[0], 0)
        self.assertEqual(run(["--remove", "cad-freecad", "--dir", self.target()])[0], 0)
        self.assertFalse(os.path.exists(self.path(".claude")))

    def test_the_script_is_not_stored_executable(self):
        meta = install.load_modules()["cad-freecad"]
        script = os.path.join(meta["path"], "harness", "claude", "skills", "freecad-scripts",
                              "scripts", "mesh_report.py")
        self.assertFalse(os.stat(script).st_mode & 0o111)


class DeclarationReportTest(HarnessCase):
    """Plan 0020 increment C: the dependency report for new, add and update."""

    EXTRACTOR = "reads the listed files, writes one chunk"

    def setUp(self):
        super().setUp()
        self.bin = os.path.join(self.work, "bin")
        os.makedirs(self.bin)
        self.sentinel = os.path.join(self.work, "ran")
        self.cfg = os.path.join(self.work, "cfg")
        os.makedirs(self.cfg)
        self.marker = os.path.join(self.cfg, "global-config.json")
        with open(self.marker, "w") as handle:
            handle.write('{"schema": 1}')
        self.tool("zz-tool-a")
        os.environ["PATH"] = self.bin + os.pathsep + os.environ.get("PATH", "")  # git must still run

    def tool(self, name):
        path = os.path.join(self.bin, name)
        with open(path, "w") as handle:
            handle.write("#!/bin/sh\ntouch %s\n" % self.sentinel)
        os.chmod(path, 0o755)

    def dep(self, name="dep", **extra):
        meta = dict(helpers=["zz-tool-a", "zz-tool-b"], workers={"extractor": self.EXTRACTOR},
                    global_config=True)
        meta.update(extra)
        self.module(name, harness={"agents/e.md": "extractor\n",
                                   "harness.json": '{"roles": {"extractor": "agents/e.md"}}'}, **meta)

    def run_new(self, with_, *extra):
        return self.new_h(with_, "--global-config", self.cfg, *extra)

    def lines(self, out):
        return [line.strip() for line in out.splitlines()]

    def test_every_item_is_reported_for_a_new_project(self):
        self.dep()
        code, out, err = self.run_new("dep", "--harness", "claude")
        self.assertEqual(code, 0, err)
        lines = self.lines(out)
        self.assertIn("Declared dependencies:", lines)
        for expected in ("dep: helper zz-tool-a: present", "dep: helper zz-tool-b: missing",
                         "dep: worker extractor: implemented by dep",
                         "dep: global configuration: present"):
            self.assertIn(expected, lines)
        self.assertFalse(os.path.exists(self.sentinel))

    def test_dry_run_reports_too(self):
        self.dep()
        code, out, err = self.run_new("dep", "--harness", "claude", "--dry-run")
        self.assertEqual(code, 0, err)
        self.assertIn("dep: helper zz-tool-b: missing", self.lines(out))
        self.assertFalse(os.path.exists(self.target()))

    def test_a_missing_or_invalid_marker_is_reported_without_its_contents(self):
        self.dep()
        os.unlink(self.marker)
        out = self.run_new("dep", "--harness", "claude")[1]
        self.assertIn("dep: global configuration: missing", self.lines(out))
        shutil.rmtree(self.target())
        with open(self.marker, "w") as handle:
            handle.write("SECRET-CONTENT")
        out = self.run_new("dep", "--harness", "claude")[1]
        self.assertIn("dep: global configuration: missing (unreadable or invalid marker)", self.lines(out))
        self.assertNotIn("SECRET", out)

    def test_missing_items_leave_the_exit_status_at_zero(self):
        self.dep()
        os.unlink(self.marker)
        code, out, err = self.run_new("dep", "--harness", "claude")
        self.assertEqual(code, 0, err)
        self.assertIn("helper zz-tool-b: missing", out)

    def test_a_role_that_is_not_implemented_is_a_warning_with_its_contract(self):
        self.module("unmapped", harness={"agents/e.md": "x\n", "harness.json": '{"roles": {}}'},
                    workers={"extractor": self.EXTRACTOR})
        self.module("bare", workers={"extractor": self.EXTRACTOR})
        out = self.run_new("unmapped,bare", "--harness", "claude")[1]
        for module in ("unmapped", "bare"):
            self.assertIn("%s: warning: claude does not implement worker extractor (%s)"
                          % (module, self.EXTRACTOR), self.lines(out))

    def test_a_role_in_harness_json_that_the_module_did_not_declare_prints_nothing(self):
        self.module("quiet", harness={"agents/e.md": "x\n",
                                      "harness.json": '{"roles": {"extractor": "agents/e.md"}}'})
        out = self.run_new("quiet", "--harness", "claude")[1]
        self.assertNotIn("worker", out)
        self.assertNotIn("Declared dependencies", out)

    def test_a_mapped_file_skipped_as_a_conflict_does_not_count_as_implemented(self):
        self.dep()
        self.module("other")
        self.assertEqual(self.new_h("dep")[0], 0)
        os.makedirs(self.path(".claude/agents"))
        self.write(".claude/agents/e.md", "mine\n")
        code, out, err = run(["--add", "other", "--harness", "claude", "--global-config", self.cfg,
                              "--dir", self.target()])
        self.assertEqual(code, 0, err)
        self.assertIn("dep: warning: claude does not implement worker extractor (%s)" % self.EXTRACTOR,
                      self.lines(out))
        self.assertIn("conflict .claude/agents/e.md", out)

    def test_without_a_harness_helpers_are_checked_and_the_rest_says_so(self):
        self.dep()
        code, out, err = self.run_new("dep")
        self.assertEqual(code, 0, err)
        lines = self.lines(out)
        self.assertIn("dep: helper zz-tool-a: present", lines)
        self.assertIn("dep: worker extractor: no harness selected", lines)
        self.assertIn("dep: global configuration: no harness selected", lines)

    def test_modules_without_declarations_print_nothing(self):
        self.module("plain")
        out = self.run_new("plain", "--harness", "claude")[1]
        self.assertNotIn("Declared dependencies", out)

    def test_add_reports_the_added_module_and_activation_reports_every_installed_one(self):
        self.dep()
        self.dep("dep2", helpers=["zz-tool-a"], workers={}, global_config=False)
        self.module("plain")
        self.assertEqual(self.new_h("plain", "--harness", "claude")[0], 0)
        out = run(["--add", "dep2", "--global-config", self.cfg, "--dir", self.target()])[1]
        self.assertIn("dep2: helper zz-tool-a: present", self.lines(out))
        self.assertNotIn("dep:", out.replace("dep2:", ""))
        shutil.rmtree(self.target())
        self.assertEqual(self.new_h("dep,plain")[0], 0)
        out = run(["--add", "dep2", "--harness", "claude", "--global-config", self.cfg,
                   "--dir", self.target()])[1]
        self.assertIn("dep: worker extractor: implemented by dep", self.lines(out))
        self.assertIn("dep2: helper zz-tool-a: present", self.lines(out))

    def test_adding_an_installed_module_prints_nothing_and_update_reports_it(self):
        self.dep()
        self.assertEqual(self.run_new("dep", "--harness", "claude")[0], 0)
        out = run(["--add", "dep", "--global-config", self.cfg, "--dir", self.target()])[1]
        self.assertIn("Nothing to add", out)
        self.assertNotIn("Declared dependencies", out)
        shutil.rmtree(self.target())
        self.assertEqual(self.new_h("dep")[0], 0)
        out = run(["--add", "dep", "--global-config", self.cfg, "--dir", self.target()])[1]
        self.assertIn("Nothing to add", out)
        self.assertNotIn("Declared dependencies", out)
        code, out, err = self.update("--global-config", self.cfg)
        self.assertEqual(code, 0, err)
        self.assertIn("dep: helper zz-tool-a: present", self.lines(out))

    def test_update_reports_even_when_there_is_nothing_to_update(self):
        self.dep()
        self.assertEqual(self.run_new("dep", "--harness", "claude")[0], 0)
        code, out, err = self.update("--global-config", self.cfg)
        self.assertEqual(code, 0, err)
        self.assertIn("Nothing to update", out)
        self.assertIn("dep: worker extractor: implemented by dep", self.lines(out))
        self.assertIn("dep: global configuration: present", self.lines(out))

    def test_update_of_a_named_module_reports_only_that_module(self):
        self.dep()
        self.dep("dep2", helpers=["zz-tool-a"], workers={}, global_config=False)
        self.assertEqual(self.run_new("dep,dep2", "--harness", "claude")[0], 0)
        out = self.update("dep2", "--global-config", self.cfg)[1]
        self.assertIn("dep2: helper zz-tool-a: present", self.lines(out))
        self.assertNotIn("dep: ", out.replace("dep2: ", ""))

    def test_a_failing_report_cannot_fail_an_install(self):
        self.dep()
        with unittest.mock.patch.object(install, "report_declarations",
                                        side_effect=RuntimeError("boom")):
            code, out, err = self.run_new("dep", "--harness", "claude")
        self.assertEqual(code, 0, err)
        self.assertIn("dependency report failed", out)
        self.assertTrue(os.path.exists(self.path(".claude/agents/e.md")))
        self.assertNotIn("boom", out)

    def test_a_dry_run_says_would_be_implemented(self):
        self.dep()
        out = self.run_new("dep", "--harness", "claude", "--dry-run")[1]
        self.assertIn("dep: worker extractor: would be implemented by dep", self.lines(out))
        shutil.rmtree(self.target(), ignore_errors=True)
        out = self.run_new("dep", "--harness", "claude")[1]
        self.assertIn("dep: worker extractor: implemented by dep", self.lines(out))

    def test_the_option_changes_nothing_that_is_installed_or_recorded(self):
        self.dep()
        trees = []
        for label, extra in (("p1", ["--global-config", self.cfg]), ("p2", [])):
            target = os.path.join(self.work, label)
            code, out, err = run([target, "--with", "dep", "--harness", "claude", "--name", "same",
                                  "--git-name", "T", "--git-email", "t@users.noreply.example.invalid",
                                  *extra])
            self.assertEqual(code, 0, err)
            trees.append(read_tree(target))
        self.assertEqual(trees[0], trees[1])

    def test_dry_runs_of_add_and_update_write_nothing(self):
        self.dep()
        self.module("plain")
        self.assertEqual(self.new_h("plain", "--harness", "claude")[0], 0)
        before = read_tree(self.target())
        code, out, err = run(["--add", "dep", "--dry-run", "--global-config", self.cfg,
                              "--dir", self.target()])
        self.assertEqual(code, 0, err)
        self.assertIn("dep: helper zz-tool-a: present", self.lines(out))
        self.assertEqual(read_tree(self.target()), before)
        self.assertEqual(run(["--add", "dep", "--dir", self.target()])[0], 0)
        before = read_tree(self.target())
        os.unlink(self.path(".claude/agents/e.md"))
        code, out, err = self.update("--dry-run", "--global-config", self.cfg)
        self.assertEqual(code, 0, err)
        self.assertFalse(os.path.exists(self.path(".claude/agents/e.md")))

    def test_the_fake_helper_is_never_run(self):
        self.dep()
        self.assertEqual(self.run_new("dep", "--harness", "claude")[0], 0)
        self.update("--global-config", self.cfg)
        run(["--add", "dep", "--dir", self.target()])
        self.assertFalse(os.path.exists(self.sentinel))


class HarnessFormalTest(ProjectCase):
    """Plan 0021: the real formal module ships the verilog-sby-formal skill."""

    SKILL = ".claude/skills/verilog-sby-formal"
    FILES = [SKILL + "/SKILL.md", SKILL + "/reference.md"]

    def tree(self):
        return install.read_harness_tree(install.load_modules()["formal"], "claude")

    def new_formal(self, with_, *extra):
        return run([self.target(), "--with", with_, "--git-name", "Test User",
                    "--git-email", "tester@users.noreply.example.invalid", *extra])

    def manifest(self):
        return json.loads(self.read(".template-manifest"))

    def test_the_module_ships_exactly_the_skill(self):
        files, units = self.tree()
        self.assertEqual(sorted(files), sorted(self.FILES))
        self.assertEqual(units, {self.SKILL: "verilog-sby-formal"})

    def test_the_text_is_self_contained(self):
        files, _ = self.tree()
        for path, data in files.items():
            self.assertNotIn(b"~/.claude", data, path)
        self.assertIn("reference.md", files[self.SKILL + "/SKILL.md"].decode("utf-8"))
        self.assertLess(sum(len(d) for d in files.values()), install.HARNESS_MAX_TREE_BYTES // 20)

    def test_new_with_the_harness_installs_and_records_the_skill(self):
        code, out, err = self.new_formal("formal", "--harness", "claude")
        self.assertEqual(code, 0, err)
        for rel in self.FILES:
            self.assertTrue(os.path.isfile(self.path(rel)), rel)
        manifest = self.manifest()
        self.assertEqual((manifest["schema"], manifest["harness"]), (2, "claude"))
        self.assertEqual(sorted(manifest["harness_files"]), sorted(self.FILES))
        for entry in manifest["harness_files"].values():
            self.assertEqual(entry["modules"], ["formal"])

    def test_new_without_the_harness_installs_nothing_extra(self):
        self.assertEqual(self.new_formal("formal")[0], 0)
        self.assertFalse(os.path.exists(self.path(".claude")))
        self.assertEqual(self.manifest()["schema"], 1)
        self.assertNotIn("harness_files", self.manifest())

    def test_the_add_paths(self):
        self.assertEqual(self.new_formal("cad")[0], 0)
        code, out, err = run(["--add", "formal", "--harness", "claude", "--dir", self.target()])
        self.assertEqual(code, 0, err)
        self.assertEqual(sorted(self.manifest()["harness_files"]), sorted(self.FILES))
        shutil.rmtree(self.target())
        self.assertEqual(self.new_formal("cad")[0], 0)
        self.assertEqual(run(["--add", "formal", "--dir", self.target()])[0], 0)
        self.assertFalse(os.path.exists(self.path(".claude")))
        self.assertNotIn("harness", self.manifest())
        shutil.rmtree(self.target())
        self.assertEqual(self.new_formal("cad", "--harness", "claude")[0], 0)
        self.assertEqual(run(["--add", "formal", "--dir", self.target()])[0], 0)
        self.assertEqual(sorted(self.manifest()["harness_files"]), sorted(self.FILES))
        shutil.rmtree(self.target())
        self.assertEqual(self.new_formal("formal")[0], 0)
        code, out, err = run(["--add", "formal", "--harness", "claude", "--dir", self.target()])
        self.assertEqual(code, 0, err)
        self.assertEqual(sorted(self.manifest()["harness_files"]), sorted(self.FILES))

    def test_update_leaves_an_unedited_tree_alone_and_keeps_an_edit(self):
        self.assertEqual(self.new_formal("formal", "--harness", "claude")[0], 0)
        code, out, err = self.update()
        self.assertEqual(code, 0, err)
        self.assertNotIn("conflict", out)
        self.write(self.SKILL + "/reference.md", "my notes\n")
        code, out, err = self.update()
        self.assertEqual(code, 0, err)
        self.assertIn("conflict " + self.SKILL + "/reference.md", out)
        self.assertEqual(self.read(self.SKILL + "/reference.md"), "my notes\n")

    def test_remove_deletes_the_unedited_skill_and_keeps_an_edit(self):
        self.assertEqual(self.new_formal("formal", "--harness", "claude")[0], 0)
        self.write(self.SKILL + "/reference.md", "my notes\n")
        code, out, err = run(["--remove", "formal", "--dir", self.target()])
        self.assertEqual(code, 0, err)
        self.assertEqual(os.listdir(self.path(self.SKILL)), ["reference.md"])
        self.assertEqual(self.manifest()["harness_files"], {})

    def test_remove_with_no_edits_leaves_no_skill_directory(self):
        self.assertEqual(self.new_formal("formal", "--harness", "claude")[0], 0)
        self.assertEqual(run(["--remove", "formal", "--dir", self.target()])[0], 0)
        self.assertFalse(os.path.exists(self.path(".claude")))

    def test_the_hint_points_at_the_option(self):
        code, out, err = self.new_formal("formal")
        self.assertEqual(code, 0, err)
        self.assertIn("formal: pass --harness claude", out)


class HarnessNewProjectTest(HarnessCase):
    """Plan 0018 increment C: --harness with a new project."""

    def test_new_installs_the_units_and_records_them(self):
        self.demo()
        code, out, err = self.new_h("demo", "--harness", "claude")
        self.assertEqual(code, 0, err)
        self.assertEqual(self.read(".claude/skills/x/SKILL.md").splitlines()[-1],
                         "Skill body for proj")
        self.assertEqual(self.read(".claude/agents/a.md"), "---\nname: agent-a\n---\nagent\n")
        self.assertEqual(self.read("CLAUDE.md"), "@AGENTS.md\n")
        self.assertFalse(os.path.exists(self.path(".claude/harness.json")))
        manifest = self.manifest()
        self.assertEqual((manifest["schema"], manifest["harness"]), (2, "claude"))
        self.assertEqual(sorted(manifest["harness_files"]), [
            ".claude/agents/a.md", ".claude/commands/c.md", ".claude/skills/x/SKILL.md", "CLAUDE.md"])
        import hashlib
        with open(self.path(".claude/skills/x/SKILL.md"), "rb") as handle:
            digest = hashlib.sha256(handle.read()).hexdigest()
        self.assertEqual(manifest["harness_files"][".claude/skills/x/SKILL.md"],
                         {"sha256": digest, "modules": ["demo"]})

    def test_without_the_option_nothing_is_installed_and_the_manifest_is_unchanged(self):
        self.demo()
        self.assertEqual(self.new_h("demo")[0], 0)
        self.assertFalse(os.path.exists(self.path(".claude")))
        self.assertFalse(os.path.exists(self.path("CLAUDE.md")))
        manifest = self.manifest()
        self.assertEqual(manifest["schema"], 1)
        self.assertNotIn("harness", manifest)
        self.assertNotIn("harness_files", manifest)

    def test_unknown_harness_is_refused_before_anything_is_written(self):
        self.demo()
        for value in ("nope", "Claude", "x" * 40, ""):
            with self.subTest(value=value):
                code, out, err = self.new_h("demo", "--harness", value)
                self.assertEqual(code, 2)
                self.assertFalse(os.path.exists(self.target()))
        self.assertNotIn("x" * 40, self.new_h("demo", "--harness", "x" * 40)[2])

    def test_option_is_refused_with_the_other_actions(self):
        self.demo()
        for argv in (["--list", "--harness", "claude"],
                     ["--register", self.work, "--harness", "claude"],
                     ["--unregister", "nope", "--harness", "claude"],
                     ["--remove", "demo", "--harness", "claude", "--dir", self.work]):
            with self.subTest(argv=argv):
                code, out, err = run(argv)
                self.assertEqual(code, 2)
                self.assertIn("--harness", err)

    def test_two_modules_with_different_bytes_fail_before_any_write(self):
        self.module("one", harness={"agents/a.md": "one\n"})
        self.module("two", harness={"agents/a.md": "two\n"})
        code, out, err = self.new_h("one,two", "--harness", "claude")
        self.assertEqual(code, 2)
        self.assertIn(".claude/agents/a.md", err)
        self.assertFalse(os.path.exists(self.target()))

    def test_identical_bytes_install_once_with_both_suppliers(self):
        self.module("one", harness={"agents/a.md": "same\n"})
        self.module("two", harness={"agents/a.md": "same\n"})
        self.assertEqual(self.new_h("one,two", "--harness", "claude")[0], 0)
        self.assertEqual(self.manifest()["harness_files"][".claude/agents/a.md"]["modules"],
                         ["one", "two"])

    def test_a_skill_unit_with_different_trees_fails(self):
        self.module("one", harness={"skills/s/SKILL.md": "---\nname: s\n---\n", "skills/s/a.md": "a\n"})
        self.module("two", harness={"skills/s/SKILL.md": "---\nname: s\n---\n"})
        code, out, err = self.new_h("one,two", "--harness", "claude")
        self.assertEqual(code, 2)
        self.assertFalse(os.path.exists(self.target()))

    def test_two_modules_naming_different_units_the_same_fail(self):
        self.module("one", harness={"agents/a.md": "---\nname: shared\n---\n"})
        self.module("two", harness={"agents/b.md": "---\nname: Shared\n---\n"})
        code, out, err = self.new_h("one,two", "--harness", "claude")
        self.assertEqual(code, 2)
        self.assertIn("shared", err.lower())
        self.assertFalse(os.path.exists(self.target()))

    def test_a_path_shipped_as_a_module_file_is_refused(self):
        self.module("one", harness={"agents/a.md": "h\n"})
        self.module("two", files={".claude/agents/a.md": "f\n"})
        code, out, err = self.new_h("one,two", "--harness", "claude")
        self.assertEqual(code, 2)
        self.assertFalse(os.path.exists(self.target()))
        self.module("three", files={"claude.md": "f\n"})
        self.module("four", harness={"root/CLAUDE.md": "h\n"})
        self.assertEqual(self.new_h("three,four", "--harness", "claude")[0], 2)

    def test_placeholders_need_a_conservative_project_name(self):
        self.demo()
        code, out, err = run([os.path.join(self.work, "bad;name"), "--with", "demo",
                              "--harness", "claude", "--git-name", "T",
                              "--git-email", "t@users.noreply.example.invalid"])
        self.assertEqual(code, 2)
        self.assertFalse(os.path.exists(os.path.join(self.work, "bad;name")))
        self.module("plain", harness={"agents/p.md": "no placeholder\n"})
        code, out, err = run([os.path.join(self.work, "ok;name"), "--with", "plain",
                              "--harness", "claude", "--git-name", "T",
                              "--git-email", "t@users.noreply.example.invalid"])
        self.assertEqual(code, 0, err)

    def test_a_module_without_the_harness_directory_keeps_its_neutral_part(self):
        self.demo()
        self.module("neutral", files={"notes.txt": "n\n"})
        code, out, err = self.new_h("demo,neutral", "--harness", "claude")
        self.assertEqual(code, 0, err)
        self.assertIn("neutral: no claude files", out)
        self.assertNotIn("demo: no claude files", out)
        self.assertEqual(self.read("notes.txt"), "n\n")

    def test_per_run_limits_across_modules(self):
        for n in range(5):  # 5 x 103 files: each module is within 128, the run is over 512
            self.module("m%d" % n, harness={"skills/s%d/f%03d.md" % (n, i): "x\n" for i in range(103)})
        code, out, err = self.new_h("m0,m1,m2,m3,m4", "--harness", "claude")
        self.assertEqual(code, 2)
        self.assertIn("512", err)
        self.assertFalse(os.path.exists(self.target()))
        for n in range(5):  # 5 x 2 MiB: each tree is at its limit, the run is over 8 MiB
            self.module("b%d" % n, harness={"skills/s%d/f%d.md" % (n, i): "a" * (256 * 1024)
                                            for i in range(8)})
        code, out, err = self.new_h("b0,b1,b2,b3,b4", "--harness", "claude")
        self.assertEqual(code, 2)
        self.assertIn("8 MiB", err)
        self.assertFalse(os.path.exists(self.target()))

    def test_neutrality_ignores_harness_files_and_still_covers_the_rest(self):
        self.module("tooled", harness={"agents/a.md": "uses ask-codex and second-opinion\n"},
                    files={"notes.md": "neutral\n"})
        self.assertEqual(self.new_h("tooled", "--harness", "claude")[0], 0)
        self.assertIn("ask-codex", self.read(".claude/agents/a.md"))
        self.assertEqual(neutrality_problems(self.target()), [])
        self.module("leaky", files={"notes.md": "uses ask-codex\n"})
        shutil.rmtree(self.target())
        self.assertEqual(self.new_h("leaky", "--harness", "claude")[0], 0)
        problems = neutrality_problems(self.target())
        self.assertIn(("notes.md", "ask-codex"), problems)
        self.assertEqual({path for path, _ in problems}, {"notes.md"})

    def test_dry_run_lists_the_files_and_writes_nothing(self):
        self.demo()
        code, out, err = self.new_h("demo", "--harness", "claude", "--dry-run")
        self.assertEqual(code, 0, err)
        self.assertIn("would write .claude/skills/x/SKILL.md", out)
        self.assertIn("would write CLAUDE.md", out)
        self.assertFalse(os.path.exists(self.target()))

    def test_files_are_created_644_and_never_copy_a_replaced_mode(self):
        target = os.path.join(self.work, "wt")
        os.makedirs(target)
        old_umask = os.umask(0)
        self.addCleanup(os.umask, old_umask)
        victim = os.path.join(target, "victim")
        with open(victim, "w") as handle:
            handle.write("old")
        os.chmod(victim, 0o4755)
        install.write_tree(target, {"victim": b"new", "fresh": b"x", "plain": b"y"},
                           private={"victim", "fresh"})
        self.assertEqual(os.stat(victim).st_mode & 0o7777, 0o644)
        self.assertEqual(os.stat(os.path.join(target, "fresh")).st_mode & 0o7777, 0o644)
        self.assertEqual(os.stat(os.path.join(target, "plain")).st_mode & 0o7777, 0o666)
        with open(os.path.join(target, "plain"), "w") as handle:
            handle.write("old")
        os.chmod(os.path.join(target, "plain"), 0o755)
        install.write_tree(target, {"plain": b"z"})  # existing behaviour: the mode is kept
        self.assertEqual(os.stat(os.path.join(target, "plain")).st_mode & 0o7777, 0o755)


class ModuleHygieneTest(unittest.TestCase):
    def test_every_built_in_harness_tree_reads_clean(self):
        for name, meta in install.load_modules().items():
            for harness in install.HARNESSES:
                with self.subTest(module=name, harness=harness):
                    install.read_harness_tree(meta, harness)


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
