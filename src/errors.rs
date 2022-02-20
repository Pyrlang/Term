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

use std::{convert::From, str::Utf8Error};

use cpython::*;

use crate::reader::ReadError;

use super::PyCodecError;

use thiserror::Error;

#[derive(Error, Debug)]
pub enum CodecError {
    #[error("ETF version 131 is expected")]
    UnsupportedETFVersion,
    #[error("Compressed size does not match decompressed")]
    CompressedSizeMismatch,
    #[error("Read failed")]
    ReadError(#[from] ReadError),
    #[error("{txt}")]
    PythonError { txt: String, error: PyErr },
    #[error("Unrecognized term tag byte: {}", b)]
    UnknownTermTagByte { b: u8 },
    #[error("Bad options passed: {}", txt)]
    BadOptions { txt: String },
    #[error("Integer {} is too large (> 32bit): big integers not impl", i)]
    IntegerEncodingRange { i: i64 },
    #[error("Float value {} is not finite", f)]
    NonFiniteFloat { f: f64 },
    #[error("IOError")]
    IOError(#[from] std::io::Error),
    #[error("Encoding error")]
    EncodingError(#[from] Utf8Error),
    #[error("Atom too long")]
    AtomTooLong,
}

pub type CodecResult<T> = Result<T, CodecError>;

impl From<PyErr> for CodecError {
    fn from(err: PyErr) -> Self {
        CodecError::PythonError {
            txt: format!("{:?}", err),
            error: err,
        }
    }
}

impl From<CodecError> for PyErr {
    /// Somehow this works. Create a PyErr struct without traceback, containing
    /// a PyCodecError created from Rust CodecError with string explanation.
    fn from(err: CodecError) -> PyErr {
        let gil = Python::acquire_gil();
        let py = gil.python();
        let ty = py.get_type::<PyCodecError>();

        // CodecErrors are formatted using #[fail...] attribute format string
        let err_str = format!("{}", err);
        let py_str = PyString::new(py, &err_str);
        let noargs = PyTuple::new(py, &[py_str.into_object()]);
        let err_val = ty.call(py, noargs, None).unwrap();

        let tyo = ty.into_object();
        PyErr {
            ptype: tyo,
            pvalue: Some(err_val),
            ptraceback: None,
        }
    }
}

/// Repacks CodecResult<T> into PyResult<T>
pub fn pyresult_from<T>(r: Result<T, CodecError>) -> Result<T, PyErr> {
    match r {
        Ok(x) => Ok(x),
        Err(e) => Err(PyErr::from(e)),
    }
}
