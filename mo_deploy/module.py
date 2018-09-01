# encoding: utf-8
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this file,
# You can obtain one at http://mozilla.org/MPL/2.0/.
#
# Author: Kyle Lahnakoski (kyle@lahnakoski.com)
#
from __future__ import division
from __future__ import unicode_literals

from collections import Mapping

import mo_json_config
from mo_deploy.utils import parse_req, Version
from mo_dots import coalesce, wrap
from mo_files import File
from mo_future import text_type, sort_using_key
from mo_json import value2json
from mo_logs import Log, Except
from mo_logs.strings import quote
from mo_math.randoms import Random
from mo_threads import Process
from mo_times import SECOND
from pyLibrary.env import http
from pyLibrary.meta import cache


SETUPTOOLS = 'setuptools.json'

class Module(object):
    # FULL PATH TO EXECUTABLES
    git = "git"
    svn = "svn"
    pip = "pip"
    twine = "twine"
    python = "C:/Python27/python.exe"

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
            self.update_setup_file(self.graph.next_version)
            self.update_dev("update version number")
            self.update_master_locally(self.graph.next_version)
            self.pypi()
            self.local("git", [self.git, "push", "origin", self.master_branch])
        except Exception as e:
            e = Except.wrap(e)
            self.local("git", [self.git, "checkout", master_rev])
            self.local("git", [self.git, "tag", "--delete", "v" + text_type(self.graph.next_version)], raise_on_error=False)
            self.local("git", [self.git, "branch", "-D", self.master_branch], raise_on_error=False)
            self.local("git", [self.git, "checkout", "-b", self.master_branch])
            Log.error("Can not deploy", cause=e)
        finally:
            self.local("git", [self.git, "checkout", self.dev_branch])

    def setup(self):
        self.local("git", [self.git, "checkout", self.dev_branch])
        self.local("git", [self.git, "merge", self.master_branch])

    @cache(duration=10*SECOND)
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
        (self.directory / (self.directory.name.replace("-", "_") + ".egg-info")).delete()

    def pypi(self):
        setup_file = self.directory / 'setup.py'

        Log.note("Update PyPi for {{dir}}", dir=self.directory.abspath)
        try:
            self.scrub_pypi_residue()

            Log.note("write setup.py")
            setup = mo_json_config.get_file(self.directory / SETUPTOOLS)
            setup_file.write(
                "from setuptools import setup\n" +
                "setup(\n" +
                ",\n".join("    " + k + "=" + value2python(v) for k, v in setup.items()) + "\n" +
                ")"
            )
            Log.note("run setup.py")
            self.local("pypi", [self.python, "setup.py", "sdist"], raise_on_error=True)

            Log.note("twine upload of {{dir}}", dir=self.directory.abspath)
            process, stdout, stderr = self.local("twine", [self.twine, "upload", "dist/*"], raise_on_error=False, show_all=True)
            if "Upload failed (400): File already exists." in stderr:
                Log.error("Version exists. Not uploaded")
            elif "error: <urlopen error [Errno 11001] getaddrinfo failed>" in stderr:
                Log.error("No network. Not uploaded")
            elif process.returncode == 0:
                pass
            elif "error: Upload failed (400): This filename has previously been used, you should use a different version." in stderr:
                Log.error("Exists already in pypi")
            elif "503: Service Unavailable" in stderr:
                Log.error("Some big problem during upload")
            else:
                Log.error("not expected\n{{result}}", result=stdout + stderr)
        finally:
            setup_file.delete()
            self.scrub_pypi_residue()

    def update_setup_file(self, new_version):
        setup_file = self.directory / 'setup.py'
        setup_json = self.directory / SETUPTOOLS
        readme = self.directory / 'README.md'
        req_file = self.directory / 'requirements.txt'

        # CHECK FILES EXISTENCE
        if setup_file.exists:
            Log.error("expecting no setup.py file; it will be created from setup.json")
        if not setup_json.exists:
            Log.error("expecting {{file}} file", file=SETUPTOOLS)
        if not readme.exists:
            Log.error("expecting a README.md file to add to long_description")
        if not req_file.exists:
            Log.error("Expecting a requirements.txt file")

        # LOAD
        setup = mo_json_config.get_file(setup_json)

        # LONG DESCRIPTION
        setup.long_description_content_type='text/markdown'
        setup.long_description = readme.read()

        # PACKAGES
        setup.packages = [
            f.parent.abspath[len(self.directory.abspath)+1:]
            for f in self.directory.leaves
            if f.name == '__init__' and f.extension == 'py'
        ]

        # VERSION
        setup.version = text_type(new_version)

        # REQUIRES
        reqs = self.get_requirements()
        setup.install_requires = [
            r.name + r.type + text_type(r.version) if r.version else r.name
            for r in sort_using_key(reqs, key=lambda rr: rr.name)
        ]

        # WRITE JSON FILE
        setup_json.write(value2json(setup, pretty=True))





    def svn_update(self):
        self.local("git", [self.git, "checkout", self.dev_branch])

        for d in self.directory.find(r"\.svn"):
            svn_dir = d.parent.abspath
            Log.note("Update svn directory {{dir}}", dir=svn_dir)
            self.local("svn", [self.svn, "update", "--accept", "p", svn_dir])
            self.local("svn", [self.svn, "commit", svn_dir, "-m", "auto"])

    def update_dev(self, message):
        Log.note("Update git dev branch for {{dir}}", dir=self.directory.abspath)
        self.scrub_pypi_residue()
        self.local("git", [self.git, "add", "-A"])
        process, stdout, stderr = self.local("git", [self.git, "commit", "-m", message], raise_on_error=False)
        if "nothing to commit, working directory clean" in stdout or process.returncode == 0:
            pass
        else:
            Log.error("not expected {{result}}", result=(stdout, stderr))
        try:
            self.local("git", [self.git, "push", "origin", self.dev_branch])
        except Exception as e:
            Log.warning("git origin dev not updated for {{dir}}", dir=self.directory.name, cause=e)

    def update_master_locally(self, version):
        Log.note("Update git master branch for {{dir}}", dir=self.directory.abspath)
        try:
            self.local("git", [self.git, "checkout", self.master_branch])
            self.local("git", [self.git, "merge", "--no-ff", self.dev_branch])
            self.local("tag", [self.git, "tag", "v" + text_type(version)])
        except Exception as e:
            Log.error("git origin master not updated for {{dir}}", dir=self.directory.name, cause=e)

    def local(self, cmd, args, raise_on_error=True, show_all=False, cwd=None):
        try:
            p = Process(cmd, args, cwd=coalesce(cwd, self.directory)).join(raise_on_error=raise_on_error)
            stdout = list(v.decode('latin1') for v in p.stdout)
            stderr = list(v.decode('latin1') for v in p.stderr)
            if show_all:
                Log.note("stdout = {{stdout}}\nstderr = {{stderr}}", stdout=stdout, stderr=stderr, stack_depth=1)
            p.join()
            return p, stdout, stderr
        except Exception as e:
            Log.error("can not execute {{args}} in dir={{dir|quote}}", args=args, dir=self.directory.abspath, cause=e)

    def get_requirements(self):
        output = wrap([
            {
                "name": req_name,
                "type": type,
                "version": version
            }
            if req_name not in self.graph.graph or not hasattr(self.graph, "next_version") else
            {
                "name": req_name,
                "type": ">=",
                "version": self.graph.get_version(req_name)
            }
            for line in (self.directory / "requirements.txt").read_lines()
            for req_name, type, version in [parse_req(line)]
        ])
        if any("_" in r.name for r in output):
            Log.error("found problem in {{module}}", module=self.name)
        return output

    @cache(duration=10*SECOND)
    def get_version(self):
        # RETURN version, revision PAIR
        p, stdout, stderr = self.local("list tags", ["git", "tag"])
        all_versions = [Version(line.lstrip('v')) for line in stdout]

        if all_versions:
            version = max(all_versions)
            p, stdout, stderr = self.local("get tagged rev", [self.git, "show", "v"+text_type(version)])
            for line in stdout:
                if line.startswith("commit "):
                    revision = line.split("commit")[1].strip()
                    return version, revision

        version = self.last_deploy()
        revision = self.master_revision()
        return version, revision

    def master_revision(self):
        p, stdout, stderr = self.local("get current rev", [self.git, "log", self.master_branch, "-1"])
        for line in stdout:
            if line.startswith("commit "):
                revision = line.split("commit")[1].strip()
                return revision

    def current_revision(self):
        p, stdout, stderr = self.local("get current rev", [self.git, "log", "-1"])
        for line in stdout:
            if line.startswith("commit "):
                revision = line.split("commit")[1].strip()
                return revision

    def can_upgrade(self):
        # get current version, hash
        version, revision = self.get_version()
        self.svn_update()
        self.update_dev("updates from other projects")

        # COMPARE TO MASTER
        branch_name = Random.string(10)
        self.local("git", [self.git, "checkout", "-b", branch_name, self.master_branch])
        try:
            self.local("git", [self.git, "merge", self.dev_branch])
            curr_revision = self.current_revision()
        except Exception:
            self.local("git", [self.git, "reset", "--hard", "HEAD"])
            self.local("git", [self.git, "checkout", self.dev_branch])
            curr_revision = self.current_revision()
        finally:
            self.local("git", [self.git, "checkout", self.dev_branch])
            self.local("git", [self.git, "branch", "-D", branch_name])

        return curr_revision != revision


def value2python(value):
    if value in (True, False, None):
        return text_type(repr(value))
    else:
        return value2json(value)
