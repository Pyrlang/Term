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

use flate2::bufread::ZlibDecoder;
use pyo3::prelude::*;
use pyo3::types::{PyBool, PyBytes, PyDict, PyInt, PyList, PyTuple};
use pyo3::IntoPyObjectExt;
use std::borrow::Cow;
use std::io::Read;
use std::str;

use crate::reader::{Readable, Reader};

use super::consts;
use super::errors::{CodecError, CodecResult};
use super::helpers;
use super::helpers::{AtomRepresentation, ByteStringRepresentation};

pub struct Decoder<'py> {
    py: Python<'py>, // Python instance will live at least as long as Decoder
    atom_representation: AtomRepresentation,
    bytestring_repr: ByteStringRepresentation,

    pub decode_hook: Bound<'py, PyDict>,
    // The "atom_call" option: builds every atom from its text when set.
    atom_call: Option<Bound<'py, PyAny>>,
    cached_atom_pyclass: Option<Bound<'py, PyAny>>,
    // term.atom.Atom, for node names whatever the "atom" option says.
    cached_node_atom_pyclass: Option<Bound<'py, PyAny>>,
    cached_pid_pyclass: Option<Bound<'py, PyAny>>,
    cached_ref_pyclass: Option<Bound<'py, PyAny>>,
    cached_fun_pyclass: Option<Bound<'py, PyAny>>,
    cached_improper_list_pyclass: Option<Bound<'py, PyAny>>,
}

/// Return the cached Python class from `slot`, or import `module.name`, cache
/// it in `slot` and return it.
fn cached_class<'py>(
    py: Python<'py>,
    slot: &mut Option<Bound<'py, PyAny>>,
    module: &str,
    name: &str,
) -> PyResult<Bound<'py, PyAny>> {
    if let Some(cls) = slot {
        return Ok(cls.clone());
    }
    let cls = py.import(module)?.getattr(name)?;
    *slot = Some(cls.clone());
    Ok(cls)
}

impl<'py> Decoder<'py> {
    /// Create decoder instance. Parse options.
    pub fn new(py: Python<'py>, opts: &Bound<'py, PyAny>) -> CodecResult<Decoder<'py>> {
        // If opts is None, make it empty Dict, otherwise take it as PyDict
        let opts1 = helpers::maybe_dict(opts)?;
        let aopt = helpers::get_atom_opt(&opts1)?;
        let atom_call = match opts1.get_item("atom_call")? {
            Some(f) if f.is_none() => None,
            Some(f) if !f.is_callable() => {
                return Err(CodecError::BadOptions {
                    txt: "'atom_call' must be callable".to_string(),
                })
            }
            other => other,
        };
        let s8opt = helpers::get_byte_str_opt(&opts1)?;

        let decode_hook = match opts1.get_item("decode_hook")? {
            Some(h1) if h1.is_none() => PyDict::new(py),
            Some(h1) => match h1.cast_into::<PyDict>() {
                Ok(d) => d,
                Err(_) => {
                    return Err(CodecError::BadOptions {
                        txt: "'decode_hook' must be a dict".to_string(),
                    })
                }
            },
            None => PyDict::new(py),
        };

        Ok(Decoder {
            py,
            atom_representation: aopt,
            bytestring_repr: s8opt,
            decode_hook,
            atom_call,
            cached_atom_pyclass: None,
            cached_node_atom_pyclass: None,
            cached_pid_pyclass: None,
            cached_ref_pyclass: None,
            cached_fun_pyclass: None,
            cached_improper_list_pyclass: None,
        })
    }

    /// Decode one term and return the Python tuple (value, remaining bytes).
    pub fn decode_and_wrap(&mut self, reader: &mut Reader) -> CodecResult<Bound<'py, PyAny>> {
        let result = self.decode(reader)?;
        let tail = PyBytes::new(self.py, reader.rest());
        let result = PyTuple::new(self.py, [result, tail.into_any()])?;
        Ok(result.into_any())
    }

    /// Strip 131 byte header and uncompress if the data was compressed.
    /// Return: PyTuple(PyObject, Bytes) or CodecError
    pub fn decode_with_131tag(&mut self, reader: &mut Reader) -> CodecResult<Bound<'py, PyAny>> {
        let pre_tag = reader.read_u8()?;
        if pre_tag != consts::ETF_VERSION_TAG {
            return Err(CodecError::UnsupportedETFVersion);
        }

        // Read first byte of term, it might be a compressed term marker
        let tag = reader.peek()?;
        if tag == consts::TAG_COMPRESSED {
            reader.read_u8()?;
            let decomp_size = reader.read_u32()? as usize;

            // The declared size is not checked against any limit yet (TERM-09).
            let mut decompressed = vec![0u8; decomp_size];
            let mut d = ZlibDecoder::new(reader);
            d.read_exact(&mut decompressed)?;
            if d.total_out() != decomp_size as u64 {
                return Err(CodecError::CompressedSizeMismatch);
            }

            let mut decompressed_reader = (&decompressed).into();
            self.decode_and_wrap(&mut decompressed_reader)
        } else {
            // Second byte was not consumed, so restart parsing from the second byte
            self.decode_and_wrap(reader)
        }
    }

    /// Decodes binary External Term Format (ETF) into a Python structure.
    /// Returns: Decoded object or CodecError
    pub fn decode(&mut self, reader: &mut Reader) -> CodecResult<Bound<'py, PyAny>> {
        let tag = reader.read_u8()?;
        let value = match tag {
            consts::TAG_ATOM_EXT => self.parse_latin1_atom::<u16>(reader),
            consts::TAG_ATOM_UTF8_EXT => self.parse_utf8_atom::<u16>(reader),
            consts::TAG_SMALL_ATOM_EXT => self.parse_latin1_atom::<u8>(reader),
            consts::TAG_SMALL_ATOM_UTF8_EXT => self.parse_utf8_atom::<u8>(reader),
            consts::TAG_BINARY_EXT => self.parse_binary(reader),
            consts::TAG_BIT_BINARY_EXT => self.parse_bitstring(reader),
            consts::TAG_NIL_EXT => Ok(PyList::empty(self.py).into_any()),
            consts::TAG_LIST_EXT => self.parse_list(reader),
            consts::TAG_STRING_EXT => self.parse_string(reader), // 16-bit sz bytestr
            consts::TAG_SMALL_UINT => self.parse_number::<u8>(reader),
            consts::TAG_INT => self.parse_number::<i32>(reader),
            consts::TAG_SMALL_BIG_EXT => {
                let size = reader.read_u8()? as usize;
                let sign = reader.read_u8()?;
                self.parse_arbitrary_length_int(reader, size, sign)
            }
            consts::TAG_LARGE_BIG_EXT => {
                let size = reader.read_u32()? as usize;
                let sign = reader.read_u8()?;
                self.parse_arbitrary_length_int(reader, size, sign)
            }
            consts::TAG_NEW_FLOAT_EXT => self.parse_number::<f64>(reader),
            consts::TAG_MAP_EXT => self.parse_map(reader),
            consts::TAG_SMALL_TUPLE_EXT => {
                let arity = reader.read_u8()? as usize;
                self.parse_tuple(reader, arity)
            }
            consts::TAG_LARGE_TUPLE_EXT => {
                let arity = reader.read_u32()? as usize;
                self.parse_tuple(reader, arity)
            }
            consts::TAG_PID_EXT => self.parse_pid(reader),
            consts::TAG_NEW_PID_EXT => self.parse_new_pid(reader),
            consts::TAG_NEW_REF_EXT => self.parse_ref(reader),
            consts::TAG_NEWER_REF_EXT => self.parse_newer_ref(reader),
            consts::TAG_NEW_FUN_EXT => self.parse_fun(reader),
            _ => Err(CodecError::UnknownTermTagByte { b: tag }),
        }?;

        // If the type name (`__name__`) of the value is in decode_hook, call it
        if self.decode_hook.is_empty() {
            return Ok(value);
        }
        let type_name = value.get_type().name()?;
        match self.decode_hook.get_item(type_name)? {
            Some(h1) => Ok(h1.call1((value,))?),
            None => Ok(value),
        }
    }

    /// Return cached value of atom class used for decoding. Otherwise if not
    /// found - import and cache it locally.
    fn get_atom_pyclass(&mut self) -> PyResult<Bound<'py, PyAny>> {
        let name = match self.atom_representation {
            AtomRepresentation::TermStrictAtom => "StrictAtom",
            _ => "Atom",
        };
        cached_class(self.py, &mut self.cached_atom_pyclass, "term.atom", name)
    }

    #[inline]
    fn parse_number<T>(&self, in_bytes: &mut Reader) -> CodecResult<Bound<'py, PyAny>>
    where
        T: IntoPyObject<'py> + Readable,
    {
        let val = in_bytes.read_with::<T>()?;
        Ok(val.into_bound_py_any(self.py)?)
    }

    /// Parses bytes after Atom tag (100) or Atom Utf8 (118)
    /// Returns: string | bytes | Atom object
    #[inline]
    fn parse_utf8_atom<T>(&mut self, reader: &mut Reader) -> CodecResult<Bound<'py, PyAny>>
    where
        usize: std::convert::From<T>,
        T: Readable,
    {
        let txt = read_utf8_text::<T>(reader)?;
        self.create_atom(&txt)
    }

    #[inline]
    fn parse_latin1_atom<T>(&mut self, reader: &mut Reader) -> CodecResult<Bound<'py, PyAny>>
    where
        usize: std::convert::From<T>,
        T: Readable,
    {
        let txt = read_latin1_text::<T>(reader)?;
        self.create_atom(&txt)
    }

    #[inline]
    fn create_atom(&mut self, txt: &str) -> CodecResult<Bound<'py, PyAny>> {
        match txt {
            "true" => return Ok(PyBool::new(self.py, true).to_owned().into_any()),
            "false" => return Ok(PyBool::new(self.py, false).to_owned().into_any()),
            "undefined" => return Ok(self.py.None().into_bound(self.py)),
            _ => {}
        }

        if let Some(f) = &self.atom_call {
            return Ok(f.call1((txt,))?);
        }
        match self.atom_representation {
            AtomRepresentation::Bytes => Ok(PyBytes::new(self.py, txt.as_bytes()).into_any()),
            AtomRepresentation::Str => Ok(txt.into_bound_py_any(self.py)?),
            _ => {
                // Construct Atom object (Note: performance cost)
                let atom_cls = self.get_atom_pyclass()?;
                Ok(atom_cls.call1((txt,))?)
            }
        }
    }

    #[inline]
    fn parse_arbitrary_length_int(
        &self,
        reader: &mut Reader,
        size: usize,
        sign: u8,
    ) -> CodecResult<Bound<'py, PyAny>> {
        let bin = reader.read(size)?;
        let data = PyBytes::new(self.py, bin);
        let py_int = self.py.get_type::<PyInt>();
        let val = py_int.call_method1("from_bytes", (data, "little"))?;
        let val = if sign == 0 { val } else { val.mul(-1)? };
        Ok(val)
    }

    /// Given input _after_ binary tag, parse remaining bytes
    #[inline]
    fn parse_binary(&self, in_bytes: &mut Reader) -> CodecResult<Bound<'py, PyAny>> {
        let sz = in_bytes.read_u32()? as usize;
        let bin = in_bytes.read(sz)?;
        Ok(PyBytes::new(self.py, bin).into_any())
    }

    /// Given input _after_ bit-string tag, parse remaining bytes and bit-count.
    /// Returns the tuple (bytes, last_byte_bits); TERM-20 adds a BitString option.
    #[inline]
    fn parse_bitstring(&mut self, in_bytes: &mut Reader) -> CodecResult<Bound<'py, PyAny>> {
        let sz = in_bytes.read_u32()? as usize;
        let last_byte_bits: u8 = in_bytes.read_u8()?;
        let bin = in_bytes.read(sz)?;
        let py_bytes = PyBytes::new(self.py, bin).into_any();
        let py_bits = last_byte_bits.into_bound_py_any(self.py)?;
        Ok(PyTuple::new(self.py, [py_bytes, py_bits])?.into_any())
    }

    /// Given input _after_ string tag, parse remaining bytes as a UTF-8 string
    /// (Latin-1 is correct; TERM-07 fixes this).
    #[inline]
    fn parse_string(&self, reader: &mut Reader) -> CodecResult<Bound<'py, PyAny>> {
        let sz = reader.read_u16()? as usize;
        let arr = reader.read(sz)?;
        let result = match self.bytestring_repr {
            ByteStringRepresentation::Str => str::from_utf8(arr)?.into_bound_py_any(self.py)?,
            ByteStringRepresentation::Bytes => PyBytes::new(self.py, arr).into_any(),
            ByteStringRepresentation::IntList => {
                PyList::new(self.py, arr.iter().copied())?.into_any()
            }
        };
        Ok(result)
    }

    /// Given input _after_ the list tag, parse the list elements and tail
    #[inline]
    fn parse_list(&mut self, reader: &mut Reader) -> CodecResult<Bound<'py, PyAny>> {
        let sz = reader.read_u32()? as usize;

        // Pre-allocated from the length field; TERM-09 bounds this.
        let mut lst = Vec::<Bound<'py, PyAny>>::with_capacity(sz);

        // Read list elements, one by one
        for _i in 0..sz {
            lst.push(self.decode(reader)?);
        }

        let py_lst = PyList::new(self.py, lst)?;

        // Check whether last element is a NIL, or something else
        if reader.peek()? == consts::TAG_NIL_EXT {
            reader.read_u8()?;
            // We are looking at a proper list, so just return the result
            Ok(py_lst.into_any())
        } else {
            // We are looking at an improper list
            let tail_val = self.decode(reader)?;
            if sz == 0 {
                // A zero-length list is its tail: <<108,0,0,0,0,97,42>> is 42
                // (binary_SUITE:robustness), as in the Python codec.
                return Ok(tail_val);
            }
            let improper_list_cls = cached_class(
                self.py,
                &mut self.cached_improper_list_pyclass,
                "term.list",
                "ImproperList",
            )?;
            Ok(improper_list_cls.call1((py_lst, tail_val))?)
        }
    }

    /// Given input _after_ the TAG_MAP_EXT byte, parse map key/value pairs.
    #[inline]
    fn parse_map(&mut self, reader: &mut Reader) -> CodecResult<Bound<'py, PyAny>> {
        let arity = reader.read_u32()? as usize;

        let result = PyDict::new(self.py);

        // Read key/value pairs two at a time
        for _i in 0..arity {
            let py_key = self.decode(reader)?;
            let py_val = self.decode(reader)?;
            result.set_item(py_key, py_val)?;
        }

        Ok(result.into_any())
    }

    /// Given input _after_ the TAG_SMALL_TUPLE_EXT or the TAG_TUPLE_EXT byte,
    /// tuple elements into a vector and create Python tuple.
    #[inline]
    fn parse_tuple(&mut self, reader: &mut Reader, arity: usize) -> CodecResult<Bound<'py, PyAny>> {
        // Pre-allocated from the length field; TERM-09 bounds this.
        let mut result = Vec::<Bound<'py, PyAny>>::with_capacity(arity);

        // Read values one by one
        for _i in 0..arity {
            result.push(self.decode(reader)?);
        }

        Ok(PyTuple::new(self.py, result)?.into_any())
    }

    /// Decode the node name of a pid or reference: always a `term.atom.Atom`,
    /// whatever the options and hooks say. Anything but an atom is an error.
    fn decode_node_name(&mut self, reader: &mut Reader) -> CodecResult<Bound<'py, PyAny>> {
        let tag = reader.read_u8()?;
        let txt = match tag {
            consts::TAG_ATOM_EXT => read_latin1_text::<u16>(reader)?,
            consts::TAG_ATOM_UTF8_EXT => read_utf8_text::<u16>(reader)?,
            consts::TAG_SMALL_ATOM_EXT => read_latin1_text::<u8>(reader)?,
            consts::TAG_SMALL_ATOM_UTF8_EXT => read_utf8_text::<u8>(reader)?,
            _ => return Err(CodecError::NodeNotAnAtom { b: tag }),
        };
        let atom_cls = cached_class(
            self.py,
            &mut self.cached_node_atom_pyclass,
            "term.atom",
            "Atom",
        )?;
        Ok(atom_cls.call1((txt,))?)
    }

    /// Given input _after_ the PID tag byte, parse an external pid
    #[inline]
    fn parse_pid(&mut self, reader: &mut Reader) -> CodecResult<Bound<'py, PyAny>> {
        let node = self.decode_node_name(reader)?;

        let id: u32 = reader.read_u32()?;
        let serial: u32 = reader.read_u32()?;
        let creation: u8 = reader.read_u8()?;

        let pid_cls = cached_class(self.py, &mut self.cached_pid_pyclass, "term.pid", "Pid")?;
        Ok(pid_cls.call1((node, id, serial, creation))?)
    }

    /// Given input _after_ the NEW_PID tag byte, parse an external pid
    #[inline]
    fn parse_new_pid(&mut self, reader: &mut Reader) -> CodecResult<Bound<'py, PyAny>> {
        let node = self.decode_node_name(reader)?;

        let id: u32 = reader.read_u32()?;
        let serial: u32 = reader.read_u32()?;
        let creation: u32 = reader.read_u32()?;

        let pid_cls = cached_class(self.py, &mut self.cached_pid_pyclass, "term.pid", "Pid")?;
        Ok(pid_cls.call1((node, id, serial, creation))?)
    }

    /// Given input _after_ the Reference tag byte, parse an external reference
    #[inline]
    fn parse_ref(&mut self, reader: &mut Reader) -> CodecResult<Bound<'py, PyAny>> {
        let term_len = reader.read_u16()? as usize;
        let node = self.decode_node_name(reader)?;

        let creation: u8 = reader.read_u8()?;

        let id: &[u8] = reader.read(term_len * 4)?;
        let bytes_id = PyBytes::new(self.py, id);

        let ref_cls = cached_class(
            self.py,
            &mut self.cached_ref_pyclass,
            "term.reference",
            "Reference",
        )?;
        Ok(ref_cls.call1((node, creation, bytes_id))?)
    }

    /// Given input _after_ the Newer Reference tag byte, parse an external reference
    #[inline]
    fn parse_newer_ref(&mut self, reader: &mut Reader) -> CodecResult<Bound<'py, PyAny>> {
        let term_len = reader.read_u16()? as usize;
        let node = self.decode_node_name(reader)?;

        let creation: u32 = reader.read_u32()?;

        // Any length is accepted for now; TERM-11 limits it to 1..5 words.
        let id: &[u8] = reader.read(term_len * 4)?;
        let bytes_id = PyBytes::new(self.py, id);

        let ref_cls = cached_class(
            self.py,
            &mut self.cached_ref_pyclass,
            "term.reference",
            "Reference",
        )?;
        Ok(ref_cls.call1((node, creation, bytes_id))?)
    }

    /// Given input _after_ the Fun tag byte, parse a fun (not useful in Python
    /// but we store all parts of it and can reconstruct it, if it will be sent out)
    #[inline]
    fn parse_fun(&mut self, reader: &mut Reader) -> CodecResult<Bound<'py, PyAny>> {
        let _size = reader.read_u32()?;
        let arity = reader.read_u8()? as usize;

        let uniq_md5 = PyBytes::new(self.py, reader.read(16)?);

        let index = reader.read_u32()?;
        let num_free = reader.read_u32()?;

        let module = self.decode(reader)?;
        let old_index = self.decode(reader)?;
        let old_uniq = self.decode(reader)?;
        let pid = self.decode(reader)?;

        // Decode num_free free variables following after pid
        let mut frozen_vars = Vec::<Bound<'py, PyAny>>::new();
        for _i in 0..num_free {
            frozen_vars.push(self.decode(reader)?);
        }
        let py_frozen_vars = PyTuple::new(self.py, frozen_vars)?;

        let fun_cls = cached_class(self.py, &mut self.cached_fun_pyclass, "term.fun", "Fun")?;
        let py_fun = fun_cls.call1((
            module,
            arity,
            pid,
            index,
            uniq_md5,
            old_index,
            old_uniq,
            py_frozen_vars,
        ))?;
        Ok(py_fun)
    }
}
// end impl

/// Read the length (a `T`) and the UTF-8 text of an atom.
fn read_utf8_text<'a, T>(reader: &mut Reader<'a>) -> CodecResult<Cow<'a, str>>
where
    usize: std::convert::From<T>,
    T: Readable,
{
    let sz = reader.read_with::<T>()?.into();
    Ok(Cow::Borrowed(str::from_utf8(reader.read(sz)?)?))
}

/// Read the length (a `T`) and the Latin-1 text of an atom.
fn read_latin1_text<'a, T>(reader: &mut Reader<'a>) -> CodecResult<Cow<'a, str>>
where
    usize: std::convert::From<T>,
    T: Readable,
{
    let sz = reader.read_with::<T>()?.into();
    let buf = reader.read(sz)?;
    if buf.is_ascii() {
        Ok(Cow::Borrowed(str::from_utf8(buf)?))
    } else {
        Ok(Cow::Owned(buf.iter().map(|c| char::from(*c)).collect()))
    }
}
