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
from mo_json import json2value
from mo_kwargs import override
from mo_logs import constants, strings
from mo_logs import startup, Log
from mo_times import Date
from mo_times.dates import unicode2Date

from mo_threads import Process


class Deploy(object):
    @override
    def __init__(self, directory, git, kwargs=None):
        self.directory = directory
        self.git = git

    def deploy(self):

        self.svn_update()
        self.setup()
        self.pypi()
        self.update_master()

    def last_deploy(self):
        setup_file = File.new_instance(self.directory, 'setup.py')
        if not setup_file.exists:
            Log.note("Not a pypi project: {{dir}}", dir=self.directory)
            return Date.today()
        setup = setup_file.read()
        version = json2value(strings.between(setup, "version=", ",")).split(".")[-1]
        date = unicode2Date(version, format="%y%j")
        Log.note("PyPi last deployed {{date|datetime}}", date=date, dir=self.directory)
        return date

    def setup(self):
        result = self.local("git", [self.git, "checkout", "dev"])
        result = self.local("git", [self.git, "merge", "master"])
        result = self.local("git", [self.git, "push", "origin", "dev"])

    def pypi(self):
        if Date.today() <= self.last_deploy():
            Log.note("Can not upload to pypi")
            return

        lib_name = self.directory.name
        source_readme = File.new_instance(self.directory, 'README.md').abspath
        dest_readme = File.new_instance(self.directory, 'README.txt').abspath
        pypandoc.convert(source_readme, to=b'rst', outputfile=dest_readme)
        setup_file = File.new_instance(self.directory, 'setup.py')

        setup = setup_file.read()
        curr = (datetime.datetime.utcnow() + datetime.timedelta(days=1)).strftime("%y%j")
        setup = re.sub(r'(version\s*=\s*\"\d*\.\d*\.)\d*(\")', r'\g<1>%s\2' % curr, setup)
        setup_file.write(setup)

        File.new_instance(self.directory, "build").delete()
        File.new_instance(self.directory, "dist").delete()
        File.new_instance(self.directory, lib_name.replace("-", "_") + ".egg-info").delete()

        process, stdout, stderr = self.local("pypi", ["C:/Python27/python.exe", "setup.py", "bdist_egg", "upload"], raise_on_error=False)
        if "Upload failed (400): File already exists." in stderr:
            Log.warning("Not uploaded")
        elif process.returncode==0:
            pass
        else:
            Log.error("not expected")
        process, stdout, stderr = self.local("pypi", ["C:/Python27/python.exe", "setup.py", "sdist", "upload"], raise_on_error=False)
        if "Upload failed (400): File already exists." in stderr:
            Log.warning("Not uploaded")
        elif process.returncode==0:
            pass
        else:
            Log.error("not expected")

        File.new_instance(self.directory, "README.txt").delete()
        File.new_instance(self.directory, "build").delete()
        File.new_instance(self.directory, "dist").delete()
        File.new_instance(self.directory, lib_name.replace("-", "_") + ".egg-info").delete()

    def svn_update(self):
        source = File.new_instance(self.directory, self.directory.name.replace("-", "_")).abspath
        tests = File.new_instance(self.directory, "tests").abspath

        result = self.local("git", [self.git, "checkout", "dev"])
        if File.new_instance(source, ".svn").exists:
            result = self.local("svn", ["C:/Program Files/TortoiseSVN/bin/svn.exe", "update", "--accept", "p", source])
            result = self.local("svn", ["C:/Program Files/TortoiseSVN/bin/svn.exe", "commit", source, "-m", "auto"])
            result = self.local("svn", ["C:/Program Files/TortoiseSVN/bin/svn.exe", "update", "--accept", "p", tests])
            result = self.local("svn", ["C:/Program Files/TortoiseSVN/bin/svn.exe", "commit", tests, "-m", "auto"])
        result = self.local("git", [self.git, "add", "-A"])
        process, stdout, stderr = self.local("git", [self.git, "commit", "-m", "updates from other projects"], raise_on_error=False)
        if "nothing to commit, working directory clean" in stdout or process.returncode==0:
            pass
        else:
            Log.error("not expected {{result}}", result=result)
        result = self.local("git", [self.git, "push", "origin", "dev"])

    def update_master(self):
        result = self.local("git", [self.git, "checkout", "master"])
        result = self.local("git", [self.git, "merge", "--no-ff", "dev"])
        result = self.local("git", [self.git, "push", "origin", "master"])
        result = self.local("git", [self.git, "checkout", "dev"])

    def local(self, cmd, args, raise_on_error=True):
        p = Process(cmd, args, cwd=self.directory).join(raise_on_error=raise_on_error)
        return p, list(p.stdout), list(p.stderr)

def deploy_all(parent_dir, prefix, config):
    for c in parent_dir.children:
        if c.name.lower().startswith(prefix):
            Log.alert("Process {{dir}}", dir=c.abspath)
            Deploy(c, kwargs=config).deploy()


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
                "required": True
            }
        ])
        constants.set(settings.constants)
        Log.start(settings.debug)

        if settings.args.all:
            deploy_all(File(settings.args.directory), settings.prefix, settings)
        else:
            Deploy(File(settings.args.directory), kwargs=settings).deploy()
    except Exception, e:
        Log.warning("Problem with etl", cause=e)
    finally:
        Log.stop()


if __name__ == "__main__":
    main()
