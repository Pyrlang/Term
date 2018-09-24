from setuptools import setup
from setuptools_rust import Binding, RustExtension

setup(name="term",
      version="1.0",
      rust_extensions=[RustExtension("term.native_codec_impl",
                                     binding=Binding.RustCPython)],
      packages=["term"],
      # rust extensions are not zip safe, just like C-extensions.
      zip_safe=False,
      )
