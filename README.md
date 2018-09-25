Erlang Term and Codec for Python
================================

This project is a part of http://github.com/Pyrlang/Pyrlang
but does not depend on it and can be used separately.

The Term library adds support classes to represent Erlang terms in Python 
and implements a codec for encoding and decoding data in Erlang
External Term Format (abbreviated ETF) written in Python and a native 
and (most likely) safe Python extension written in Rust. 

The extension or Python implementation is selected automatically when you import 
`term.codec` and all API is available via `term.codec` module. If native 
extension was not found, a warning will be logged and the Python implementation
will be used.

Documentation
-------------

Here: https://pyrlang.github.io/Term/
