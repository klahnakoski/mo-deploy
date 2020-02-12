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

from mo_deploy.utils import Requirement, parse_req
from mo_dots import coalesce, wrap, listwrap
from mo_files import File
from mo_future import is_binary, is_text, sort_using_key, text
from mo_json import value2json
import mo_json_config
from mo_logs import Except, Log
from mo_math.randoms import Random
from mo_threads.multiprocess import Command
from pyLibrary.env import http
from pyLibrary.meta import cache
from pyLibrary.utils import Version

SETUPTOOLS = "setuptools.json"  # CONFIGURATION EXPECTED TO MAKE A setup.py FILE


class Module(object):
    # FULL PATH TO EXECUTABLES
    git = "git"
    svn = "svn"
    pip = "pip"
    twine = "twine"
    python = "python"
    python_requires = ">=2.7"
    ignore_svn = []

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
        self.version = None
        self.graph = graph

    def deploy(self):
        self.setup()
        self.svn_update()
        self.update_dev("updates from other projects")

        curr_version, revision = self.get_version()
        if curr_version == self.graph.next_version:
            Log.error("{{module}} does not need deploy", module=self.name)

        master_rev = self.master_revision()
        try:
            self.update_setup_json_file(self.graph.next_version)
            self.gen_setup_py_file()
            self.local([self.python, "-c", "from " + self.name.replace("-", "_") + " import __deploy__; __deploy__()"], raise_on_error=False)
            self.update_dev("update version number")
            self.update_master_locally(self.graph.next_version)
            self.pypi()
            self.local([self.git, "push", "origin", self.master_branch])
        except Exception as e:
            e = Except.wrap(e)
            self.local([self.git, "checkout", "-f", master_rev])
            self.local(
                [self.git, "tag", "--delete", "v" + text(self.graph.next_version)],
                raise_on_error=False,
            )
            self.local(
                [self.git, "branch", "-D", self.master_branch], raise_on_error=False
            )
            self.local([self.git, "checkout", "-b", self.master_branch])
            Log.error("Can not deploy", cause=e)
        finally:
            self.local([self.git, "checkout", self.dev_branch])

    def setup(self):
        self.local([self.git, "checkout", self.dev_branch])
        self.local([self.git, "merge", self.master_branch])

    def gen_setup_py_file(self):
        setup_file = self.directory / "setup.py"
        Log.note("write setup.py")
        setup = mo_json_config.get_file(self.directory / SETUPTOOLS)
        setup_file.write(
            "# encoding: utf-8\n" + "# THIS FILE IS AUTOGENERATED!\n"
            "from __future__ import unicode_literals\n"
            + "from setuptools import setup\n"
            + "setup(\n"
            + ",\n".join("    " + k + "=" + value2python(v) for k, v in setup.items())
            + "\n"
            + ")"
        )

    @cache()
    def last_deploy(self):
        url = "https://pypi.org/pypi/" + self.name + "/json"
        try:
            return max(Version(k) for k in http.get_json(url).releases.keys())
        except Exception as e:
            Log.warning("could not get version from {{url}}", url=url, cause=e)
            return None

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

        Log.note("Update PyPi for {{dir}}", dir=self.directory.abspath)
        try:
            self.scrub_pypi_residue()

            Log.note("run setup.py")
            self.local([self.python, "setup.py", "sdist"], raise_on_error=True)

            Log.note("twine upload of {{dir}}", dir=self.directory.abspath)
            # python3 -m twine upload --repository-url https://test.pypi.org/legacy/ dist/*
            process, stdout, stderr = self.local(
                [self.twine, "upload", "dist/*"], raise_on_error=False, show_all=True
            )
            if "Upload failed (400): File already exists." in stderr:
                Log.error("Version exists. Not uploaded")
            elif "error: <urlopen error [Errno 11001] getaddrinfo failed>" in stderr:
                Log.error("No network. Not uploaded")
            elif process.returncode == 0:
                pass
            elif (
                "error: Upload failed (400): This filename has previously been used, you should use a different version."
                in stderr
            ):
                Log.error("Exists already in pypi")
            elif "503: Service Unavailable" in stderr:
                Log.error("Some big problem during upload")
            else:
                Log.error("not expected\n{{result}}", result=stdout + stderr)
        finally:
            self.scrub_pypi_residue()

    def update_setup_json_file(self, new_version):
        setup_json = self.directory / SETUPTOOLS
        readme = self.directory / "README.md"
        req_file = self.directory / "requirements.txt"

        # CHECK FILES EXISTENCE
        # if setup_file.exists:
        #     Log.error("expecting no setup.py file; it will be created from {{tools}}", tools=SETUPTOOLS)
        if not setup_json.exists:
            Log.error("expecting {{file}} file", file=setup_json)
        if not readme.exists:
            Log.error("expecting a README.md file to add to long_description")
        if not req_file.exists:
            Log.error("Expecting a requirements.txt file")

        # LOAD
        setup = mo_json_config.get_file(setup_json)

        setup.python_requires = Module.python_requires
        if not any(c.startswith("Programming Language :: Python") for c in listwrap(setup.classifiers)):
            Log.warning("expecting language classifier, like 'Programming Language :: Python :: 3.7'")

        # LONG DESCRIPTION
        setup.long_description_content_type = "text/markdown"
        setup.long_description = readme.read()

        # PACKAGES
        packages = [
            dir_name
            for f in self.directory.leaves
            if f.name == "__init__" and f.extension == "py"
            for dir_name in [f.parent.abspath[len(self.directory.abspath) + 1 :]]
            if dir_name and not dir_name.startswith("tests/") and dir_name != "tests"
        ]
        if setup.packages == None:
            setup.packages = packages
        elif set(setup.packages) != set(packages):
            Log.warning(
                "Packages are {{existing}}. Maybe they should be {{proposed}}",
                existing=setup.packages,
                proposed=packages,
            )

        # VERSION
        setup.version = text(new_version)

        # REQUIRES
        reqs = self.get_requirements(
            [parse_req(line) for line in setup.install_requires]
        )
        setup.install_requires = [
            r.name + r.type + text(r.version) if r.version else r.name
            for r in sort_using_key(reqs, key=lambda rr: rr.name)
        ]

        # WRITE JSON FILE
        setup_json.write(value2json(setup, pretty=True))

    def svn_update(self):
        self.local([self.git, "checkout", self.dev_branch])

        for d in self.directory.find(r"\.svn"):
            svn_dir = d.parent.abspath
            if any(d in svn_dir for d in listwrap(Module.ignore_svn)):
                Log.note("Ignoring svn directory {{dir}}", dir=svn_dir)
                continue

            Log.note("Update svn directory {{dir}}", dir=svn_dir)
            self.local([self.svn, "update", "--accept", "p", svn_dir])
            self.local([self.svn, "commit", svn_dir, "-m", "auto"])

    def update_dev(self, message):
        Log.note("Update git dev branch for {{dir}}", dir=self.directory.abspath)
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
        Log.note("Update git master branch for {{dir}}", dir=self.directory.abspath)
        try:
            v = "v" + text(version)
            self.local([self.git, "checkout", self.master_branch])
            self.local([self.git, "merge", "--no-ff", "--no-commit", self.dev_branch])
            self.local([self.git, "commit", "-m", "release " + v])
            self.local([self.git, "tag", v])
            self.local([self.git, "push", "origin", v])
        except Exception as e:
            Log.error(
                "git origin master not updated for {{dir}}",
                dir=self.directory.name,
                cause=e,
            )

    def local(self, args, raise_on_error=True, show_all=False, cwd=None):
        try:
            p = Command(self.name, args, cwd=coalesce(cwd, self.directory)).join(
                raise_on_error=raise_on_error
            )
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
                dir=self.directory.abspath,
                cause=e,
            )

    def get_requirements(self, current_requires):
        # MAP FROM NAME TO CURRENT LIMITS
        lookup_old_requires = {r.name: r for r in current_requires}

        req = self.directory / "requirements.txt"
        output = wrap([  # TODO: improve this, keep version numbers from json file so that they only increase
            r & lookup_old_requires.get(r.name)
            if r.name not in self.graph.graph or not hasattr(self.graph, "next_version")
            else Requirement(
                name=r.name,
                type=">=",
                version=self.graph.get_version(r.name),  # ALREADY THE MAX
            )
            for line in req.read_lines()
            if line
            for r in [parse_req(line)]
        ])

        if any("_" in r.name for r in output):
            Log.error("found problem in {{module}}", module=self.name)
        return output

    @cache()
    def get_version(self):
        # RETURN version, revision PAIR
        p, stdout, stderr = self.local([self.git, "tag"])
        all_versions = [Version(line.lstrip("v")) for line in stdout]

        if all_versions:
            version = max(all_versions)
            p, stdout, stderr = self.local([self.git, "show", "v" + text(version)])
            for line in stdout:
                if line.startswith("commit "):
                    revision = line.split("commit")[1].strip()
                    return version, revision

        version = self.last_deploy()
        revision = self.master_revision()
        return version, revision

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
    def can_upgrade(self):
        ignored_files = ["setup.py"]

        # get current version, hash
        version, revision = self.get_version()
        self.svn_update()
        self.update_dev("updates from other projects")
        # COMPARE TO MASTER
        branch_name = Random.string(10)
        self.local([self.git, "checkout", "-b", branch_name, self.master_branch])
        try:
            self.local([self.git, "merge", self.dev_branch])
            p, stdout, stderr = self.local(
                [self.git, "--no-pager", "diff", "--name-only", "master"]
            )
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


def value2python(value):
    if value in (True, False, None):
        return text(repr(value))
    elif is_text(value):
        return text(repr(value))
    elif is_binary(value):
        return text(repr(value))
    else:
        return value2json(value)
