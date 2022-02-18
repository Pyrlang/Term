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

use cpython::*;

use super::PyCodecError;

#[derive(Debug, Fail)]
pub enum CodecError {
    #[fail(display = "Feature is not implemented yet")]
    NotImpl,
    #[fail(display = "ETF version 131 is expected")]
    UnsupportedETFVersion,
    #[fail(display = "Input is empty")]
    EmptyInput,
    #[fail(display = "Compressed size does not match decompressed")]
    CompressedSizeMismatch,
    #[fail(display = "Read failed: {}", txt)]
    ReadError { txt: String },
    #[fail(display = "{}", txt)]
    PythonError { txt: String },
    #[fail(display = "Unrecognized term tag byte: {}", b)]
    UnknownTermTagByte { b: u8 },
    #[fail(display = "Bad options passed: {}", txt)]
    BadOptions { txt: String },
    #[fail(display = "Input too short while decoding a binary")]
    BinaryInputTooShort,
    #[fail(display = "Input too short while decoding a string")]
    StrInputTooShort,
    //  #[fail(display="Encoding for type {} is not implemented", t)]
    //  NotImplEncodeForType { t: String },
    #[fail(
        display = "Integer {} is too large (> 32bit): big integers not impl",
        i
    )]
    IntegerEncodingRange { i: i64 },
    #[fail(display = "Atom text is too long (65535 bytes limit reached)")]
    AtomTooLong,
    #[fail(display = "Float value {} is not finite", f)]
    NonFiniteFloat { f: f64 },
    #[fail(display = "IOError: {}", txt)]
    IOError { txt: String },
}

pub type CodecResult<T> = Result<T, CodecError>;

impl std::convert::From<PyErr> for CodecError {
    fn from(err: PyErr) -> CodecError {
        CodecError::PythonError {
            txt: format!("{:?}", err),
        }
    }
}

impl std::convert::From<std::io::Error> for CodecError {
    fn from(err: std::io::Error) -> CodecError {
        CodecError::IOError {
            txt: format!("{:?}", err),
        }
    }
}

impl std::convert::From<byte::Error> for CodecError {
    fn from(err: byte::Error) -> CodecError {
        CodecError::ReadError {
            txt: format!("{:?}", err),
        }
    }
}

impl std::convert::From<CodecError> for PyErr {
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
