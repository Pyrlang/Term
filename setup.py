from setuptools import setup

VERSION = '1.1'
PKGNAME = "term"
DESCR = 'Erlang term and External Term Format codec in Python and native Rust extension'
AUTHOR = 'Erlang Solutions Ltd and S2HC Sweden AB',
AUTHOR_EMAIL = 'dmytro.lytovchenko@gmail.com,pyrlang@s2hc.com',

try:
    from setuptools_rust import Binding, RustExtension

    setup(name=PKGNAME,
          version=VERSION,
          description=DESCR,
          author=AUTHOR,
          author_email=AUTHOR_EMAIL,
          rust_extensions=[RustExtension("term.native_codec_impl",
                                         binding=Binding.RustCPython)],
          packages=[PKGNAME],
          # rust extensions are not zip safe, just like C-extensions.
          zip_safe=False)
except:
    print("----------------------------")
    print("Rust Setuptools not found, continue with Python slow implementation only")
    print("----------------------------")

    setup(name=PKGNAME,
          version=VERSION,
          description=DESCR,
          author=AUTHOR,
          author_email=AUTHOR_EMAIL,
          packages=[PKGNAME])
