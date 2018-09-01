
# Managing library code across multiple projects

This document details my process for managing many libraries used in many projects, and keeping the code in sync across all the combinations.


## Source code is wonderful! Use it. Own it. 

This document assumes source code is useful, and can act as an effort multiplier to those that are familiar with the code.

Source code is beneficial in many ways, and I will list some of those ways code is useful. The reasoning overlaps somewhat, but I hope portray that code-as-a-library is powerful. 

* **Reduced Learning Curve** - If you are already familiar with code that provides a solution, and you know its behaviour in corner case, you should use it over other 3rd party libraries, even if they may be more mature. You save yourself the time of climbing the learning curve for the 3rd party library, and save yourself from being surprised when it does not work as expected.
* **Utilities** - Many projects have a `utils` directory that contains code that does not belong elsewhere in the project. Often those utility functions can be used in other projects; used like a toolbox.
* **Domain specific functions** - If you are coding in a specific field, you will see common patterns in the data structures and algorithms needed to solve problems in those fields. These are not utilility functions, rather can occupy multiple libraries   
* **Facade** - Code can act as a facade over another library.  Often your application makes certain assumptions, or uses only a portion of library, that allows you to simplify calls to that library. Facades are also a good strategy to isolate your application code from the library implementation code
* **Understanding a domain** - Maybe you see the world differently: Maybe you are mathematician and you wonder how engineers use and produce code with such sprawling and irregular behaviour. Maybe you are an engineer and you wonder how mathematicians use and produce such densely inscrutable code. In either case you make a facade that allows you to leverage that already-existing code while smoothing over bumps and communicating more clearly.   
* **Incomplete libraries** - Being a domain expert, you may want to write a framework. But your time is limited, so you slowly refactor an existing project to separate the framework code from the rest of the project, or you may write just a skeleton of a new framework, and fill in the pieces your project actually use.
* **3rd party code stability** - including the source code of another project is called "vendoring", and it is useful to cement the specific version of the library that works in your project; this gives you control over when and what gets changed in the future.
* **3rd party bug fixes** - Most 3rd libraries are incomplete in some way that your project would like to use it. Maybe this is a bug fix, or a missing feature. Vendoring the code allows you to expediently fix bugs and add those features while you wait on the project maintainer to accept those changes, assuming the maintainer will ever accept those changes.  
* **Extension of your knowledge** - Code can contain the details of a process that your mind will soon forget. You may require the effect of a process often, but forgetting how it is implemented. Use should be using code as your knowledge store: You become a more capable coder when you have a large library of code you are inimitably familiar with. New projects are easier to start, and you are faster at getting-stuff-done.  

For whatever reason, you have a suite of useful code that you use to implement solutions. They may have a range of maturity, but your intimate familiarity with the code mitigates that.

## Problem

Starting a new project is difficult because you must import, in one way or another, your personal suite of useful code.  

Code is useful, you are intimately familiar with its inner workings, and you would like to use it in your projects
You want you library code included in each of your projects,  (this is called "vendoring" 

```
my_project
  |
  +-- vendor
        |
        +-- my_library
```


the library code does not change - once you have your project tests passing, you do not want you code changing
You can fix the library code in your project, reducing your debug cycle,  staying focused on your project, 



### Packaged projects?

package project cycle:

* while debugging `my_project` 
* you see a bug in `my_library` code
* you switch to the `my_library` project
* you change the `my_library` code
* you package `my_library`
* you update `my_library` package in `my_project`
* you resume debugging `my_project`


## Solution: Two version control systems

Your projects are managed with one vcs, and your libraries are synched with another vcs. In this document we will assume Git and Subversion respectively.  Each has particular properties that are well suited to managing libraries in the manner   





You can use this technique on all your vendor libraries. It helps especially when your vendor code lacks comprehensive tests: Each project that uses you vendor library effectively acts as a test suite.



## Overview

We will use the following directory pattern to allow both vcs' to track the project and library code. This will be explained in more detail below.

```
my-project
  |
  +- .git
  |
  +-- my_project
  |
  +-- vendor 
  |    |
  |    +-- my_library
  |          |
  |          +-- .svn
  |
  +-- tests
```

Please notice 

* projects are named with dashes (`-`), eg `my-project`
* code subdirectories are named with underscore (`_`), eg `my_project`

### Project Setup

Setup Subversion host your library

    svn mkdir svn://localhost/libraries/my_library

> I installed SVN locally so I can perform cross-project synching while offline (and it is faster).


Subversion is very good a tracking subdirectories independently. Notice you can use one Subversion repo, called `libraries`, and put each library in a separate subdirectory.

Ensure `my-project` has a `dev` branch on `git`
    
    git checkout -b dev

make a new `svn` repo to track the `vendor/my_library` directory
    
    cd my-project/vendor
    svn checkout svn://localhost/my_library


### Project Synchronization

If you have two projects with vendored `my_library` you probably will want to occasionally synch them:
 
Ensure you are on `dev` branch

    git checkout dev

Update libary with changes from other projects

	svn update --accept p vendor/my_library

Commit those changes, for good measure

    git add -A
    git commit -m "lib updates"

Ensure you push your library updates to Subversion so other projects can use it

    svn commit vendor\my_library -m "lib updates"

> I use TortoiseSVN to perform the syncing (it shows the files I forgot to add)

## Library as a project

If a library is big enough, it may require tests, configuration, and deployment resources. It is not recommended for small libraries because there are project support costs. (repo, issues, deployment, etc).


```
my-library
  |
  +- .git
  |
  +- my_library
  |    |
  |    +- .svn
  |
  +- tests
```

### Library Setup 

Make a Git repo for your library-as-a-project, then clone it

    git clone my-library

Ensure you have a `dev` branch

    gti checkout -b dev

Checkout the library code from Subversion into your code directory

	cd my-library
    svn checkout svn://localhost/my_library

Please notice that only the code is tracked with Subversion.  


### Library Synchronization

Syncing a library is much like syncing a vendor directory.

Ensure you are on `dev` branch

    git checkout dev

Update library with changes from other projects

    cd my-library
	svn update --accept p my_library

Commit those changes, for good measure

    git add -A
    git commit -m "lib updates"

Ensure you push your library updates to Subversion so other projects can use it

    svn commit my_library -m "lib updates"



