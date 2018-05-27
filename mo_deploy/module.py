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

import re

import pypandoc

from mo_deploy.utils import parse_req, Version
from mo_dots import coalesce, wrap
from mo_files import File
from mo_future import text_type, sort_using_key
from mo_json import value2json
from mo_logs import strings, Log
from mo_logs.strings import quote
from mo_threads import Process
from mo_times.dates import unicode2Date


class Module(object):
    # FULL PATH TO EXECUTABLES
    git = "git"
    svn = "svn"
    pip = "pip"
    twine = "twine"

    def __init__(self, directory, graph):
        self.directory = File(directory)
        self.version = None
        self.graph = graph

    @property
    def name(self):
        return self.directory.name.replace("_", "-")

    def deploy(self):
        self.setup()
        self.svn_update()
        self.update_dev("updates from other projects")
        curr_version, revision = self.get_version()

        if curr_version==self.graph.version:
            Log.error("{{module}} does not need deploy", module=self.name)

        self.update_version(self.graph.version)
        success = self.pypi()
        if success:
            self.update_dev("update version number")
            self.update_master(self.graph.version)
        else:
            # ROLLBACK CHANGES TO setup.py
            self.local("git", ["stash"])
        return success

    def setup(self):
        self.local("git", [self.git, "checkout", "dev"])
        self.local("git", [self.git, "merge", "master"])

    def last_deploy(self):
        try:
            self.local("pip", [self.pip, "uninstall", "-y", self.directory.name], raise_on_error=False, show_all=True)
            self.local("pip", [self.pip, "install", "--no-cache-dir", self.directory.name], cwd=self.directory.parent, show_all=True)
            process, stdout, stderr = self.local("pip", [self.pip, "show", self.directory.name], cwd=self.directory.parent, show_all=True)
            for line in stdout:
                if line.startswith("Version:"):
                    version = Version(line.split(":")[1])
                    date = unicode2Date(version.mini, format="%y%j")
                    Log.note("PyPi last deployed {{date|datetime}}", date=date, dir=self.directory)
                    return version
            return None
        except Exception as e:
            Log.warning("could not get version", cause=e)
            return None

    def pypi(self):
        Log.note("Update PyPi for {{dir}}", dir=self.directory.abspath)
        lib_name = self.directory.name
        source_readme = File.new_instance(self.directory, 'README.md').abspath
        dest_readme = File.new_instance(self.directory, 'README.txt').abspath
        pypandoc.convert(source_readme, to=b'rst', outputfile=dest_readme)

        File.new_instance(self.directory, "build").delete()
        File.new_instance(self.directory, "dist").delete()
        File.new_instance(self.directory, lib_name.replace("-", "_") + ".egg-info").delete()

        Log.note("setup.py Preperation for {{dir}}", dir=self.directory.abspath)
        self.local("pypi", ["C:/Python27/python.exe", "setup.py", "sdist"], raise_on_error=False)
        Log.note("twine upload of {{dir}}", dir=self.directory.abspath)
        process, stdout, stderr = self.local("twine", [self.twine, "upload", "dist/*"], raise_on_error=False, show_all=True)
        if "Upload failed (400): File already exists." in stderr:
            Log.warning("Version exists. Not uploaded")
        elif "error: <urlopen error [Errno 11001] getaddrinfo failed>" in stderr:
            Log.warning("No network. Not uploaded")
        elif process.returncode == 0:
            pass
        elif "error: Upload failed (400): This filename has previously been used, you should use a different version." in stderr:
            Log.warning("Exists already in pypi")
        elif "503: Service Unavailable" in stderr:
            Log.warning("Some big problem during upload")
        else:
            Log.error("not expected\n{{result}}", result=stdout + stderr)

        File.new_instance(self.directory, "README.txt").delete()
        File.new_instance(self.directory, "build").delete()
        File.new_instance(self.directory, "dist").delete()
        File.new_instance(self.directory, lib_name.replace("-", "_") + ".egg-info").delete()
        return True

    def update_version(self, new_version):
        setup_file = File.new_instance(self.directory, 'setup.py')
        req_file = File.new_instance(self.directory, 'requirements.txt')
        if not setup_file.exists:
            Log.warning("Not a PyPi project! No setup.py file.")
        setup = setup_file.read().replace("\r", "")
        # UPDATE THE VERSION NUMBER
        old_version = strings.between(setup, "version=", ",")
        if not old_version:
            Log.error("could not find version number")
        self.version = new_version

        setup = setup.replace("version=" + old_version, "version=" + quote(text_type(self.version)))
        # UPDATE THE REQUIREMENTS
        if not req_file.exists:
            Log.error("Expecting a requirements.txt file")
        old_requires = re.findall(r'install_requires\s*=\s*\[.*\]\s*,', setup)
        reqs = self.get_requirements()
        new_requires = value2json([
            r.name + r.type + r.version if r.version else r.name
            for r in sort_using_key(reqs, key=lambda rr: rr.name)
        ])
        setup = setup.replace(old_requires[0], 'install_requires=' + new_requires + ",")
        setup_file.write(setup)

    def svn_update(self):
        self.local("git", [self.git, "checkout", "dev"])

        for d in self.directory.find(r"\.svn"):
            svn_dir = d.parent.abspath
            Log.note("Update svn directory {{dir}}", dir=svn_dir)
            self.local("svn", [self.svn, "update", "--accept", "p", svn_dir])
            self.local("svn", [self.svn, "commit", svn_dir, "-m", "auto"])

    def update_dev(self, message):
        Log.note("Update git dev branch for {{dir}}", dir=self.directory.abspath)
        self.local("git", [self.git, "add", "-A"])
        process, stdout, stderr = self.local("git", [self.git, "commit", "-m", message], raise_on_error=False)
        if "nothing to commit, working directory clean" in stdout or process.returncode == 0:
            pass
        else:
            Log.error("not expected {{result}}", result=(stdout, stderr))
        try:
            self.local("git", [self.git, "push", "origin", "dev"])
        except Exception as e:
            Log.warning("git origin dev not updated for {{dir}}", dir=self.directory.name, cause=e)

    def update_master(self, version):
        Log.note("Update git master branch for {{dir}}", dir=self.directory.abspath)
        try:
            self.local("git", [self.git, "checkout", "master"])
            self.local("git", [self.git, "merge", "--no-ff", "dev"])
            self.local("tag", [self.git, "tag", "v" + text_type(version)])

            try:
                self.local("git", [self.git, "push", "origin", "master"])
            except Exception as e:
                Log.warning("git origin master not updated for {{dir}}", dir=self.directory.name, cause=e)
        finally:
            self.local("git", [self.git, "checkout", "dev"])

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
            for line in (self.directory / "requirements.txt").read_lines()
            for req_name, type, version in [parse_req(line)]
        ])
        if any("_" in r.name for r in output):
            Log.error("found problem in {{module}}", module=self.name)
        return output

    def get_version(self):
        # RETURN version, revision PAIR
        p, stdout, stderr = self.local("list tags", ["git", "tag"])
        all_versions = [Version(line.ltrim('v')) for line in stdout]

        if all_versions:
            version = max(all_versions)
            p, stdout, stderr = self.local("get tagged rev", [self.git, "show", "v"+text_type(version)])
            for line in stdout:
                if line.startswith("commit "):
                    revision = line.split("commit")[1].strip()
                    return version, revision
        return None, None

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
        curr_revision = self.current_revision()

        return curr_revision != revision
