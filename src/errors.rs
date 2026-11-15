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

use pyo3::{CastError, CastIntoError, PyErr, Python};

use crate::reader::ReadError;

use super::PyCodecError;

use thiserror::Error;

#[derive(Error, Debug)]
pub enum CodecError {
    #[error("ETF version 131 is expected")]
    UnsupportedETFVersion,
    #[error("Compressed size does not match decompressed")]
    CompressedSizeMismatch,
    // The zlib stream of a compressed term ends before its checksum.
    #[error("Compressed term: the zlib stream is incomplete")]
    CompressedIncomplete,
    // A compressed term declares more data than option "max_size" allows.
    #[error("Compressed term declares {declared} bytes, more than max_size {max_size}")]
    CompressedTooLarge { declared: usize, max_size: usize },
    // zlib rejected the stream of a compressed term.
    #[error("Compressed term: {txt}")]
    Compressed { txt: String },
    // A count field larger than the remaining input could hold.
    #[error("{what} declares {count} elements but only {remaining} bytes remain")]
    TooManyElements {
        what: &'static str,
        count: usize,
        remaining: usize,
    },
    // Nesting beyond option "max_depth".
    #[error("Term is nested deeper than max_depth {max_depth}")]
    TooDeep { max_depth: usize },
    // A value to encode that contains itself.
    #[error("Value contains itself (a {type_name})")]
    Cyclic { type_name: String },
    // Encode hooks that keep returning values with no encoding of their own.
    #[error("Value is substituted more than max_depth {max_depth} times")]
    TooManySubstitutions { max_depth: usize },
    // NEW_FUN_EXT with more free variables than MAX_ARG (255).
    #[error("NEW_FUN_EXT has {count} free variables, at most 255")]
    TooManyFree { count: usize },
    // NEW_FUN_EXT whose creator pid is not a pid.
    #[error("NEW_FUN_EXT pid must be a pid, found tag {b}")]
    FunPidNotAPid { b: u8 },
    // A Fun to encode with a field of the wrong type or out of range.
    #[error("{0}")]
    BadFunValue(&'static str),
    #[error("Read failed: {0}")]
    ReadError(#[from] ReadError),
    // A Python call failed (a user hook raised, a type check failed); the
    // original exception becomes the PyCodecError's __cause__.
    #[error("{txt}")]
    PythonError { txt: String, error: PyErr },
    // A decoded map key that a Python dict cannot hold (a list, a dict).
    #[error("Map key of type {type_name} is not hashable")]
    UnhashableKey { type_name: String, error: PyErr },
    #[error("Unrecognized term tag byte: {}", b)]
    UnknownTermTagByte { b: u8 },
    // A pid, port or reference whose node is not an atom, or an export fun
    // whose module or function is not (OTP rejects them).
    #[error("{what} must be an atom, found tag {b}")]
    NotAnAtom { what: &'static str, b: u8 },
    // An integer field of EXPORT_EXT or NEW_FUN_EXT that is not an integer,
    // or not a small one (OTP requires is_small).
    #[error("{what} must be an integer, found tag {b}")]
    NotAnInteger { what: &'static str, b: u8 },
    #[error("{what} is out of range")]
    IntegerRange { what: &'static str },
    // An 8-bit creation above 3 in an old node-container tag (OTP rejects it).
    #[error("{what} creation {creation} is above 3")]
    BadCreation { what: &'static str, creation: u8 },
    // A reference with no ID words or more than 5 (decoding or encoding).
    #[error("{what} has {words} ID words, expected 1..5")]
    BadRefWords { what: &'static str, words: u16 },
    // REFERENCE_EXT or NEW_REFERENCE_EXT whose first ID word exceeds 18 bits.
    #[error("{what} first ID word is above 18 bits")]
    BadRefFirstWord { what: &'static str },
    // A Reference to encode whose ID is not 1..5 words of 4 bytes.
    #[error("Reference ID of {size} bytes; expected 1..5 words of 4 bytes")]
    BadRefId { size: usize },
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
    // FLOAT_EXT whose 31 bytes are not a float's text ended by a NUL.
    #[error("FLOAT_EXT does not hold a float")]
    BadFloatText,
    #[error("Float value {} is not finite", f)]
    NonFiniteFloat { f: f64 },
    #[error("Encoding error")]
    EncodingError(#[from] Utf8Error),
    // An atom of more than 255 characters (decoding or encoding).
    #[error("Atom has {chars} characters, at most 255")]
    AtomTooLong { chars: usize },
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
/// Python as `PyCodecError` carrying the formatted message; a Python error
/// is kept as its `__cause__`.
impl From<CodecError> for PyErr {
    fn from(err: CodecError) -> PyErr {
        let codec_err = PyCodecError::new_err(err.to_string());
        match err {
            CodecError::PythonError { error, .. } | CodecError::UnhashableKey { error, .. } => {
                Python::attach(|py| codec_err.set_cause(py, Some(error)));
                codec_err
            }
            _ => codec_err,
        }
    }
}
