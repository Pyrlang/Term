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
use pyo3::types::{PyDict, PyInt, PyString};

use super::errors::{CodecError, CodecResult};

/// Get dict value with string key, expect it to be string too, or return
/// the default value.
pub fn get_str_opt(opts: &Bound<'_, PyDict>, optname: &str, default: &str) -> CodecResult<String> {
    match opts.get_item(optname)? {
        Some(val) => {
            let py_str = val.cast::<PyString>()?;
            Ok(py_str.to_string_lossy().into_owned())
        }
        None => Ok(default.to_string()),
    }
}

/// Given a dict or a possibly None, return dict
pub fn maybe_dict<'py>(dict_or_none: &Bound<'py, PyAny>) -> CodecResult<Bound<'py, PyDict>> {
    if dict_or_none.is_none() {
        Ok(PyDict::new(dict_or_none.py()))
    } else {
        Ok(dict_or_none.cast::<PyDict>()?.clone())
    }
}

/// Get dict value with string key, expect a positive int (a size or a
/// limit), or return the default value.
pub fn get_positive_int_opt(
    opts: &Bound<'_, PyDict>,
    optname: &str,
    default: usize,
) -> CodecResult<usize> {
    let Some(val) = opts.get_item(optname)? else {
        return Ok(default);
    };
    // bool is an int subclass in Python, but not a size
    if !val.is_exact_instance_of::<PyInt>() {
        return Err(bad_positive_int(optname, &val));
    }
    match val.extract::<usize>() {
        Ok(n) if n > 0 => Ok(n),
        _ => Err(bad_positive_int(optname, &val)),
    }
}

fn bad_positive_int(optname: &str, val: &Bound<'_, PyAny>) -> CodecError {
    CodecError::BadOptions {
        txt: format!("'{}' option is {}; expected a positive int", optname, val),
    }
}

#[derive(Eq, PartialEq, Copy, Clone)]
pub enum AtomRepresentation {
    TermAtom,
    TermStrictAtom,
    Bytes,
    Str,
}

#[derive(Eq, PartialEq)]
pub enum ByteStringRepresentation {
    Bytes,
    Str,
    IntList,
}

/// Option: "atom" => "bytes" | "str" | "Atom" | "StrictAtom" (as Atom class, default)
pub fn get_atom_opt(opts1: &Bound<'_, PyDict>) -> CodecResult<AtomRepresentation> {
    let opt_s = get_str_opt(opts1, "atom", "Atom")?;
    match opt_s.as_ref() {
        "bytes" => Ok(AtomRepresentation::Bytes),
        "str" => Ok(AtomRepresentation::Str),
        "Atom" => Ok(AtomRepresentation::TermAtom),
        "StrictAtom" => Ok(AtomRepresentation::TermStrictAtom),
        other => {
            let txt = format!(
                "'atom' option is '{}' while expected: bytes, str, Atom, StrictAtom",
                other
            );
            Err(CodecError::BadOptions { txt })
        }
    }
}

/// Option: "byte_string" => "bytes" | "str" | "int_list" (default: str)
pub fn get_byte_str_opt(opts1: &Bound<'_, PyDict>) -> CodecResult<ByteStringRepresentation> {
    let opt_s: String = get_str_opt(opts1, "byte_string", "str")?;
    match opt_s.as_ref() {
        "bytes" => Ok(ByteStringRepresentation::Bytes),
        "str" => Ok(ByteStringRepresentation::Str),
        "int_list" => Ok(ByteStringRepresentation::IntList),
        other => {
            let txt = format!(
                "'byte_string' option is '{}' while expected: bytes, str",
                other
            );
            Err(CodecError::BadOptions { txt })
        }
    }
}

// The "bitstring" decode option: what a BIT_BINARY_EXT becomes in Python.
#[derive(Eq, PartialEq, Copy, Clone)]
pub enum BitstringRepresentation {
    Tuple,
    BitString,
}

/// Option: "bitstring" => "tuple" (default) | "BitString"
pub fn get_bitstring_opt(opts1: &Bound<'_, PyDict>) -> CodecResult<BitstringRepresentation> {
    let opt_s = get_str_opt(opts1, "bitstring", "tuple")?;
    match opt_s.as_ref() {
        "tuple" => Ok(BitstringRepresentation::Tuple),
        "BitString" => Ok(BitstringRepresentation::BitString),
        other => Err(CodecError::BadOptions {
            txt: format!(
                "'bitstring' option is '{}' while expected: tuple, BitString",
                other
            ),
        }),
    }
}

/// BIT_BINARY_EXT carries 1..8 bits in its last byte, so it has a last byte
/// (binary_SUITE:bad_terms, bad_binary_to_term).
pub fn check_bits(size: usize, bits: u8) -> CodecResult<()> {
    if !(1..=8).contains(&bits) || size == 0 {
        return Err(CodecError::BadBitstring { size, bits });
    }
    Ok(())
}

/// Copy of a bitstring's bytes with the unused low bits of the last byte
/// cleared, as OTP does. `bits` is 1..8 (see `check_bits`).
pub fn mask_last_byte(value: &[u8], bits: u8) -> Vec<u8> {
    let mut out = value.to_vec();
    if let Some(last) = out.last_mut() {
        *last &= 0xFFu8.checked_shl(u32::from(8 - bits)).unwrap_or(0);
    }
    out
}

pub trait VecWriteExt {
    fn push_u32(&mut self, value: u32);
    fn push_i32(&mut self, value: i32);
    fn push_u16(&mut self, value: u16);
    fn push_f64(&mut self, value: f64);
}

impl VecWriteExt for Vec<u8> {
    fn push_u32(&mut self, value: u32) {
        self.extend(value.to_be_bytes());
    }

    fn push_i32(&mut self, value: i32) {
        self.extend(value.to_be_bytes());
    }

    fn push_u16(&mut self, value: u16) {
        self.extend(value.to_be_bytes());
    }

    fn push_f64(&mut self, value: f64) {
        self.extend(value.to_be_bytes());
    }
}

#[cfg(test)]
mod tests {
    use super::{check_bits, mask_last_byte};

    #[test]
    fn mask_clears_unused_low_bits() {
        assert_eq!(mask_last_byte(&[0xFF, 0xFF], 1), [0xFF, 0x80]);
        assert_eq!(mask_last_byte(&[0xFF], 7), [0xFE]);
        assert_eq!(mask_last_byte(&[0xFF], 8), [0xFF]);
        assert_eq!(mask_last_byte(&[], 3), [0u8; 0]);
    }

    #[test]
    fn bits_must_be_1_to_8_with_a_byte() {
        assert!(check_bits(1, 1).is_ok());
        assert!(check_bits(1, 8).is_ok());
        assert!(check_bits(1, 0).is_err());
        assert!(check_bits(1, 9).is_err());
        assert!(check_bits(0, 1).is_err());
    }
}
