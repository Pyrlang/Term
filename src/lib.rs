// Copyright 2018, Erlang Solutions Ltd, and S2HC Sweden AB
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
// http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.

#[macro_use] extern crate failure;
//#[macro_use]
//#[macro_use] extern crate lazy_static;
extern crate byte;
extern crate byteorder;
extern crate compress;
extern crate cpython;
extern crate empty;

use cpython::*;

use self::decoder::{Decoder, wrap_decode_result};
use self::encoder::{Encoder};
use self::errors::{pyresult_from};

mod consts;
mod decoder;
mod encoder;
mod errors;
mod helpers;

py_exception!(native_codec_impl, PyCodecError);


/// Strips 131 byte header and unpacks if the data was compressed.
fn binary_to_term(py: Python, b: PyBytes,
                  opts: PyObject) -> PyResult<PyObject> {
  let mut dec_state = Decoder::new(py, opts)?;
  pyresult_from(dec_state.decode_with_131tag(b.data(py)))
}


fn binary_to_term_2(py: Python, b: PyBytes,
                    opts: PyObject) -> PyResult<PyObject> {
  let mut dec_state = Decoder::new(py, opts)?;
  let result = dec_state.decode(b.data(py));
  pyresult_from(wrap_decode_result(py, result))
}


fn term_to_binary(py: Python, py_term: PyObject,
                  opt: PyObject) -> PyResult<PyBytes> {
  let mut enc_state = Encoder::new(py, opt)?;

  // Rest of the function is identical to ``term_to_binary_2`` except that
  // 131 byte is pushed to the output before the encoder is called
  enc_state.data.push(consts::ETF_VERSION_TAG);

  enc_state.encode(&py_term)?;
  Ok(PyBytes::new(py, enc_state.data.as_ref()))
}


fn term_to_binary_2(py: Python, py_term: PyObject,
                    opt: PyObject) -> PyResult<PyBytes> {
  let mut enc_state = Encoder::new(py, opt)?;
  enc_state.encode(&py_term)?;
  Ok(PyBytes::new(py, enc_state.data.as_ref()))
}


// add bindings to the generated python module
// N.B: names: "librust2py" must be the name of the `.so` or `.pyd` file
#[inline]
fn m_init(py: Python, m: &PyModule) -> PyResult<()> {
  m.add(py, "__doc__", "Erlang Term Format encoding and decoding.")?;
  m.add(py, "binary_to_term",
        py_fn!(py, binary_to_term(b: PyBytes, opt: PyObject)))?;
  m.add(py, "binary_to_term_2",
        py_fn!(py, binary_to_term_2(b: PyBytes, opt: PyObject)))?;
  m.add(py, "term_to_binary",
        py_fn!(py, term_to_binary(py_term: PyObject, opt: PyObject)))?;
  m.add(py, "term_to_binary_2",
        py_fn!(py, term_to_binary_2(py_term: PyObject, opt: PyObject)))?;
  m.add(py, "PyCodecError", py.get_type::<PyCodecError>())?;
  Ok(())
}
py_module_initializer!(
  native_codec_impl,
  initnative_codec_impl,
  PyInit_native_codec_impl,
  |py, m| { m_init(py, m) }
  );
