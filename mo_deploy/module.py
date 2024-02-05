# encoding: utf-8
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this file,
# You can obtain one at http://mozilla.org/MPL/2.0/.
#
# Author: Kyle Lahnakoski (kyle@lahnakoski.com)
#
from mo_future import Mapping

import yaml

from mo_deploy.utils import Requirement, parse_req
from mo_dots import coalesce, listwrap, to_data, exists, from_data
from mo_dots.lists import last
from mo_files import File, TempDirectory, URL
from mo_future import is_binary, is_text, sort_using_key, text, first
from mo_http import http
from mo_json import value2json, json2value
from mo_logs import Except, logger, strings
from mo_math import randoms
from mo_threads import Thread, Till, Lock, lock
from mo_threads.commands import Command
from mo_times import Timer, Date
from mo_times.dates import ISO8601
from pyLibrary.meta import cache
from pyLibrary.utils import Version

NO_VERSION = Version((-1,))
FIRST_VERSION = Version("0.0.0")
SETUPTOOLS = "packaging/setuptools.json"  # CONFIGURATION USED TO MAKE THE setup.py FILE
SVN_BRANCH = "svn"
TEMP_BRANCH_PREFIX = "temp-"


class Module(object):
    # FULL PATH TO EXECUTABLES
    git = "git"
    svn = "svn"
    twine = "twine"
    python = {"3.11": "c:/python311/python.exe"}
    ignore_svn = []
    test_versions = []

    def __init__(self, info, graph):
        if isinstance(info, Mapping):
            self.master_branch = coalesce(info.deploy_branch, "master")
            self.dev_branch = coalesce(info.dev_branch, "dev")
            self.svn_branch = info.svn_branch
            self.directory = File(info.location)
            self.package_name = coalesce(info.package_name, self.directory.stem.replace("_", "-"))
            self.name = coalesce(info.name, self.directory.stem.replace("_", "-"))
        else:
            self.master_branch = "master"
            self.dev_branch = "dev"
            self.svn_branch = SVN_BRANCH
            self.directory = File(info)
            self.name = self.directory.stem.replace("_", "-")
            self.package_name = self.name
        self.graph = graph
        self.all_versions = []
        # setattr(lock, "print", lambda x: logger.info(x, static_template=False, stack_depth=1))
        self.install_locker = Lock("only one pip installer at a time")

    def deploy(self):
        self.setup()
        self.svn_update()
        self.update_dev("updates from other projects")

        curr_version, revision = self.get_version()
        next_version = self.graph.get_next_version(self.name)
        if curr_version == next_version:
            logger.error("{{module}} does not need deploy", module=self.name)

        master_rev = self.master_revision()
        try:
            self.update_setup_json_file(next_version)
            self.synch_travis_file()
            self.gen_setup_py_file()
            # TOO SOON TO RUN THIS, MUST HAVE THE DEPENDENCIES INSTALLED FIRST
            # logger.info("if you are stalled here, it is because import __deploy__ may have imported mo_threads and now has an active thread that has not been told to shutdown")
            # self.local(
            #     [
            #         self.python["latest"],
            #         "-c",
            #         "from " + self.package_name.replace("-", "_") + " import __deploy__; __deploy__()",
            #     ],
            #     raise_on_error=False,
            # )
            self.update_dev("update version number")

            # RUN TESTS IN PARALLEL
            while True:
                try:
                    test_threads = [Thread.run("test " + v, self.run_tests, v) for v in self.test_versions]
                    Thread.join_all(test_threads)
                    # for v in self.test_versions:
                    #     self.run_tests(v, None)
                    break
                except Exception as cause:
                    logger.warning("Tests did not pass", cause=cause)
                    value = input("Did not pass tests.  Try again? (y/N): ")
                    if value not in "yY":
                        logger.error("Can not install self", cause=cause)
            self.update_dev("update lockfile")  # ONE OF THE TEST THREADS UPDATED THE REQUIREMENTS FILE
            self.update_master_locally(next_version)
            self.pypi()
            self.local([self.git, "push", "origin", self.master_branch])
        except Exception as cause:
            cause = Except.wrap(cause)
            self.local([self.git, "checkout", "-f", master_rev])
            self.local(
                [self.git, "tag", "--delete", text(next_version)], raise_on_error=False,
            )
            self.local([self.git, "branch", "-D", self.master_branch], raise_on_error=False)
            self.local([self.git, "checkout", "-b", self.master_branch])
            logger.error("Can not deploy {{module}}", module=self.name, cause=cause)
        finally:
            self.local([self.git, "checkout", self.dev_branch])

    def setup(self):
        self.local([self.git, "checkout", self.dev_branch])
        self.local([self.git, "merge", self.master_branch])

    def synch_travis_file(self):
        travis_file = self.directory / ".travis.yml"
        if travis_file.exists:
            logger.info("synch .travis.yml file")

            setup = (self.directory / SETUPTOOLS).read_json(leaves=False)
            tested_versions = [
                c.split("::")[-1].strip()
                for c in setup.classifiers
                if c.startswith("Programming Language :: Python :: ")
            ]
            content = to_data(yaml.safe_load(travis_file.read()))
            python = content.python = []
            content.jobs.include = []
            for v in tested_versions:
                if v in ("3.8", "3.9"):
                    python += [str(v)]
                elif v == "3.10":
                    content.jobs.include += [{
                        "name": "Python 3.10",
                        "dist": "jammy",  # Ubuntu 22.04
                        "python": "3.10",
                        "before_install": [
                            # https://discourse.charmhub.io/t/cannot-install-dependencies-modulenotfounderror-no-module-named-setuptools-command-build/7374
                            "pip install wheel==0.37.1",
                            "pip install setuptools==45.2.0",
                        ],
                    }]
                elif v == "3.11":
                    content.jobs.include += [{
                        "name": "Python 3.11",
                        "dist": "jammy",  # Ubuntu 22.04
                        "python": "3.11",
                        "before_install": [
                            "pip install --upgrade pip",
                            "pip install wheel==0.41.2",
                            "pip install setuptools==65.5.0",
                        ],
                    }]
                elif v == "3.12":
                    content.jobs.include += [{
                        "name": "Python 3.12",
                        "dist": "jammy",  # Ubuntu 22.04
                        "python": "3.12",
                        "before_install": [
                            "pip install --upgrade pip",
                            "pip install wheel==0.42.0",
                            "pip install setuptools==69.0.3",
                        ],
                    }]
                else:
                    logger.error("Unhandled version {{version}}", version=v)

            travis_file.write(yaml.dump(from_data(content), default_flow_style=False, sort_keys=False))

    def gen_setup_py_file(self):
        logger.info("write setup.py")
        setup = (self.directory / SETUPTOOLS).read_json(leaves=False)
        content = (
            "# encoding: utf-8\n"
            + "# THIS FILE IS AUTOGENERATED!\n"
            + "from setuptools import setup\n"
            + "setup(\n"
            + ",\n".join("    " + k + "=" + value2python(v) for k, v in setup.items() if v != None)
            + "\n"
            + ")"
        )
        (self.directory / "packaging" / "setup.py").write(content)
        (self.directory / "setup.py").write(content)

    @cache()
    def last_deploy(self):
        url = URL("https://pypi.org/pypi") / self.package_name / "json"
        try:
            result = http.get_json(url)
            version = max(
                v
                for k in result.releases.keys()
                for v in [Version(k, prefix="v")]
                if v.major == self.get_major_version()
            )
            logger.info("last deployed version is {{version}}", version=version)
            return version
        except Exception as e:
            logger.warning("Is this new? Could not get version from {{url}}", url=url, cause=e)
            return NO_VERSION

    def scrub_pypi_residue(self):
        with Timer("cleanup pypi residue", verbose=True):
            with self.install_locker:
                (self.directory / "setup.py").delete()
                (self.directory / "README.txt").delete()
                (self.directory / "build").delete()
                (self.directory / "dist").delete()
                (self.directory / (self.directory.stem.replace("-", "_") + ".egg-info")).delete()

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

        logger.info("Update PyPi for {{dir}}", dir=self.directory.abs_path)
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

            logger.info("run build command")
            self.gen_setup_py_file()

            # self.local([self.python["latest"], "setup.py", "bdist_wheel", "--universal"], raise_on_error=True)
            self.local([self.python["latest"], "-m", "build", "--wheel", "--sdist"], raise_on_error=True)

            logger.info("twine upload of {{dir}}", dir=self.directory.abs_path)
            # python3 -m twine upload --repository-url https://test.pypi.org/legacy/ dist/*
            process, stdout, stderr = self.local(
                [self.twine, "upload", "--verbose", "dist/*"], raise_on_error=False, show_all=True,
            )
            if "Upload failed (400): File already exists." in stderr:
                logger.error("Version exists. Not uploaded")
            elif "error: <urlopen error [Errno 11001] getaddrinfo failed>" in stderr:
                logger.error("No network. Not uploaded")
            elif process.returncode == 0:
                pass
            elif (
                "error: Upload failed (400): This filename has previously been used,"
                " you should use a different version."
                in stderr
            ):
                logger.error("Exists already in pypi")
            elif "503: Service Unavailable" in stderr:
                logger.error("Some big problem during upload")
            else:
                logger.error("not expected\n{{result}}", result=stdout + stderr)
        finally:
            self.scrub_pypi_residue()

        give_up_on_pypi = Till(seconds=90)
        while not give_up_on_pypi:
            logger.info(
                "WAIT FOR PYPI TO SHOW NEW VERSION {{module}}=={{version}}",
                module=self.package_name,
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
                [self.python["latest"], "-m", "pip", "install", self.package_name + "=="], raise_on_error=False,
            )
            if any(str(self.graph.get_next_version(self.name)) in e for e in stderr):
                logger.info("Found on pypi")
                break

    def update_setup_json_file(self, new_version):
        setup_json = self.directory / SETUPTOOLS
        readme = self.directory / "README.md"
        req_file = self.directory / "packaging" / "requirements.txt"
        test_req_file = self.directory / "tests" / "requirements.txt"

        # CHECK FILES EXISTENCE
        # if setup_file.exists:
        #     logger.error("expecting no setup.py file; it will be created from {{tools}}", tools=SETUPTOOLS)
        if not setup_json.exists:
            logger.error("expecting {{file}} file", file=setup_json)
        if not readme.exists:
            logger.error("expecting a README.md file to add to long_description")
        if not req_file.exists:
            logger.error("Expecting a requirements.txt file")

        setup = setup_json.read_json(leaves=False)

        # FIND VERSIONS FOR TESTING
        self.test_versions = []
        for c in listwrap(setup.classifiers):
            if c.startswith("Programming Language :: Python ::"):
                version = c.split("::")[-1].strip()
                if not self.python.get(version):
                    setup.classifiers.remove(c)
                    logger.alert("Removing {{classifier}} from {{setup_json}} file", classifier=c, setup_json=setup_json)
                else:
                    self.test_versions.append(version)
        if "3.11" not in self.test_versions:
            # ask user if they want to add 3.11
            value = input("Add 3.11 python to supported versions list? (y/N): ")
            if value in "yY":
                self.test_versions.append("3.11")
                setup.classifiers.append("Programming Language :: Python :: 3.11")
        if "3.12" not in self.test_versions:
            # ask user if they want to add 3.12
            value = input("Add 3.12 python to supported versions list? (y/N): ")
            if value in "yY":
                self.test_versions.append("3.12")
                setup.classifiers.append("Programming Language :: Python :: 3.12")
        if not self.test_versions:
            logger.error("expecting language classifier, like 'Programming Language :: Python :: 3.8'")

        # LONG DESCRIPTION
        setup.long_description_content_type = "text/markdown"
        setup.long_description = readme.read().replace("\r", "")

        # PACKAGES
        expected_packages = [
            dir_name.replace("/", ".")
            for f in self.directory.leaves
            if f.stem == "__init__" and f.extension == "py"
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
            logger.warning(
                "Packages are {{existing}}. Maybe they should be {{proposed}}",
                existing=list(sorted(declared_packages)),
                proposed=list(sorted(expected_packages)),
            )

        # EXTRA DEPENDENCIES
        if test_req_file.exists:
            setup.extras_require.tests = [
                str(r) for line in test_req_file.read_lines() if line for r in [parse_req(line)] if r
            ]

        # VERSION
        setup.version = text(new_version)

        # REQUIRES
        reqs = self.get_next_requirements([r for line in setup.install_requires for r in [parse_req(line)] if r])
        setup.install_requires = [
            r.name + r.type + text(r.version) if r.version else r.name
            for r in sort_using_key(reqs, key=lambda rr: rr.name)
        ]

        # WRITE JSON FILE
        setup_json.write(value2json(setup, pretty=True))

    def svn_update(self):
        if not self.svn_branch:
            return
        try:
            self.local([self.git, "checkout", self.svn_branch])
        except Exception as cause:
            try:
                self.local([self.git, "checkout", self.dev_branch])
                self.local([self.git, "checkout", "-b", self.svn_branch])
            except Exception as other_cause:
                logger.error("not expected", cause=[cause, other_cause])

        self.local([self.git, "merge", self.dev_branch])

        for d in self.directory.find(r"\.svn"):
            svn_dir = d.parent.os_path
            if any(d in svn_dir for d in listwrap(Module.ignore_svn)):
                logger.info("Ignoring svn directory {{dir}}", dir=svn_dir)
                continue

            logger.info("Update svn directory {{dir}}", dir=svn_dir)
            self.local([self.svn, "update", "--accept", "p", svn_dir])
            self.local([self.svn, "commit", svn_dir, "-m", "auto"])

        self.local([self.git, "checkout", self.dev_branch])
        self.local([self.git, "merge", self.svn_branch])

    def update_dev(self, message):
        logger.info("Update git dev branch for {{dir}}", dir=self.directory.abs_path)
        self.scrub_pypi_residue()
        self.local([self.git, "add", "-A"])
        process, stdout, stderr = self.local([self.git, "commit", "-m", message], raise_on_error=False)
        if any(line.startswith("nothing to commit, working") for line in stdout) or process.returncode == 0:
            pass
        else:
            logger.error("not expected {{result}}", result=(stdout, stderr))
        try:
            self.local([self.git, "push", "origin", self.dev_branch])
        except Exception as e:
            logger.warning(
                "git origin dev not updated for {{dir}}", dir=self.directory.abs_path, cause=e,
            )

    def update_master_locally(self, version):
        logger.info("Update git master branch for {{dir}}", dir=self.directory.abs_path)
        try:
            v = text(version)
            self.local([self.git, "checkout", self.master_branch])
            self.local([self.git, "merge", "--no-ff", "--no-commit", self.dev_branch])
            self.local([self.git, "commit", "-m", "release " + v])
            self.local([self.git, "tag", v])
            self.local([self.git, "push", "--delete", "origin", v], raise_on_error=False)
            self.local([self.git, "push", "origin", v])
        except Exception as e:
            logger.error(
                "git origin master not updated for {{dir}}", dir=self.directory.stem, cause=e,
            )

    def run_tests(self, python_version, please_stop):
        # if python_version == "3.12":
        #     return  # python 3.12 is unstable

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
            test_reqs = None

            logger.info("install virtualenv into {{dir}}", dir=temp.abs_path)
            self.local([
                self.python[python_version],
                "-m",
                "pip",
                "install",
                "virtualenv",
            ])
            self.local(
                [self.python[python_version], "-m", "virtualenv", temp / ".venv"], cwd=temp,
            )
            self.local([python, "-m", "pip", "install", "--upgrade", "pip", "setuptools"], cwd=self.directory)

            # CLEAN INSTALL FIRST, TO TEST FOR VERSION COMPATIBILITY
            self.gen_setup_py_file()
            self.install_self(pip)

            # RUN THE SMOKE TEST
            logger.info("run tests/smoke_test.py")
            if (self.directory / "tests" / "smoke_test.py").exists:
                self.local(
                    [python, "-Werror", "tests/smoke_test.py"], env={"PYTHONPATH": ""}, debug=True, cwd=self.directory,
                )
            else:
                logger.warning("add tests/smoke_test.py to ensure the library will run after installed")

            # INSTALL TEST RESOURCES
            logger.info("install testing requirements")
            if (self.directory / "tests" / "requirements.txt").exists:
                # TRY THE lock FILE, FOR QUICKER INSTALL.  NOT NEEDED
                self.local([pip, "install", "--no-deps", "-r", "tests/requirements.lock"], raise_on_error=False)

                while True:
                    try:
                        self.local(
                            [
                                # pip,
                                python,
                                "-m",
                                "pip",
                                "install",
                                "--upgrade",
                                "-r",
                                "tests/requirements.txt",
                            ],
                            debug=True,
                        )
                        _, test_reqs, _ = self.local([pip, "freeze"], env={"PYTHONPATH": "."})
                        break
                    except Exception as cause:
                        if any(
                            'pip\\_vendor\\packaging\\version.py", line 264, in __init__' in e
                            for e in cause.cause.params.stderr
                        ):
                            # Happens occasionally, so retry
                            logger.warning("Problem with install", cause=cause.cause.params.stderr)
                        else:
                            raise cause

            # INSTALL SELF AGAIN TO ENSURE CORRECT VERSIONS ARE USED (EVEN IF CONFLICT WITH TEST RESOURCES)
            self.install_self(pip)

            # RUN THE TESTS
            with Timer("run tests"):
                process, stdout, stderr = self.local(
                    [python, "-m", "unittest", "discover", "tests", "-v"], env={"PYTHONPATH": "."}, debug=True,
                )
                logger.info("TESTS DONE")
                if len(stderr) < 2:
                    logger.error("Expecting unittest results (at least two lines of output)")
                summary = first(line for line in reversed(stderr) if line.startswith("Ran "))
                num_tests = int(strings.between(summary, "Ran ", " test"))
                if num_tests == 0:
                    logger.error("Expecting to run some tests: {{error}}", error=stderr[-2])
                summary_index = stderr.index(summary)

                if not stderr[summary_index + 1].startswith("OK"):
                    logger.error("Expecting all tests to pass: {{error}}", error=last(stderr))
                logger.info("STDERR:\n{{stderr|indent}}", stderr=stderr)

            # WRITE lock FILE TO RECORD THE SUCCESSFUL COMBINATION
            if test_reqs:
                self.write_lock_file(python, pip, python_version, test_reqs)

        logger.info("done")

    def write_lock_file(self, python, pip, python_version, test_reqs):
        # ONLY THE LOWEST VERSION WILL WRITE THE LOCKFILE
        if python_version != str(min(*(Version(v) for v in self.test_versions))):
            return

        try:
            test_req_file = self.directory / "tests" / "requirements.txt"
            versions = {
                r.name: r.version
                for line in test_reqs
                if line
                for r in [parse_req(line)]
                if r and r.name not in ["setuptools", "wheel", "pip", "build"]
            }
            new_test_reqs = []
            for line in test_req_file.read_lines():
                r = parse_req(line)
                if r:
                    new_version = versions.get(r.name)
                    if Version(new_version) > Version(r.version):
                        r.version = new_version
                        r.type = ">="
                        line = str(r)
                new_test_reqs.append(line)

            process, stdout, stderr = self.local([pip, "freeze"], env={"PYTHONPATH": "."})
            lock_reqs = [
                line
                for line in stdout
                if line and not any(line.startswith(p) for p in ["setuptools=", "wheel=", "pip=", "build=", f"{self.name}="])
            ]
            lock_lines = [f"# Tests pass with these versions {Date.now().format('%Y-%m-%d')}", *lock_reqs]

            lockfile = self.directory / "tests" / "requirements.lock"
            with Timer("update test requirements", verbose=True):
                with self.install_locker:
                    lockfile.write("\n".join(lock_lines))
                    test_req_file.write("\n".join(new_test_reqs))

        except Exception as cause:
            logger.error("Can not write lockfile", cause=cause)

    def install_self(self, pip):
        while True:
            try:
                with Timer("install self", verbose=True):
                    with self.install_locker:
                        logger.info("got lock")
                        p, stdout, stderr = self.local([pip, "install", "."], debug=True)
                if p.returncode and any("which is incompatible" in line for line in stderr):
                    logger.error("Seems we have an incompatibility problem", stderr=stderr)
                if p.returncode and any("conflicting dependencies" in line for line in stderr):
                    logger.error("Seems we have a conflicting dependencies problem", stderr=stderr)
                break
            except Exception as cause:
                if any("unable to write new index file" in e for e in cause.cause.params.stderr):
                    # Happens occasionally, so retry
                    logger.warning("Problem with install", cause=cause.cause.params.stderr)
                elif any("because the GET request got Content-Type" in e for e in cause.cause.params.stderr):
                    # Happens occasionally, so retry
                    logger.warning("Problem with install", cause=cause.cause.params.stderr)
                elif any("Directory '.' is not installable. " in e for e in cause.cause.params.stderr):
                    # Happens occasionally, so retry
                    (self.directory / "setup.py").write((self.directory / "packaging" / "setup.py").read())
                    logger.warning("Problem with install", cause=cause.cause.params.stderr)
                else:
                    logger.error("Problem with install", cause=cause)

    def local(self, args, raise_on_error=True, show_all=False, cwd=None, env=None, debug=False):
        try:
            cwd = coalesce(cwd, self.directory)
            env = coalesce(env, {"PYTHONPATH": "."})
            p = Command(
                self.name, args, cwd=cwd, env=env, max_stdout=10 ** 6, debug=debug, timeout=120
            ).join(raise_on_error=raise_on_error)
            stdout = list(p.stdout)
            stderr = list(p.stderr)
            p.join()
            if show_all:
                logger.info(
                    "{{module}} stdout = {{stdout}}\nstderr = {{stderr}}",
                    module=self.name,
                    stdout=stdout,
                    stderr=stderr,
                    stack_depth=1,
                )
            return p, stdout, stderr
        except Exception as cause:
            logger.error(
                "can not execute {{args}} in dir={{dir|quote}}", args=args, dir=self.directory.os_path, cause=cause,
            )

    def get_current_requirements(self, current_requires):
        # MAP FROM NAME TO CURRENT LIMITS
        lookup_old_requires = {r.name: r for r in current_requires}

        req = self.directory / "packaging" / "requirements.txt"
        output = to_data([
            r & lookup_old_requires.get(r.name) for line in req.read_lines() if line for r in [parse_req(line)] if r
        ])

        if any(r.name.startswith(("mo_", "jx_")) for r in output):
            logger.error("found problem in {{module}}", module=self.name)
        return output

    def get_next_requirements(self, current_requires):
        # MAP FROM NAME TO CURRENT LIMITS
        lookup_old_requires = {r.name: r for r in current_requires}

        req = self.directory / "packaging" / "requirements.txt"
        output = to_data([
            r & lookup_old_requires.get(r.name)
            if r.name not in self.graph.graph
            else Requirement(name=r.name, type="==", version=self.graph.get_version(r.name),)
            for line in req.read_lines()
            if line
            for r in [parse_req(line)]
            if r
        ])
        return output

    def get_major_version(self):
        return self.get_setup_version().major

    @cache()
    def get_setup_version(self):
        try:
            # read version from git
            p, stdout, stderr = self.local([self.git, "show", f"{self.dev_branch}:{SETUPTOOLS}"], raise_on_error=True,)
            setup = json2value("\n".join(stdout), leaves=False)
        except Exception:
            setup_json = self.directory / SETUPTOOLS
            setup = setup_json.read_json(leaves=False)
        return Version(setup.version, prefix="v")

    def clean_branches(self):
        p, stdout, stderr = self.local([self.git, "branch", "-a"])
        for branch in stdout:
            branch = branch.strip()
            if branch.startswith(TEMP_BRANCH_PREFIX):
                self.local([self.git, "branch", "-D", branch], raise_on_error=False)

    @cache()
    def get_version(self):
        # RETURN version, revision PAIR
        p, stdout, stderr = self.local([self.git, "tag"])
        # ONLY PICK VERSIONS WITH vX.Y.Z PATTERN
        all_versions = self.all_versions = list(sorted(
            v for line in stdout for v in [Version(line)] if v.major == self.get_major_version()
        ))

        if all_versions:
            version = max(all_versions)
            logger.info("Found {version} of {module} in git tags", version=version, module=self.name)
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
        logger.info("Find {{name}}=={{version}} in git history", name=self.package_name, version=version)
        p, stdout, stderr = self.local([self.git, "show", f"{version}:{SETUPTOOLS}"], raise_on_error=False)
        if p.returncode or any("invalid object name" in line for line in stderr):
            requirements = File(self.directory / SETUPTOOLS).read_json().install_requires
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
                    logger.error("do not know how to handle")
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
        ignored_files = [
            "setup.py",
            "setuptools.json",
            "requirements.lock",
            ".gitignore",
            "README.md",
        ]  # , ".travis.yml"]
        ignored_dir = ["packaging/", "tests/", "vendor/"]

        # get current version, hash
        version, revision = self.get_version()
        self.svn_update()
        self.update_dev("updates from other projects")
        # COMPARE TO MASTER
        branch_name = f"{TEMP_BRANCH_PREFIX}{randoms.string(10)}"
        while True:
            try:
                self.local([self.git, "checkout", "-b", branch_name, self.master_branch])
                break
            except Exception as cause:
                if "unable to write new index file" in cause:
                    logger.warning("retrying checkout", cause=cause)
                    continue
                raise cause
        try:
            self.local([self.git, "merge", self.dev_branch])
            p, stdout, stderr = self.local([self.git, "--no-pager", "diff", "--name-only", "master"], debug=True,)
            changed_files = [
                clean_line
                for line in stdout
                for clean_line in [line.strip()]
                if clean_line
                and clean_line not in ignored_files
                and not any(clean_line.startswith(d) for d in ignored_dir)
            ]
            if len(changed_files) > 4:
                logger.info("Upgrade {module} because {num} files changed", module=self.name, num=len(changed_files))
                curr_revision = self.current_revision()
            elif changed_files:
                logger.info(
                    "Upgrade {module} because {num} files changed {files}",
                    module=self.name,
                    num=len(changed_files),
                    files=changed_files,
                )
                curr_revision = self.current_revision()
            else:
                curr_revision = revision

            while True:
                try:
                    self.local([self.git, "checkout", "-f", self.dev_branch])
                    break
                except Exception as cause:
                    if any(r in cause for r in ["unable to write symref", "unable to write new index file"]):
                        logger.warning("retrying checkout", cause=cause)
                        continue
                    raise
        except Exception as e:
            logger.warning("problem determining upgrade status", cause=e)
            self.local([self.git, "reset", "--hard", "HEAD"])
            self.local([self.git, "checkout", "-f", self.dev_branch])
            curr_revision = self.current_revision()
        finally:
            try:
                self.local([self.git, "branch", "-D", branch_name], raise_on_error=True)
            except Exception:
                logger.info("can not delete branch {branch}", branch=branch_name)

        return curr_revision != revision

    def __str__(self):
        return self.name


def count(values):
    return sum(1 if exists(v) else 0 for v in values)


def value2python(value):
    if value in (True, False, None):
        return text(repr(value))
    elif is_text(value):
        return text(repr(value))
    elif is_binary(value):
        return text(repr(value))
    else:
        return value2json(value)
