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

use std::str::Utf8Error;

use pyo3::{CastError, CastIntoError, PyErr};

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
    // A pid, port or reference whose node is not an atom (OTP rejects it).
    #[error("Node name must be an atom, found tag {}", b)]
    NodeNotAnAtom { b: u8 },
    #[error("Bad options passed: {}", txt)]
    BadOptions { txt: String },
    // A bitstring whose last byte would hold 0 or more than 8 bits.
    #[error(
        "Bitstring of {} bytes with {} bits in the last byte (expected 1..8 bits, 1 or more bytes)",
        size,
        bits
    )]
    BadBitstring { size: usize, bits: u8 },
    // More magnitude bytes than LARGE_BIG_EXT's 32-bit count can declare.
    #[error("Integer is too large for LARGE_BIG_EXT")]
    IntegerTooLarge,
    // A list, string or tuple longer than its 32-bit length field.
    #[error("{} elements do not fit a 32-bit length", size)]
    TooLong { size: usize },
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
            txt: err.to_string(),
            error: err,
        }
    }
}

// A failed type check of a Python object (`Bound::cast`) is a Python error.
impl From<CastError<'_, '_>> for CodecError {
    fn from(err: CastError<'_, '_>) -> Self {
        PyErr::from(err).into()
    }
}

// Same as above, for the consuming `Bound::cast_into`.
impl From<CastIntoError<'_>> for CodecError {
    fn from(err: CastIntoError<'_>) -> Self {
        PyErr::from(err).into()
    }
}

/// Every codec failure, including a Python error met on the way, reaches
/// Python as `PyCodecError` carrying the formatted message.
impl From<CodecError> for PyErr {
    fn from(err: CodecError) -> PyErr {
        PyCodecError::new_err(err.to_string())
    }
}
