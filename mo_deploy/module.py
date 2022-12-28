# encoding: utf-8
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this file,
# You can obtain one at http://mozilla.org/MPL/2.0/.
#
# Author: Kyle Lahnakoski (kyle@lahnakoski.com)
#
from __future__ import division, unicode_literals

from collections import Mapping

import yaml

from mo_deploy.utils import Requirement, parse_req
from mo_dots import coalesce, listwrap, to_data
from mo_dots.lists import last
from mo_files import File, TempDirectory, URL, os_path
from mo_future import is_binary, is_text, sort_using_key, text, first
from mo_http import http
from mo_json import value2json, json2value
from mo_logs import Except, Log, strings
from mo_math import randoms, is_number
from mo_threads import Thread, Till
from mo_threads.multiprocess import Command
from mo_times import Timer
from pyLibrary.meta import cache
from pyLibrary.utils import Version

NO_VERSION = Version((-1,))
FIRST_VERSION = Version("0.0.0")
SETUPTOOLS = "setuptools.json"  # CONFIGURATION EXPECTED TO MAKE A setup.py FILE


class Module(object):
    # FULL PATH TO EXECUTABLES
    git = "git"
    svn = "svn"
    twine = "twine"
    python = {"3.7": "python"}
    python_requires = ">=2.7"
    ignore_svn = []
    test_versions = []

    def __init__(self, info, graph):
        if isinstance(info, Mapping):
            self.master_branch = coalesce(info.deploy_branch, "master")
            self.dev_branch = coalesce(info.dev_branch, "dev")
            self.directory = File(info.location)
            self.name = coalesce(info.name, self.directory.name.replace("_", "-"))
        else:
            self.master_branch = "master"
            self.dev_branch = "dev"
            self.directory = File(info)
            self.name = self.directory.name.replace("_", "-")
        self.graph = graph
        self.all_versions = []

    def deploy(self):
        self.setup()
        self.svn_update()
        self.update_dev("updates from other projects")

        curr_version, revision = self.get_version()
        next_version = self.graph.get_next_version(self.name)
        if curr_version == next_version:
            Log.error("{{module}} does not need deploy", module=self.name)

        master_rev = self.master_revision()
        try:
            self.update_setup_json_file(next_version)
            self.synch_travis_file()
            self.gen_setup_py_file()
            self.local(
                [
                    self.python["latest"],
                    "-c",
                    "from "
                    + self.name.replace("-", "_")
                    + " import __deploy__; __deploy__()",
                ],
                raise_on_error=False,
            )
            self.update_dev("update version number")

            # RUN TESTS IN PARALLEL
            while True:
                try:
                    test_threads = [
                        Thread.run("test " + v, self.run_tests, v)
                        for v in self.test_versions
                    ]
                    Thread.join_all(test_threads)
                    # for v in self.test_versions:
                    #     self.run_tests(v, None)
                    break
                except Exception as cause:
                    Log.warning("Tests did not pass", cause=cause)
                    value = input("Did not pass tests.  Try again? (y/N): ")
                    if value not in "yY":
                        Log.error("Can not install self", cause=cause)

            self.update_master_locally(next_version)
            self.pypi()
            self.local([self.git, "push", "origin", self.master_branch])
        except Exception as cause:
            cause = Except.wrap(cause)
            self.local([self.git, "checkout", "-f", master_rev])
            self.local(
                [self.git, "tag", "--delete", text(next_version)], raise_on_error=False,
            )
            self.local(
                [self.git, "branch", "-D", self.master_branch], raise_on_error=False
            )
            self.local([self.git, "checkout", "-b", self.master_branch])
            Log.error("Can not deploy {{module}}", module=self.name, cause=cause)
        finally:
            self.local([self.git, "checkout", self.dev_branch])

    def setup(self):
        self.local([self.git, "checkout", self.dev_branch])
        self.local([self.git, "merge", self.master_branch])

    def synch_travis_file(self):
        travis_file = self.directory / ".travis.yml"
        if travis_file.exists:
            Log.note("synch .travis.yml file")

            setup = (self.directory / SETUPTOOLS).read_json(leaves=False)
            tested_versions = [
                c.split("::")[-1].strip()
                for c in setup.classifiers
                if c.startswith("Programming Language :: Python :: ")
            ]
            content = yaml.safe_load(travis_file.read())
            content["python"] = list(map(
                lambda v: float(v) if is_number(v) else v,
                map(
                    str,
                    sorted(
                        Version(str(v) if str(v) != "3.7" else "3.7.8")  # ONLY 3.7.8 IS STABLE ON TRAVIS
                        for v in tested_versions
                    ),
                ),
            ))
            travis_file.write(yaml.dump(
                content, default_flow_style=False, sort_keys=False
            ))

    def gen_setup_py_file(self):
        setup_file = self.directory / "setup.py"
        Log.note("write setup.py")
        setup = (self.directory / SETUPTOOLS).read_json(leaves=False)
        setup_file.write(
            "# encoding: utf-8\n"
            + "# THIS FILE IS AUTOGENERATED!\n"
            + "from __future__ import unicode_literals\n"
            + "from setuptools import setup\n"
            + "setup(\n"
            + ",\n".join(
                "    " + k + "=" + value2python(v)
                for k, v in setup.items()
                if v != None
            )
            + "\n"
            + ")"
        )

    @cache()
    def last_deploy(self):
        url = URL("https://pypi.org/pypi") / self.name / "json"
        try:
            return max(
                Version(k, prefix="v") for k in http.get_json(url).releases.keys()
            )
        except Exception as e:
            Log.warning("could not get version from {{url}}", url=url, cause=e)
            return NO_VERSION

    def scrub_pypi_residue(self):
        (self.directory / "README.txt").delete()
        (self.directory / "build").delete()
        (self.directory / "dist").delete()
        (
            self.directory / (self.directory.name.replace("-", "_") + ".egg-info")
        ).delete()

        for f in self.directory.leaves:
            if f.extension == "pyc":
                f.delete()

    def pypi(self):
        # ENSURE THE API TOKEN IS SET.  twine USES keyring:
        #     C:\Users\kyle>keyring get https://upload.pypi.org/legacy/ __token__
        #
        #    C:\Users\kyle>keyring set https://upload.pypi.org/legacy/ __token__
        #    Password for '__token__' in 'https://upload.pypi.org/legacy/':
        #

        Log.note("Update PyPi for {{dir}}", dir=self.directory.abs_path)
        try:
            self.scrub_pypi_residue()

            # INSTRUCTIONS FOR USE OF pyproject.toml
            # pip install pep517
            # python -m pep517.build .
            # python setup.py --version
            #
            # pyproject.toml
            # [build-system]
            # requires = ["setuptools", "wheel"]
            # build-backend = "setuptools.build_meta"

            Log.note("run setup.py")
            self.local(
                [self.python["latest"], "setup.py", "sdist"], raise_on_error=True
            )

            Log.note("twine upload of {{dir}}", dir=self.directory.abs_path)
            # python3 -m twine upload --repository-url https://test.pypi.org/legacy/ dist/*
            process, stdout, stderr = self.local(
                [self.twine, "upload", "--verbose", "dist/*"],
                raise_on_error=False,
                show_all=True,
            )
            if "Upload failed (400): File already exists." in stderr:
                Log.error("Version exists. Not uploaded")
            elif "error: <urlopen error [Errno 11001] getaddrinfo failed>" in stderr:
                Log.error("No network. Not uploaded")
            elif process.returncode == 0:
                pass
            elif (
                "error: Upload failed (400): This filename has previously been used,"
                " you should use a different version."
                in stderr
            ):
                Log.error("Exists already in pypi")
            elif "503: Service Unavailable" in stderr:
                Log.error("Some big problem during upload")
            else:
                Log.error("not expected\n{{result}}", result=stdout + stderr)
        finally:
            self.scrub_pypi_residue()

        give_up_on_pypi = Till(seconds=90)
        while not give_up_on_pypi:
            Log.note(
                "WAIT FOR PYPI TO SHOW NEW VERSION {{version}}",
                version=self.graph.get_next_version(self.name),
            )
            Till(seconds=10).wait()
            """
            (.venv) C:\\Users\\kyle\\code\\mo-sql-parsing>pip install mo-collections==
            ERROR: Could not find a version that satisfies the requirement mo-collections== (from versions: 1.0.17035, 1.0.17036, 1.0.17039, 1.1.17039, 1.1.17040, 1.1.17041, 1.1.17049, 1.1.17056, 1.1.17085, 1.1.17131, 1.1.17227, 1.1.17229, 1.2.17235, 1.2.18029, 2.13.18154, 2.15.18155, 2.16.18199, 2.17.18212, 2.18.18240, 2.26.18331, 2.31.19025, 3.5.19316, 3.38.20029, 3.46.20032, 3.58.20089, 3.60.20091, 3.77.20190, 3.96.20290, 4.3.20340, 4.30.21121, 5.37.21239, 5.45.21241)
            ERROR: No matching distribution found for mo-collections==
            WARNING: You are using pip version 20.1.1; however, version 21.2.4 is available.
            You should consider upgrading via the 'c:\\python37\\python.exe -m pip install --upgrade pip' command.
            """
            p, stdout, stderr = self.local(
                [self.python["latest"], "-m", "pip", "install", self.name + "=="],
                raise_on_error=False,
            )
            if any(str(self.graph.get_next_version(self.name)) in e for e in stderr):
                Log.note("Found on pypi")
                break

    def update_setup_json_file(self, new_version):
        setup_json = self.directory / SETUPTOOLS
        readme = self.directory / "README.md"
        req_file = self.directory / "requirements.txt"
        test_req_file = self.directory / "tests" / "requirements.txt"

        # CHECK FILES EXISTENCE
        # if setup_file.exists:
        #     Log.error("expecting no setup.py file; it will be created from {{tools}}", tools=SETUPTOOLS)
        if not setup_json.exists:
            Log.error("expecting {{file}} file", file=setup_json)
        if not readme.exists:
            Log.error("expecting a README.md file to add to long_description")
        if not req_file.exists:
            Log.error("Expecting a requirements.txt file")

        # ENSURE PYTHON VERSION IS INCLUDED
        setup = setup_json.read_json(leaves=False)

        # FIND VERSIONS FOR TESTING
        self.test_versions = []
        for c in listwrap(setup.classifiers):
            if c.startswith("Programming Language :: Python ::"):
                version = c.split("::")[-1].strip()
                self.test_versions.append(version)
                if not self.python[version]:
                    Log.error(
                        'Expecting {{version}} in "general.python" settings',
                        version=version,
                    )
        if not self.test_versions:
            Log.error(
                "expecting language classifier, like 'Programming Language :: Python ::"
                " 3.7'"
            )

        # LONG DESCRIPTION
        setup.long_description_content_type = "text/markdown"
        setup.long_description = readme.read().replace("\r", "")

        # PACKAGES
        expected_packages = [
            dir_name.replace("/", ".")
            for f in self.directory.leaves
            if f.name == "__init__" and f.extension == "py"
            for dir_name in [f.parent.abs_path[len(self.directory.abs_path) + 1 :]]
            if dir_name
            and not dir_name.startswith("tests/")
            and not dir_name.startswith(".")
            and not dir_name.startswith("vendor/")
            and dir_name != "tests"
        ]
        package_dir = coalesce(setup.package_dir[""] + "/", "")
        declared_packages = [package_dir + p for p in setup.packages]
        if setup.packages == None:
            setup.packages = expected_packages
        elif set(declared_packages) != set(expected_packages):
            Log.warning(
                "Packages are {{existing}}. Maybe they should be {{proposed}}",
                existing=list(sorted(declared_packages)),
                proposed=list(sorted(expected_packages)),
            )

        # EXTRA DEPENDENCIES
        if test_req_file.exists:
            setup.extras_require.tests = [
                str(r)
                for line in test_req_file.read_lines()
                if line
                for r in [parse_req(line)]
                if r
            ]

        # VERSION
        setup.version = text(new_version)

        # REQUIRES
        reqs = self.get_next_requirements([
            r for line in setup.install_requires for r in [parse_req(line)] if r
        ])
        setup.install_requires = [
            r.name + r.type + text(r.version) if r.version else r.name
            for r in sort_using_key(reqs, key=lambda rr: rr.name)
        ]

        # WRITE JSON FILE
        setup_json.write(value2json(setup, pretty=True))

    def svn_update(self):
        self.local([self.git, "checkout", self.dev_branch])

        for d in self.directory.find(r"\.svn"):
            svn_dir = os_path(d.parent.abs_path)
            if any(d in svn_dir for d in listwrap(Module.ignore_svn)):
                Log.note("Ignoring svn directory {{dir}}", dir=svn_dir)
                continue

            Log.note("Update svn directory {{dir}}", dir=svn_dir)
            self.local([self.svn, "update", "--accept", "p", svn_dir])
            self.local([self.svn, "commit", svn_dir, "-m", "auto"])

    def update_dev(self, message):
        Log.note("Update git dev branch for {{dir}}", dir=self.directory.abs_path)
        self.scrub_pypi_residue()
        self.local([self.git, "add", "-A"])
        process, stdout, stderr = self.local(
            [self.git, "commit", "-m", message], raise_on_error=False
        )
        if (
            any(line.startswith("nothing to commit, working") for line in stdout)
            or process.returncode == 0
        ):
            pass
        else:
            Log.error("not expected {{result}}", result=(stdout, stderr))
        try:
            self.local([self.git, "push", "origin", self.dev_branch])
        except Exception as e:
            Log.warning(
                "git origin dev not updated for {{dir}}",
                dir=self.directory.name,
                cause=e,
            )

    def update_master_locally(self, version):
        Log.note("Update git master branch for {{dir}}", dir=self.directory.abs_path)
        try:
            v = text(version)
            self.local([self.git, "checkout", self.master_branch])
            self.local([self.git, "merge", "--no-ff", "--no-commit", self.dev_branch])
            self.local([self.git, "commit", "-m", "release " + v])
            self.local([self.git, "tag", v])
            self.local(
                [self.git, "push", "--delete", "origin", v], raise_on_error=False
            )
            self.local([self.git, "push", "origin", v])
        except Exception as e:
            Log.error(
                "git origin master not updated for {{dir}}",
                dir=self.directory.name,
                cause=e,
            )

    def run_tests(self, python_version, please_stop):
        if self.name == "pyLibrary":
            return

        # SETUP NEW ENVIRONMENT
        with TempDirectory() as temp:
            # python -m pip install virtualenv  # venv is buggy on Windows
            # REM IMPORTANT: Notice the dot in `.venv`
            # python -m virtualenv .venv
            # .venv\Scripts\activate
            # pip install -r requirements\dev.txt
            # pip install -r requirements\common.txt
            python = temp / ".venv" / "Scripts" / "python.exe"
            pip = temp / ".venv" / "Scripts" / "pip.exe"

            Log.note("install virtualenv into {{dir}}", dir=temp.abs_path)
            self.local([
                self.python[python_version],
                "-m",
                "pip",
                "install",
                "virtualenv",
            ])
            self.local(
                [self.python[python_version], "-m", "virtualenv", temp / ".venv"],
                cwd=temp,
            )
            Log.note("upgrade setuptools")
            self.local([pip, "install", "-U", "setuptools"])

            # CLEAN INSTALL FIRST, TO TEST FOR VERSION COMPATIBILITY
            try:
                Log.note("install self")
                p, stdout, stderr = self.local([pip, "install", "."], debug=True)
                if any("which is incompatible" in line for line in stderr):
                    Log.error("Seems we have an incompatibility problem")
                if any("conflicting dependencies" in line for line in stderr):
                    Log.error("Seems we have a conflicting dependencies problem")
            except Exception as cause:
                Log.error("Problem with install", cause=cause)

            # RUN THE SMOKE TEST
            Log.note("run tests/smoke_test.py")
            if (self.directory / "tests" / "smoke_test.py").exists:
                self.local(
                    [python, "-Werror", "tests/smoke_test.py"],
                    env={"PYTHONPATH": ""},
                    debug=True,
                )
            else:
                Log.warning(
                    "add tests/smoke_test.py to ensure the library will run after"
                    " installed"
                )

            # INSTALL TEST RESOURCES
            Log.note("install testing requirements")
            if (self.directory / "tests" / "requirements.txt").exists:
                self.local([
                    pip,
                    "install",
                    "--no-deps",
                    "-r",
                    "tests/requirements.txt",
                ])
                self.local([pip, "install", "-r", "tests/requirements.txt"], debug=True)

            # INSTALL SELF AGAIN TO ENSURE CORRECT VERSIONS ARE USED (EVEN IF CONFLICT WITH TEST RESOURCES)
            Log.note("install self")
            self.local([pip, "install", "."])

            with Timer("run tests"):
                process, stdout, stderr = self.local(
                    [python, "-m", "unittest", "discover", "tests"],
                    env={"PYTHONPATH": "."},
                    debug=True,
                )
                Log.note("TESTS DONE")
                if len(stderr) < 2:
                    Log.error(
                        "Expecting unittest results (at least two lines of output)"
                    )
                num_tests = int(strings.between(
                    first(line for line in reversed(stderr) if line.startswith("Ran ")),
                    "Ran ",
                    " test",
                ))
                if num_tests == 0:
                    Log.error(
                        "Expecting to run some tests: {{error}}", error=stderr[-2]
                    )
                if not last(stderr).startswith("OK"):
                    Log.error(
                        "Expecting all tests to pass: {{error}}", error=last(stderr)
                    )
                Log.note("STDERR:\n{{stderr|indent}}", stderr=stderr)
        Log.note("done")

    def local(
        self, args, raise_on_error=True, show_all=False, cwd=None, env=None, debug=False
    ):
        try:
            p = Command(
                self.name,
                args,
                cwd=coalesce(cwd, self.directory),
                env=env,
                max_stdout=10 ** 6,
                debug=debug,
            ).join(raise_on_error=raise_on_error)
            stdout = list(p.stdout)
            stderr = list(p.stderr)
            p.join()
            if show_all:
                Log.note(
                    "{{module}} stdout = {{stdout}}\nstderr = {{stderr}}",
                    module=self.name,
                    stdout=stdout,
                    stderr=stderr,
                    stack_depth=1,
                )
            return p, stdout, stderr
        except Exception as e:
            Log.error(
                "can not execute {{args}} in dir={{dir|quote}}",
                args=args,
                dir=os_path(self.directory.abs_path),
                cause=e,
            )

    def get_current_requirements(self, current_requires):
        # MAP FROM NAME TO CURRENT LIMITS
        lookup_old_requires = {r.name: r for r in current_requires}

        req = self.directory / "requirements.txt"
        output = to_data([
            r & lookup_old_requires.get(r.name)
            for line in req.read_lines()
            if line
            for r in [parse_req(line)]
            if r
        ])

        if any(r.name.startswith(("mo_", "jx_")) for r in output):
            Log.error("found problem in {{module}}", module=self.name)
        return output

    def get_next_requirements(self, current_requires):
        # MAP FROM NAME TO CURRENT LIMITS
        lookup_old_requires = {r.name: r for r in current_requires}

        req = self.directory / "requirements.txt"
        output = to_data([
            r & lookup_old_requires.get(r.name)
            if r.name not in self.graph.graph
            else Requirement(
                name=r.name, type="==", version=self.graph.get_version(r.name),
            )
            for line in req.read_lines()
            if line
            for r in [parse_req(line)]
            if r
        ])
        return output

    @cache()
    def get_version(self):
        # RETURN version, revision PAIR
        p, stdout, stderr = self.local([self.git, "tag"])
        # ONLY PICK VERSIONS WITH vX.Y.Z PATTERN
        all_versions = self.all_versions = list(sorted(
            v for line in stdout for v in [Version(line)]
        ))

        if all_versions:
            version = max(all_versions)
            try:
                p, stdout, stderr = self.local([self.git, "show", text(version)])
            except Exception:
                # HAPPENS WHEN NO VERSIONS ON NEW MODULE EXIST
                stdout = []
            for line in stdout:
                if line.startswith("commit "):
                    revision = line.split("commit")[1].strip()
                    return version, revision

        version = self.last_deploy()
        if version is NO_VERSION:
            version = FIRST_VERSION
        revision = self.master_revision()
        return version, revision

    @property
    def version(self):
        return self.get_version()[0]

    @cache(lock=True)
    def get_old_dependencies(self, version):
        # RETURN LIST OF {"name", "version"} dicts
        Log.note(
            "Find {{name}}=={{version}} in git history", name=self.name, version=version
        )
        p, stdout, stderr = self.local(
            [self.git, "show", f"{version}:{SETUPTOOLS}"], raise_on_error=False
        )
        if p.returncode or any("invalid object name" in line for line in stderr):
            requirements = (
                File(self.directory / SETUPTOOLS).read_json().install_requires
            )
        else:
            requirements = json2value("\n".join(stdout)).install_requires

        def deps():
            for r in requirements:
                if ">=" in r:
                    n, v = r.split(">=")
                    yield {"name": n, "version": Version(v)}
                elif "==" in r:
                    n, v = r.split("==")
                    yield {"name": n, "version": Version(v)}
                elif ">" in r:
                    n, v = r.split(">")
                    v = Version(v)
                    v = min(vv for vv in self.graph.modules[n].all_versions if vv > v)
                    yield {"name": n, "version": v}
                elif "<" in r:
                    Log.error("do not know how to handle")
                else:
                    yield {"name": r, "version": None}

        return list(deps())

    def master_revision(self):
        p, stdout, stderr = self.local([self.git, "log", self.master_branch, "-1"])
        for line in stdout:
            if line.startswith("commit "):
                revision = line.split("commit")[1].strip()
                return revision

    def current_revision(self):
        p, stdout, stderr = self.local([self.git, "log", "-1"])
        for line in stdout:
            if line.startswith("commit "):
                revision = line.split("commit")[1].strip()
                return revision

    @cache()
    def please_upgrade(self):
        ignored_files = ["setup.py", "setuptools.json"]

        # get current version, hash
        version, revision = self.get_version()
        self.svn_update()
        self.update_dev("updates from other projects")
        # COMPARE TO MASTER
        branch_name = randoms.string(10)
        self.local([self.git, "checkout", "-b", branch_name, self.master_branch])
        try:
            self.local([self.git, "merge", self.dev_branch])
            p, stdout, stderr = self.local([
                self.git,
                "--no-pager",
                "diff",
                "--name-only",
                "master",
            ])
            if any(l.strip() for l in stdout if l not in ignored_files):
                Log.note("{{num}} files changed", num=len(stdout))
                curr_revision = self.current_revision()
            else:
                curr_revision = revision
            self.local([self.git, "checkout", "-f", self.dev_branch])
        except Exception as e:
            Log.warning("problem determining upgrade status", cause=e)
            self.local([self.git, "reset", "--hard", "HEAD"])
            self.local([self.git, "checkout", "-f", self.dev_branch])
            curr_revision = self.current_revision()
        finally:
            self.local([self.git, "branch", "-D", branch_name])

        return curr_revision != revision

    def __str__(self):
        return self.name


def value2python(value):
    if value in (True, False, None):
        return text(repr(value))
    elif is_text(value):
        return text(repr(value))
    elif is_binary(value):
        return text(repr(value))
    else:
        return value2json(value)
