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

import datetime
import re

import pypandoc
from mo_files import File
from mo_json import json2value, value2json
from mo_kwargs import override
from mo_logs import constants, strings
from mo_logs import startup, Log
from mo_threads import Process
from mo_times import Date
from mo_times.dates import unicode2Date


class Deploy(object):
    @override
    def __init__(self, directory, git, svn, kwargs=None):
        self.directory = directory
        self.git = git
        self.svn = svn

    def deploy(self):
        self.setup()
        self.svn_update()
        self.update_dev("updates from other projects")
        success = self.pypi()
        if success:
            self.update_dev("update version number")
            self.update_master()
        return success

    def setup(self):
        result = self.local("git", [self.git, "checkout", "dev"])
        result = self.local("git", [self.git, "merge", "master"])

    def last_deploy(self):
        try:
            self.local("pip", ["pip", "uninstall", "-y", self.directory.name], raise_on_error=False, show_all=True)
            self.local("pip", ["pip", "install", "--no-cache-dir", self.directory.name], show_all=True)
            process, stdout, stderr = self.local("pip", ["pip", "show", self.directory.name], show_all=True)
            for line in stdout:
                if line.startswith("Version:"):
                    version = line.split(":")[1].split(".")[-1]
                    date = unicode2Date(version, format="%y%j")
                    Log.note("PyPi last deployed {{date|datetime}}", date=date, dir=self.directory)
                    return date
            return None
        except Exception, e:
            Log.warning("could not get version", cause=e)
            return None

    def pypi(self):
        Log.note("Update PyPi for {{dir}}", dir=self.directory.abspath)
        lib_name = self.directory.name
        source_readme = File.new_instance(self.directory, 'README.md').abspath
        dest_readme = File.new_instance(self.directory, 'README.txt').abspath
        pypandoc.convert(source_readme, to=b'rst', outputfile=dest_readme)
        setup_file = File.new_instance(self.directory, 'setup.py')
        req_file = File.new_instance(self.directory, 'requirements.txt')

        if not setup_file.exists:
            Log.warning("Not a PyPi project!  No setup.py file.")

        setup = setup_file.read()
        # UPDATE THE VERSION NUMBER
        curr = datetime.datetime.utcnow().strftime("%y%j")
        setup = re.sub(r'(version\s*=\s*\"\d*\.\d*\.)\d*(\")', r'\g<1>%s\2' % curr, setup)

        # UPDATE THE REQUIREMENTS
        if not req_file.exists:
            Log.error("Expecting a requirements.txt file")
        req = req_file.read()
        setup_req = re.findall(r'install_requires\s*=\s*\[.*\]\s*,', setup)
        reqs = value2json(d for d in sorted(map(strings.trim, req.split("\n"))) if d)
        setup = setup.replace(setup_req[0], 'install_requires='+reqs+",")

        if Date.today() <= self.last_deploy():
            Log.note("Can not upload to pypi")
            return False

        setup_file.write(setup)
        File.new_instance(self.directory, "build").delete()
        File.new_instance(self.directory, "dist").delete()
        File.new_instance(self.directory, lib_name.replace("-", "_") + ".egg-info").delete()

        Log.note("PyPi Upload for {{dir}}", dir=self.directory.abspath)
        # process, stdout, stderr = self.local("pypi", ["C:/Python27/python.exe", "setup.py", "bdist_egg", "upload"], raise_on_error=False)
        # if "Upload failed (400): File already exists." in stderr:
        #     Log.warning("Version exists. Not uploaded")
        # elif "error: <urlopen error [Errno 11001] getaddrinfo failed>" in stderr:
        #     Log.warning("No network. Not uploaded")
        # elif process.returncode == 0:
        #     pass
        # else:
        #     Log.error("not expected")
        process, stdout, stderr = self.local("pypi", ["C:/Python27/python.exe", "setup.py", "sdist", "upload", "-r", "pypi"], raise_on_error=False)
        if "Upload failed (400): File already exists." in stderr:
            Log.warning("Version exists. Not uploaded")
        elif "error: <urlopen error [Errno 11001] getaddrinfo failed>" in stderr:
            Log.warning("No network. Not uploaded")
        elif process.returncode == 0:
            pass
        elif "error: Upload failed (400): This filename has previously been used, you should use a different version." in stderr:
            Log.warning("Exists already in pypi")
        else:
            Log.error("not expected")

        File.new_instance(self.directory, "README.txt").delete()
        File.new_instance(self.directory, "build").delete()
        File.new_instance(self.directory, "dist").delete()
        File.new_instance(self.directory, lib_name.replace("-", "_") + ".egg-info").delete()
        return True

    def svn_update(self):
        result = self.local("git", [self.git, "checkout", "dev"])
        for d in self.directory.find(r"\.svn"):
            svn_dir = d.parent.abspath
            Log.note("Update svn directory {{dir}}", dir=svn_dir)
            result = self.local("svn", [self.svn, "update", "--accept", "p", svn_dir])
            result = self.local("svn", [self.svn, "commit", svn_dir, "-m", "auto"])

    def update_dev(self, message):
        Log.note("Update git dev branch for {{dir}}", dir=self.directory.abspath)
        result = self.local("git", [self.git, "add", "-A"])
        process, stdout, stderr = self.local("git", [self.git, "commit", "-m", message], raise_on_error=False)
        if "nothing to commit, working directory clean" in stdout or process.returncode == 0:
            pass
        else:
            Log.error("not expected {{result}}", result=result)
        try:
            self.local("git", [self.git, "push", "origin", "dev"])
        except Exception, e:
            Log.warning("git origin dev not updated for {{dir}}", dir=self.directory.name, cause=e)

    def update_master(self):
        Log.note("Update git master branch for {{dir}}", dir=self.directory.abspath)
        try:
            result = self.local("git", [self.git, "checkout", "master"])
            result = self.local("git", [self.git, "merge", "--no-ff", "dev"])
            try:
                result = self.local("git", [self.git, "push", "origin", "master"])
            except Exception, e:
                Log.warning("git origin master not updated for {{dir}}", dir=self.directory.name, cause=e)
        finally:
            result = self.local("git", [self.git, "checkout", "dev"])

    def local(self, cmd, args, raise_on_error=True, show_all=False):
        p = Process(cmd, args, cwd=self.directory).join(raise_on_error=raise_on_error)
        stdout = list(p.stdout)
        stderr = list(p.stderr)
        if show_all:
            Log.note("stdout = {{stdout}}\nstderr = {{stderr}}", stdout=stdout, stderr=stderr)
        return p, stdout, stderr


def deploy_all(config):
    deployed = []
    for m in config.modules:
        Log.alert("Process {{dir}}", dir=m)
        d = Deploy(File(m), kwargs=config)
        d.deploy()
        deployed.append(d)

    for d in deployed:
        Log.note("pip upgrade {{module}}", module=d.directory.name)
        d.local("pip", ["pip", "install", "--upgrade", d.directory.name])
    return deployed


def main():
    try:
        settings = startup.read_settings(defs=[
            {
                "name": ["--all", "-a"],
                "action": 'store_true',
                "help": 'process all mo-* subdirectories',
                "dest": "all",
                "required": False
            },
            {
                "name": ["--dir", "--directory", "-d"],
                "help": 'directory to deploy',
                "type": str,
                "dest": "directory",
                "required": True,
                "default": "."
            }
        ])
        constants.set(settings.constants)
        Log.start(settings.debug)

        if settings.args.all:
            deploy_all(settings)
        else:
            Deploy(File(settings.args.directory), kwargs=settings).deploy()
    except Exception, e:
        Log.warning("Problem with etl", cause=e)
    finally:
        Log.stop()


if __name__ == "__main__":
    main()
