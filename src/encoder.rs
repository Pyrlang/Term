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

use crate::helpers::VecWriteExt;

use super::consts;
use super::errors::{CodecError, CodecResult};
use super::helpers;
use pyo3::prelude::*;
use pyo3::types::{PyBytes, PyDict, PyList, PyString, PyTuple};
use std::borrow::Cow;

pub struct Encoder<'py> {
    pub py: Python<'py>, // Python instance will live at least as long as Encoder
    pub data: Vec<u8>,
    pub encode_hook: Bound<'py, PyDict>,
    pub catch_all: Option<Bound<'py, PyAny>>,
    // A function py_codec_impl.generic_serialize_object used for unknown classes
    pub cached_generic_serialize_fn: Option<Bound<'py, PyAny>>,
}

impl<'py> Encoder<'py> {
    pub fn new(py: Python<'py>, opt: &Bound<'py, PyAny>) -> CodecResult<Encoder<'py>> {
        let py_opts = helpers::maybe_dict(opt)?;
        let encode_hook = match py_opts.get_item("encode_hook")? {
            Some(h1) => h1.cast_into::<PyDict>()?,
            None => PyDict::new(py),
        };
        let catch_all = encode_hook.get_item("catch_all")?;

        Ok(Encoder {
            py,
            data: Vec::with_capacity(32),
            encode_hook,
            catch_all,
            cached_generic_serialize_fn: None,
        })
    }

    pub fn encode(&mut self, py_term: &Bound<'py, PyAny>) -> CodecResult<()> {
        // If the type name (`__name__`) of the term is in encode_hook, encode
        // what the hook returns instead
        if !self.encode_hook.is_empty() {
            let type_name = py_term.get_type().name()?;
            if let Some(h1) = self.encode_hook.get_item(type_name)? {
                let repr1 = h1.call1((py_term,))?;
                return self.encode_default(&repr1);
            }
        }
        self.encode_default(py_term)
    }

    /// Dispatch on the type name (`__name__`) of the term, not on type
    /// identity (a known defect, plan section 2.2).
    pub fn encode_default(&mut self, term: &Bound<'py, PyAny>) -> CodecResult<()> {
        let type_name = term.get_type().name()?;
        let type_name = type_name.to_cow()?;

        match type_name.as_ref() {
            "int" => self.write_int(term),
            "float" => {
                let val: f64 = term.extract()?;
                if !val.is_finite() {
                    return Err(CodecError::NonFiniteFloat { f: val });
                }
                self.write_float(val)
            }
            "list" => {
                let as_list = term.cast::<PyList>()?;
                // `[]` is NIL_EXT alone, as OTP writes it
                if !as_list.is_empty() {
                    self.write_list_no_tail(as_list)?;
                }
                self.data.push(consts::TAG_NIL_EXT);
                Ok(())
            }
            "tuple" => {
                let as_tup = term.cast::<PyTuple>()?;
                self.write_tuple(as_tup)
            }
            "dict" => {
                let as_dict = term.cast::<PyDict>()?;
                self.write_dict(as_dict)
            }
            "Atom" => self.write_atom(term),
            "StrictAtom" => self.write_atom(term),
            "str" => {
                let as_str = term.cast::<PyString>()?;
                self.write_str(as_str)
            }
            "bool" => {
                let val: bool = term.extract()?;
                self.write_atom_from_cow(if val {
                    Cow::from("true")
                } else {
                    Cow::from("false")
                })
            }
            "NoneType" => self.write_atom_from_cow(Cow::from("undefined")),
            "ImproperList" => {
                let elements0 = term.getattr("_elements")?;
                let elements = elements0.cast::<PyList>()?;
                let tail = term.getattr("_tail")?;
                // `[... | T]` with no elements is `T` itself
                if !elements.is_empty() {
                    self.write_list_no_tail(elements)?;
                }
                self.encode(&tail)
            }
            "Pid" => self.write_pid(term),
            "Reference" => self.write_ref(term),
            "bytes" => {
                let py_bytes = term.cast::<PyBytes>()?;
                self.write_binary(py_bytes)
            }
            "BitString" => self.write_bitstring(term),
            _other => self.write_unknown_object(term),
        }
    }

    /// For unknown object, check whether catch_all is set, encode what it returns.
    /// If no catch_all was set, check whether object has ``__etf__(self)`` member.
    /// Else encode object as Tuple(b'ClassName', Dict(b'field', values)) trying
    ///   to avoid circular loops.
    fn write_unknown_object(&mut self, py_term: &Bound<'py, PyAny>) -> CodecResult<()> {
        match &self.catch_all {
            Some(h1) => {
                let repr1 = h1.call1((py_term,))?;
                self.encode(&repr1)
            }
            None => match py_term.getattr("__etf__") {
                Ok(h2) => {
                    let repr2 = h2.call0()?;
                    self.encode(&repr2)
                }
                Err(_) => self.write_generic_unknown_object(py_term),
            },
        }
    }

    fn write_generic_unknown_object(&mut self, py_term: &Bound<'py, PyAny>) -> CodecResult<()> {
        let py_fn = match &self.cached_generic_serialize_fn {
            Some(a) => a.clone(),
            None => {
                let pyimpl_m = self.py.import("term.py_codec_impl")?;
                let generic_fn = pyimpl_m.getattr("generic_serialize_object")?;
                self.cached_generic_serialize_fn = Some(generic_fn.clone());
                generic_fn
            }
        };
        let result_pair = py_fn.call1((py_term, self.py.None()))?;
        let py_pair = result_pair.cast::<PyTuple>()?;
        let result = py_pair.get_item(0)?;
        self.encode(&result)
    }

    /// Writes list tag with elements, but no tail element (NIL or other). Ensure
    /// that the calling code is writing either a NIL or a tail term.
    #[inline]
    fn write_list_no_tail(&mut self, list: &Bound<'py, PyList>) -> CodecResult<()> {
        let size = list.len();
        self.data.push(consts::TAG_LIST_EXT);
        self.data
            .push_u32(u32::try_from(size).map_err(|_| CodecError::TooLong { size })?);
        for i in 0..size {
            let item = list.get_item(i)?;
            self.encode(&item)?;
        }
        Ok(())
    }

    /// Writes a tuple: SMALL_TUPLE_EXT up to 255 elements, else LARGE_TUPLE_EXT.
    #[inline]
    fn write_tuple(&mut self, tup: &Bound<'py, PyTuple>) -> CodecResult<()> {
        let size = tup.len();
        if let Ok(small) = u8::try_from(size) {
            self.data.push(consts::TAG_SMALL_TUPLE_EXT);
            self.data.push(small);
        } else {
            self.data.push(consts::TAG_LARGE_TUPLE_EXT);
            self.data
                .push_u32(u32::try_from(size).map_err(|_| CodecError::TooLong { size })?);
        }

        for i in 0..size {
            let item = tup.get_item(i)?;
            self.encode(&item)?;
        }
        Ok(())
    }

    /// Writes Erlang map from Python dict.
    #[inline]
    fn write_dict(&mut self, py_dict: &Bound<'py, PyDict>) -> CodecResult<()> {
        // `items()` is a snapshot list, so a hook that changes the dict while
        // it is encoded cannot break the iteration.
        let items = py_dict.items();
        self.data.push(consts::TAG_MAP_EXT);
        self.data.push_u32(items.len() as u32);

        for item in items.iter() {
            let (py_key, py_value): (Bound<'py, PyAny>, Bound<'py, PyAny>) = item.extract()?;
            self.encode(&py_key)?;
            self.encode(&py_value)?;
        }
        Ok(())
    }

    /// Writes an integer: SMALL_INTEGER_EXT for 0..255, INTEGER_EXT for a
    /// signed 32-bit value, otherwise a bignum.
    #[inline]
    fn write_int(&mut self, val: &Bound<'py, PyAny>) -> CodecResult<()> {
        match val.extract::<i64>() {
            Ok(v) => {
                self.write_i64(v);
                Ok(())
            }
            // Does not fit 64 bits: let Python produce the magnitude bytes
            Err(_) => self.write_py_bignum(val),
        }
    }

    fn write_i64(&mut self, val: i64) {
        if let Ok(small) = u8::try_from(val) {
            self.data.push(consts::TAG_SMALL_UINT);
            self.data.push(small);
        } else if let Ok(v32) = i32::try_from(val) {
            self.data.push(consts::TAG_INT);
            self.data.push_i32(v32);
        } else {
            self.data
                .extend(small_big_bytes(val.unsigned_abs(), val < 0));
        }
    }

    /// A bignum beyond 64 bits: SMALL_BIG_EXT up to 255 magnitude bytes, else
    /// LARGE_BIG_EXT; little-endian magnitude without leading zero bytes.
    fn write_py_bignum(&mut self, val: &Bound<'py, PyAny>) -> CodecResult<()> {
        let negative: bool = val.lt(0)?;
        let magnitude = if negative { val.neg()? } else { val.clone() };
        let bits: u64 = magnitude.call_method0("bit_length")?.extract()?;
        let size = bits.div_ceil(8);
        if let Ok(small) = u8::try_from(size) {
            self.data.push(consts::TAG_SMALL_BIG_EXT);
            self.data.push(small);
        } else {
            let large = u32::try_from(size).map_err(|_| CodecError::IntegerTooLarge)?;
            self.data.push(consts::TAG_LARGE_BIG_EXT);
            self.data.push_u32(large);
        }
        self.data.push(u8::from(negative));
        let b = magnitude.call_method1("to_bytes", (size, "little"))?;
        self.data.extend_from_slice(b.cast::<PyBytes>()?.as_bytes());
        Ok(())
    }

    #[inline]
    fn write_float(&mut self, val: f64) -> CodecResult<()> {
        self.data.push(consts::TAG_NEW_FLOAT_EXT);
        self.data.push_f64(val);
        Ok(())
    }

    /// Encode a UTF-8 Atom
    #[inline]
    fn write_atom(&mut self, py_atom: &Bound<'py, PyAny>) -> CodecResult<()> {
        let py_text = py_atom.cast::<PyString>()?;
        let text = py_text.to_cow()?;
        self.write_atom_from_cow(text)
    }

    /// Helper which writes an atom from a PyString's Copy-on-write string.
    /// Chooses the tag by byte length, not character count (TERM-15).
    fn write_atom_from_cow(&mut self, text: Cow<str>) -> CodecResult<()> {
        let byte_array: &[u8] = text.as_bytes();
        let str_byte_length: usize = byte_array.len();

        if str_byte_length <= u8::MAX as usize {
            self.data.push(consts::TAG_SMALL_ATOM_UTF8_EXT);
            self.data.push(str_byte_length as u8); // 8bit length
            self.data.extend_from_slice(byte_array); // string content
        } else if str_byte_length <= u16::MAX as usize {
            self.data.push(consts::TAG_ATOM_UTF8_EXT);
            self.data.push_u16(str_byte_length as u16); // 16bit length
            self.data.extend_from_slice(byte_array); // string content
        } else {
            return Err(CodecError::AtomTooLong);
        }

        Ok(())
    }

    /// Encode a string, which is a list of code points: STRING_EXT (one
    /// Latin-1 byte per character) when every code point is below 256 and
    /// there are at most 65535 of them, else LIST_EXT of integers; `""` is
    /// NIL_EXT.
    #[inline]
    fn write_str(&mut self, py_str: &Bound<'py, PyString>) -> CodecResult<()> {
        let text = py_str.to_cow()?;
        if text.is_empty() {
            self.data.push(consts::TAG_NIL_EXT);
            return Ok(());
        }
        let size = text.chars().count();
        let latin1 = text.chars().all(|ch| u8::try_from(ch).is_ok());

        match u16::try_from(size) {
            Ok(short) if latin1 => {
                self.data.push(consts::TAG_STRING_EXT);
                self.data.push_u16(short);
                self.data
                    .extend(text.chars().filter_map(|ch| u8::try_from(ch).ok()));
            }
            _ => {
                self.data.push(consts::TAG_LIST_EXT);
                self.data
                    .push_u32(u32::try_from(size).map_err(|_| CodecError::TooLong { size })?);
                for ch in text.chars() {
                    self.write_i64(i64::from(u32::from(ch)));
                }
                self.data.push(consts::TAG_NIL_EXT);
            }
        }
        Ok(())
    }

    /// Encode a Pid
    #[inline]
    fn write_pid(&mut self, py_pid: &Bound<'py, PyAny>) -> CodecResult<()> {
        let node_name = py_pid.getattr("node_name_")?;
        let node_name = node_name.cast::<PyString>()?;

        let id: u32 = py_pid.getattr("id_")?.extract()?;
        let serial: u32 = py_pid.getattr("serial_")?.extract()?;
        let creation: u32 = py_pid.getattr("creation_")?.extract()?;

        self.data.push(consts::TAG_NEW_PID_EXT);
        self.write_atom_from_cow(node_name.to_cow()?)?;
        self.data.push_u32(id);
        self.data.push_u32(serial);
        self.data.push_u32(creation);

        Ok(())
    }

    /// Encode a Reference
    #[inline]
    fn write_ref(&mut self, py_ref: &Bound<'py, PyAny>) -> CodecResult<()> {
        let node_name = py_ref.getattr("node_name_")?;
        let node_name = node_name.cast::<PyString>()?;

        let py_id = py_ref.getattr("id_")?;
        let id = py_id.cast::<PyBytes>()?.as_bytes();

        let creation: u32 = py_ref.getattr("creation_")?.extract()?;

        self.data.push(consts::TAG_NEWER_REF_EXT);
        self.data.push_u16((id.len() / 4) as u16);
        self.write_atom_from_cow(node_name.to_cow()?)?;
        self.data.push_u32(creation);
        self.data.extend_from_slice(id);

        Ok(())
    }

    /// Encode a binary (byte-string)
    #[inline]
    fn write_binary(&mut self, py_bytes: &Bound<'py, PyBytes>) -> CodecResult<()> {
        let data: &[u8] = py_bytes.as_bytes();
        self.data.push(consts::TAG_BINARY_EXT);
        self.data.push_u32(data.len() as u32);
        self.data.extend_from_slice(data);
        Ok(())
    }

    /// Encode a BitString: BIT_BINARY_EXT with the unused low bits of the
    /// last byte cleared; a whole last byte (8 bits) is a plain binary.
    #[inline]
    fn write_bitstring(&mut self, py_bits: &Bound<'py, PyAny>) -> CodecResult<()> {
        let py_value = py_bits.getattr("value_")?;
        let data: &[u8] = py_value.cast::<PyBytes>()?.as_bytes();
        let last_byte_bits: u8 = py_bits.getattr("last_byte_bits_")?.extract()?;
        let size =
            u32::try_from(data.len()).map_err(|_| CodecError::TooLong { size: data.len() })?;

        if last_byte_bits == 8 {
            self.data.push(consts::TAG_BINARY_EXT);
            self.data.push_u32(size);
            self.data.extend_from_slice(data);
            return Ok(());
        }
        helpers::check_bits(data.len(), last_byte_bits)?;
        self.data.push(consts::TAG_BIT_BINARY_EXT);
        self.data.push_u32(size);
        self.data.push(last_byte_bits);
        self.data
            .extend(helpers::mask_last_byte(data, last_byte_bits));
        Ok(())
    }
} // end impl

/// SMALL_BIG_EXT of a magnitude that fits 64 bits: tag, byte count, sign,
/// then the magnitude little-endian without leading zero bytes.
fn small_big_bytes(magnitude: u64, negative: bool) -> Vec<u8> {
    let le = magnitude.to_le_bytes();
    let n = le.len() - (magnitude.leading_zeros() / 8) as usize;
    let mut out = vec![consts::TAG_SMALL_BIG_EXT, n as u8, u8::from(negative)];
    out.extend(le.iter().take(n));
    out
}

#[cfg(test)]
mod tests {
    use super::small_big_bytes;

    #[test]
    fn small_big_has_no_leading_zero_bytes() {
        // 2^31 and 2^32-1 take 4 bytes, 2^32 five, as OTP writes them.
        assert_eq!(small_big_bytes(1 << 31, false), [110, 4, 0, 0, 0, 0, 128]);
        assert_eq!(
            small_big_bytes(u32::MAX.into(), true),
            [110, 4, 1, 255, 255, 255, 255]
        );
        assert_eq!(small_big_bytes(1 << 32, false), [110, 5, 0, 0, 0, 0, 0, 1]);
        assert_eq!(
            small_big_bytes(u64::MAX, false),
            [110, 8, 0, 255, 255, 255, 255, 255, 255, 255, 255]
        );
    }
}
