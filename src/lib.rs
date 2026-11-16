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

use pyo3::prelude::*;
use pyo3::types::PyBytes;

use self::decoder::Decoder;
use self::encoder::Encoder;

mod classes;
mod consts;
mod decoder;
mod encoder;
mod errors;
mod helpers;
mod reader;

// The one exception type every codec failure reaches Python as.
pyo3::create_exception!(
    native_codec_impl,
    PyCodecError,
    pyo3::exceptions::PyException
);

/// Strips 131 byte header and unpacks if the data was compressed.
/// Returns a tuple (value, remaining bytes).
#[pyfunction]
#[pyo3(signature = (b, opt))]
fn binary_to_term<'py>(
    py: Python<'py>,
    b: &Bound<'py, PyBytes>,
    opt: &Bound<'py, PyAny>,
) -> PyResult<Bound<'py, PyAny>> {
    let mut dec_state = Decoder::new(py, opt)?;
    let mut reader = b.as_bytes().into();
    Ok(dec_state.decode_with_131tag(&mut reader)?)
}

/// Decodes a term without the 131 byte header.
/// Returns a tuple (value, remaining bytes).
#[pyfunction]
#[pyo3(signature = (b, opt))]
fn binary_to_term_2<'py>(
    py: Python<'py>,
    b: &Bound<'py, PyBytes>,
    opt: &Bound<'py, PyAny>,
) -> PyResult<Bound<'py, PyAny>> {
    let mut dec_state = Decoder::new(py, opt)?;
    let mut reader = b.as_bytes().into();
    Ok(dec_state.decode_and_wrap(&mut reader)?)
}

/// Encodes a term and prepends the 131 byte header.
#[pyfunction]
#[pyo3(signature = (py_term, opt))]
fn term_to_binary<'py>(
    py: Python<'py>,
    py_term: &Bound<'py, PyAny>,
    opt: &Bound<'py, PyAny>,
) -> PyResult<Bound<'py, PyBytes>> {
    let mut enc_state = Encoder::new(py, opt)?;

    // Rest of the function is identical to ``term_to_binary_2`` except that
    // 131 byte is pushed to the output before the encoder is called
    enc_state.data.push(consts::ETF_VERSION_TAG);

    enc_state.encode(py_term)?;
    Ok(enc_state.into_bytes()?)
}

/// Encodes a term without the 131 byte header.
#[pyfunction]
#[pyo3(signature = (py_term, opt))]
fn term_to_binary_2<'py>(
    py: Python<'py>,
    py_term: &Bound<'py, PyAny>,
    opt: &Bound<'py, PyAny>,
) -> PyResult<Bound<'py, PyBytes>> {
    let mut enc_state = Encoder::new(py, opt)?;
    enc_state.encode(py_term)?;
    Ok(enc_state.into_bytes()?)
}

/// Erlang Term Format encoding and decoding.
// The module name must match the file name `native_codec_impl.*.pyd/.so` that
// setuptools-rust builds for `term.native_codec_impl`.
#[pymodule]
mod native_codec_impl {
    #[pymodule_export]
    use super::{binary_to_term, binary_to_term_2, term_to_binary, term_to_binary_2, PyCodecError};
}
