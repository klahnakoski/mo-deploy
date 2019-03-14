

## Source code is wonderful! Use it.

This document assumes source code is useful, and is an effort multiplier to those that are familiar with the code.

Source code is beneficial in many ways, and I will list some of those ways code is useful. The reasoning overlaps somewhat, but I hope portray that code-as-a-library is powerful. 

* **Reduced Learning Curve** - If you are already familiar with code that provides a solution, and you know its behaviour in corner case, you should use it over other 3rd party libraries, even if they may be more mature. You save yourself the time of climbing the learning curve for the 3rd party library, and save yourself from being surprised when it does not work as expected.
* **Bigger toolbox** - Many projects have a `utils` directory that contains code that does not belong elsewhere in the project. Often those utility functions can be used in other projects; used like a toolbox.
* **Domain specific functions** - If you are coding in a specific field, you will see common patterns in the data structures and algorithms needed to solve problems in those fields. These are not utilility functions, rather can occupy multiple libraries   
* **Facade** - Code can act as a facade over another library. Often your application makes certain assumptions, or uses only a portion of library, that allows you to simplify calls to that library. Facades are also a good strategy to isolate your application code from the library implementation code
* **Understanding a domain** - Maybe you see the world differently: Maybe you are mathematician and you wonder how engineers use and produce code with such sprawling and irregular behaviour. Maybe you are an engineer and you wonder how mathematicians use and produce such densely inscrutable code. In either case you make a facade that allows you to leverage that already-existing code while smoothing over bumps and communicating more clearly.   
* **Incomplete libraries** - Being a domain expert, you may want to write a framework. But your time is limited, so you slowly refactor an existing project to separate the framework code from the rest of the project, or you may write just a skeleton of a new framework, and fill in the pieces your project actually use.
* **3rd party code stability** - including the source code of another project is called "vendoring", and it is useful to cement the specific version of the library that works in your project; this gives you control over when and what gets changed in the future.
* **3rd party bug fixes** - Most 3rd libraries are incomplete in some way that your project would like to use it. Maybe this is a bug fix, or a missing feature. Vendoring the code allows you to expediently fix bugs and add those features while you wait on the project maintainer to accept those changes.
* **Extension of your knowledge** - Code can contain the details of a process that your mind will soon forget. You may require the effect of a process often, but forget how to implement it. You should use code as your knowledge store: You become a more capable coder when you have a large library of code you are inimitably familiar with. New projects are easier to start, and you are faster at getting-stuff-done.  

For whatever reason, you have a suite of useful code that you use to implement solutions. They may have a range of maturity, but your intimate familiarity with the code mitigates that.