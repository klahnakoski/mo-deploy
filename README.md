# More Deployment!

Lightweight CI tool for the `mo-*` projects 

## Overview

### Nomenclature

* **module** - a Python file, or directory
* **package** - Some number of modules together, probably on pypi
* **project** - Code for some purpose, probably found on Github, maybe the source for yet-another-package 

All packages are version-controlled using two systems; Git and SVN. The Git is used to track the official branches for the packages, while SVN tracks the `dev` branch across multiple projects that vendored the package source code.

Most packages are developed in the projects they are used: Packages are included in a project to keep the project simple, and the package is enhanced as the project grows. This happens across multiple projects and packages.

### Example

[mo-dots](https://github.com/klahnakoski/mo-dots) is a package used in the [ActiveData](https://github.com/mozilla/ActiveData/tree/dev/vendor/mo_dots) project.

## Can I use this?

Probably not. There are no tests, and deployment requires a specific project layout. 

## Steps

Deployment has the following steps

* Scan modules to determine which require upgrade
* Manage DAG of modules to ensure they are deployed in proper order
* Merge svn changes onto git dev branch
* Update version numbers 
* Merge to git master
* Ensure pip install works
* Ensure the test suite is run and passes
* use twine to upload to pypi