from setuptools import setup

VERSION = '1.4'
PKGNAME = "pyrlang-term"
MODULENAME = "term"
DESCR = 'Erlang term and External Term Format codec in Python and native Rust extension'
AUTHOR = 'Erlang Solutions Ltd and S2HC Sweden AB'
AUTHOR_EMAIL = 'dmytro.lytovchenko@gmail.com, pyrlang@s2hc.com'
URL = "https://github.com/Pyrlang/Term"

with open("README.md", "r", encoding='utf-8') as fp:
    LONG_DESCRPTION = fp.read()
LONG_DESCRPTION_CONTENT_TYPE = "text/markdown"

try:
    from setuptools_rust import Binding, RustExtension

    setup(name=PKGNAME,
          version=VERSION,
          url=URL,
          description=DESCR,
          long_description=LONG_DESCRPTION,
          long_description_content_type=LONG_DESCRPTION_CONTENT_TYPE,
          author=AUTHOR,
          author_email=AUTHOR_EMAIL,
          rust_extensions=[RustExtension("term.native_codec_impl",
                                         binding=Binding.RustCPython)],
          packages=[MODULENAME],
          # rust extensions are not zip safe, just like C-extensions.
          zip_safe=False)
except Exception as e:
    print("----------------------------")
    print("Rust build failed, continue with Python slow implementation only")
    print("error was:", e)
    print("----------------------------")

    setup(name=PKGNAME,
          version=VERSION,
          url=URL,
          description=DESCR,
          long_description=LONG_DESCRPTION,
          long_description_content_type=LONG_DESCRPTION_CONTENT_TYPE,
          author=AUTHOR,
          author_email=AUTHOR_EMAIL,
          packages=[MODULENAME])
