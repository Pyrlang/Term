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

use compress::zlib;
use cpython::*;
use std::io::{BufReader, Read};
use std::str;

use crate::reader::{Readable, Reader};

use super::consts;
use super::errors::*;
use super::helpers;
use super::helpers::{AtomRepresentation, ByteStringRepresentation};

pub struct Decoder<'a> {
    py: Python<'a>, // Python instance will live at least as long as Decoder
    atom_representation: AtomRepresentation,
    bytestring_repr: ByteStringRepresentation,

    pub decode_hook: PyDict,
    cached_atom_pyclass: Option<PyObject>,
    cached_pid_pyclass: Option<PyObject>,
    cached_ref_pyclass: Option<PyObject>,
    cached_fun_pyclass: Option<PyObject>,
    cached_improper_list_pyclass: Option<PyObject>,
}

impl<'a> Decoder<'a> {
    /// Create decoder instance. Parse options.
    pub fn new(py: Python, opts: PyObject) -> CodecResult<Decoder> {
        // If opts is None, make it empty Dict, otherwise take it as PyDict
        let opts1 = helpers::maybe_dict(py, opts);
        let aopt = helpers::get_atom_opt(py, &opts1)?;
        let cached_atom_pyclass = opts1.get_item(py, "atom_call");
        let s8opt = helpers::get_byte_str_opt(py, &opts1)?;

        let decode_hook = match opts1.get_item(py, "decode_hook") {
            Some(ref h1) => PyDict::extract(py, h1)?,
            None => PyDict::new(py),
        };

        Ok(Decoder {
            py,
            atom_representation: aopt,
            bytestring_repr: s8opt,
            decode_hook,
            cached_atom_pyclass,
            cached_pid_pyclass: None,
            cached_ref_pyclass: None,
            cached_fun_pyclass: None,
            cached_improper_list_pyclass: None,
            //      cached_bitstr_pyclass: None,
        })
    }

    pub fn decode_and_wrap(&mut self, reader: &mut Reader) -> Result<PyObject, CodecError> {
        let result = self.decode(reader)?;
        let tail = PyBytes::new(self.py, reader.rest());
        let result = PyTuple::new(self.py, &[result, tail.into_object()]);
        Ok(result.into_object())
    }

    /// Strip 131 byte header and uncompress if the data was compressed.
    /// Return: PyTuple(PyObject, Bytes) or CodecError
    pub fn decode_with_131tag(&mut self, reader: &mut Reader) -> CodecResult<PyObject> {
        let pre_tag = reader.read_u8()?;
        if pre_tag != consts::ETF_VERSION_TAG {
            return Err(CodecError::UnsupportedETFVersion);
        }

        // Read first byte of term, it might be a compressed term marker
        let tag = reader.peek()?;
        if tag == consts::TAG_COMPRESSED {
            reader.read_u8().unwrap();
            let decomp_size = reader.read_u32()? as usize;

            let mut decompressed = Vec::<u8>::with_capacity(decomp_size);
            let mut d = zlib::Decoder::new(reader);
            d.read_to_end(&mut decompressed).unwrap();
            if decompressed.len() != decomp_size as usize {
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
    /// Returns: (Decoded object, remaining bytes) or CodecError
    pub fn decode(&mut self, reader: &mut Reader) -> CodecResult<PyObject> {
        let tag = reader.read_u8()?;
        let result = match tag {
            consts::TAG_ATOM_EXT => self.parse_latin1_atom::<u16>(reader),
            consts::TAG_ATOM_UTF8_EXT => self.parse_utf8_atom::<u16>(reader),
            consts::TAG_SMALL_ATOM_EXT => self.parse_latin1_atom::<u8>(reader),
            consts::TAG_SMALL_ATOM_UTF8_EXT => self.parse_utf8_atom::<u8>(reader),
            consts::TAG_BINARY_EXT => self.parse_binary(reader),
            consts::TAG_BIT_BINARY_EXT => self.parse_bitstring(reader),
            consts::TAG_NIL_EXT => {
                let empty_list = PyList::new(self.py, &[]);
                Ok(empty_list.into_object())
            }
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
        };

        match result {
            Ok(value) => {
                // if type_name_ref is in decode_hook, call it
                let type_name = value.get_type(self.py).name(self.py).into_owned();
                let type_name_ref: &str = type_name.as_ref();
                match &self.decode_hook.get_item(self.py, type_name_ref) {
                    Some(ref h1) => {
                        let repr1 = h1.call(self.py, (value,), None)?;
                        Ok(repr1)
                    }
                    None => Ok(value),
                }
            }
            Err(x) => Err(x),
        }
    }

    /// Return cached value of atom class used for decoding. Otherwise if not
    /// found - import and cache it locally.
    fn get_atom_pyclass(&mut self) -> PyObject {
        match &self.cached_atom_pyclass {
            Some(ref a) => a.clone_ref(self.py),
            None => {
                let atom_m = self.py.import("term.atom").unwrap();
                let atom_cls = match &self.atom_representation {
                    AtomRepresentation::TermStrictAtom => {
                        atom_m.get(self.py, "StrictAtom").unwrap()
                    }
                    _ => atom_m.get(self.py, "Atom").unwrap(),
                };

                self.cached_atom_pyclass = Some(atom_cls.clone_ref(self.py));
                atom_cls
            }
        }
    }

    //  /// Return cached value of BitString class used for decoding. Otherwise if not
    //  /// found - import and cache it locally.
    //  fn get_bitstr_pyclass(&mut self) -> PyObject {
    //    match &self.cached_bitstr_pyclass {
    //      Some(ref a) => a.clone_ref(self.py),
    //      None => {
    //        let bitstr_m = self.py.import("term.bitstring").unwrap();
    //        let bitstr_cls = bitstr_m.get(self.py, "BitString").unwrap();
    //        self.cached_bitstr_pyclass = Some(bitstr_cls.clone_ref(self.py));
    //        bitstr_cls
    //      },
    //    }
    //  }

    /// Return cached value of Pid class used for decoding. Otherwise if not
    /// found - import and cache it locally.
    fn get_pid_pyclass(&mut self) -> PyObject {
        match &self.cached_pid_pyclass {
            Some(ref a) => a.clone_ref(self.py),
            None => {
                let pid_m = self.py.import("term.pid").unwrap();
                let pid_cls = pid_m.get(self.py, "Pid").unwrap();
                self.cached_pid_pyclass = Some(pid_cls.clone_ref(self.py));
                pid_cls
            }
        }
    }

    /// Return cached value of Reference class used for decoding. Otherwise if not
    /// found - import and cache it locally.
    fn get_ref_pyclass(&mut self) -> PyObject {
        match &self.cached_ref_pyclass {
            Some(ref a) => a.clone_ref(self.py),
            None => {
                let ref_m = self.py.import("term.reference").unwrap();
                let ref_cls = ref_m.get(self.py, "Reference").unwrap();
                self.cached_ref_pyclass = Some(ref_cls.clone_ref(self.py));
                ref_cls
            }
        }
    }

    /// Return cached value of Fun class used for decoding. Otherwise if not
    /// found - import and cache it locally.
    fn get_fun_pyclass(&mut self) -> PyObject {
        match &self.cached_fun_pyclass {
            Some(ref a) => a.clone_ref(self.py),
            None => {
                let fun_m = self.py.import("term.fun").unwrap();
                let fun_cls = fun_m.get(self.py, "Fun").unwrap();
                self.cached_fun_pyclass = Some(fun_cls.clone_ref(self.py));
                fun_cls
            }
        }
    }

    fn get_improper_list_pyclass(&mut self) -> PyObject {
        match &self.cached_improper_list_pyclass {
            Some(ref l) => l.clone_ref(self.py),
            None => {
                let list_m = self.py.import("term.list").unwrap();
                let improper_list_cls = list_m.get(self.py, "ImproperList").unwrap();
                self.cached_improper_list_pyclass = Some(improper_list_cls.clone_ref(self.py));
                improper_list_cls
            }
        }
    }

    #[inline]
    fn parse_number<'inp, T>(&self, in_bytes: &mut Reader<'inp>) -> CodecResult<PyObject>
    where
        T: ToPyObject + Readable,
    {
        let val = in_bytes.read_with::<T>()?;
        let py_val = val.to_py_object(self.py);
        Ok(py_val.into_object())
    }

    //  #[inline]
    //  fn parse_bin_float<'inp>(&self, in_bytes: &'inp [u8]) -> CodecResult<(PyObject, &'inp [u8])>
    //  {
    //    let val = in_bytes[1];
    //    let py_val = val.to_py_object(self.py);
    //    Ok((py_val.into_object(), &in_bytes[2..]))
    //  }

    /// Parses bytes after Atom tag (100) or Atom Utf8 (118)
    /// Returns: Tuple (string | bytes | Atom object, remaining bytes)
    #[inline]
    fn parse_utf8_atom<T>(&mut self, reader: &mut Reader) -> CodecResult<PyObject>
    where
        usize: std::convert::From<T>,
        T: Readable,
    {
        let sz = reader.read_with::<T>()?.into();
        let txt = str::from_utf8(reader.read(sz)?)?;

        let result = self.create_atom(txt)?.into_object();
        Ok(result)
    }

    #[inline]
    fn parse_latin1_atom<T>(&mut self, reader: &mut Reader) -> CodecResult<PyObject>
    where
        usize: std::convert::From<T>,
        T: Readable,
    {
        let sz = reader.read_with::<T>()?.into();
        let buf = reader.read(sz)?;
        let result = if buf.is_ascii() {
            let txt = unsafe { str::from_utf8_unchecked(buf) };
            self.create_atom(txt)?.into_object()
        } else {
            let txt = buf
                .iter()
                .map(|c| char::from_u32(*c as u32).unwrap())
                .collect::<String>();
            self.create_atom(&txt)?.into_object()
        };

        Ok(result)
    }

    // TODO: Make 3 functions and store fun pointer
    #[inline]
    fn create_atom(&mut self, txt: &str) -> CodecResult<PyObject> {
        match txt {
            "true" => {
                let t = PyBool::get(self.py, true);
                return Ok(t.into_object());
            }
            "false" => {
                let t = PyBool::get(self.py, false);
                return Ok(t.into_object());
            }
            "undefined" => return Ok(self.py.None()),
            _ => {}
        }

        match self.atom_representation {
            AtomRepresentation::Bytes => {
                let py_bytes = PyBytes::new(self.py, txt.as_ref());
                Ok(py_bytes.into_object())
            }
            AtomRepresentation::Str => {
                // Return as a string
                let py_txt = PyString::new(self.py, txt);
                Ok(py_txt.into_object())
            }
            _ => {
                // Construct Atom object (Note: performance cost)
                let atom_obj = self.get_atom_pyclass();
                Ok(atom_obj.call(self.py, (txt,), None)?)
            }
        } // match
    }

    #[inline]
    fn parse_arbitrary_length_int(
        &self,
        reader: &mut Reader,
        size: usize,
        sign: u8,
    ) -> CodecResult<PyObject> {
        let bin = reader.read(size)?;
        let data = PyBytes::new(self.py, bin);
        let builtins = self.py.import("builtins")?;
        let py_int = builtins.get(self.py, "int")?;
        let val = py_int.call_method(self.py, "from_bytes", (data, "little"), None)?;
        let val = if sign == 0 {
            val
        } else {
            val.call_method(self.py, "__mul__", (-1,), None)?
        };
        Ok(val.into_object())
    }
    /// Given input _after_ binary tag, parse remaining bytes
    #[inline]
    fn parse_binary(&self, in_bytes: &mut Reader) -> CodecResult<PyObject> {
        let sz = in_bytes.read_u32()? as usize;
        let bin = in_bytes.read(sz)?;
        let py_bytes = PyBytes::new(self.py, bin);
        Ok(py_bytes.into_object())
    }

    /// Given input _after_ bit-string tag, parse remaining bytes and bit-count
    #[inline]
    fn parse_bitstring(&mut self, in_bytes: &mut Reader) -> CodecResult<PyObject> {
        let sz = in_bytes.read_u32()? as usize;
        let last_byte_bits: u8 = in_bytes.read_u8()?;
        let bin = in_bytes.read(sz)?;
        let py_bytes = PyBytes::new(self.py, bin);

        //    let py_bitstr_cls: PyObject = self.get_bitstr_pyclass();
        //    let py_bitstr = py_bitstr_cls.call(self.py, (py_bytes, last_byte_bits), None)?;

        //    Ok(py_bitstr.into_object())
        let py_result = PyTuple::new(
            self.py,
            &[
                py_bytes.into_object(),
                last_byte_bits.to_py_object(self.py).into_object(),
            ],
        );
        Ok(py_result.into_object())
    }

    /// Given input _after_ string tag, parse remaining bytes as an ASCII string
    #[inline]
    fn parse_string(&self, reader: &mut Reader) -> CodecResult<PyObject> {
        let sz = reader.read_u16()? as usize;
        let arr = reader.read(sz)?;
        let result = match self.bytestring_repr {
            ByteStringRepresentation::Str => {
                let rust_str = str::from_utf8(arr)?;
                PyString::new(self.py, rust_str).into_object()
            }
            ByteStringRepresentation::Bytes => PyBytes::new(self.py, arr).into_object(),
            ByteStringRepresentation::IntList => {
                let lst: Vec<_> = arr
                    .iter()
                    .map(|n| n.to_py_object(self.py).into_object())
                    .collect();
                PyList::new(self.py, lst.as_ref()).into_object()
            }
        };

        Ok(result)
    }

    /// Given input _after_ the list tag, parse the list elements and tail
    #[inline]
    fn parse_list(&mut self, reader: &mut Reader) -> CodecResult<PyObject> {
        let sz = reader.read_u32()? as usize;

        let mut lst = Vec::<PyObject>::with_capacity(sz);

        // Read list elements, one by one
        for _i in 0..sz {
            let val = self.decode(reader)?;
            lst.push(val);
        }

        let py_lst = PyList::new(self.py, lst.as_ref());

        // Check whether last element is a NIL, or something else
        if reader.peek()? == consts::TAG_NIL_EXT {
            reader.read_u8().unwrap();
            // We are looking at a proper list, so just return the result
            Ok(py_lst.into_object())
        } else {
            // We are looking at an improper list
            let tail_val = self.decode(reader)?;
            let improper_list_cls = self.get_improper_list_pyclass();
            let improper_list = improper_list_cls.call(self.py, (py_lst, tail_val), None)?;
            Ok(improper_list.into_object())
        }
    }

    /// Given input _after_ the TAG_MAP_EXT byte, parse map key/value pairs.
    #[inline]
    fn parse_map(&mut self, reader: &mut Reader) -> CodecResult<PyObject> {
        let arity = reader.read_u32()? as usize;

        let result = PyDict::new(self.py);

        // Read key/value pairs two at a time
        for _i in 0..arity {
            let py_key = self.decode(reader)?;
            let py_val = self.decode(reader)?;
            result.set_item(self.py, py_key, py_val).unwrap();
        }

        Ok(result.into_object())
    }

    /// Given input _after_ the TAG_SMALL_TUPLE_EXT or the TAG_TUPLE_EXT byte,
    /// tuple elements into a vector and create Python tuple.
    #[inline]
    fn parse_tuple(&mut self, reader: &mut Reader, arity: usize) -> CodecResult<PyObject> {
        let mut result = Vec::<PyObject>::with_capacity(arity);

        // Read values one by one
        for _i in 0..arity {
            let py_val = self.decode(reader)?;
            result.push(py_val);
        }

        let py_result = PyTuple::new(self.py, result.as_ref());
        Ok(py_result.into_object())
    }

    /// Given input _after_ the PID tag byte, parse an external pid
    #[inline]
    fn parse_pid(&mut self, reader: &mut Reader) -> CodecResult<PyObject> {
        // Temporarily switch atom representation to binary and then decode node
        let save_repr = self.atom_representation;
        self.atom_representation = AtomRepresentation::Str;
        let node = self.decode(reader)?;
        self.atom_representation = save_repr;

        let id: u32 = reader.read_u32()?;
        let serial: u32 = reader.read_u32()?;
        let creation: u8 = reader.read_u8()?;

        let pid_obj = self.get_pid_pyclass();
        let py_pid = pid_obj.call(self.py, (node, id, serial, creation), None)?;
        Ok(py_pid.into_object())
    }

    /// Given input _after_ the NEW_PID tag byte, parse an external pid
    #[inline]
    fn parse_new_pid(&mut self, reader: &mut Reader) -> CodecResult<PyObject> {
        // Temporarily switch atom representation to binary and then decode node
        let save_repr = self.atom_representation;
        self.atom_representation = AtomRepresentation::Str;
        let node = self.decode(reader)?;
        self.atom_representation = save_repr;

        let id: u32 = reader.read_u32()?;
        let serial: u32 = reader.read_u32()?;
        let creation: u32 = reader.read_u32()?;

        let pid_obj = self.get_pid_pyclass();
        let py_pid = pid_obj.call(self.py, (node, id, serial, creation), None)?;
        Ok(py_pid.into_object())
    }

    /// Given input _after_ the Reference tag byte, parse an external reference
    #[inline]
    fn parse_ref(&mut self, reader: &mut Reader) -> CodecResult<PyObject> {
        let term_len = reader.read_u16()? as usize;

        // Temporarily switch atom representation to binary and then decode node
        let save_repr = self.atom_representation;
        self.atom_representation = AtomRepresentation::Str;
        let node = self.decode(reader)?;
        self.atom_representation = save_repr;

        let creation: u8 = reader.read_u8()?;

        let id: &[u8] = reader.read(term_len * 4)?;
        let bytes_id = PyBytes::new(self.py, id);

        let ref_obj = self.get_ref_pyclass();
        let py_ref = ref_obj.call(self.py, (node, creation, bytes_id), None)?;
        Ok(py_ref.into_object())
    }

    /// Given input _after_ the Newer Reference tag byte, parse an external reference
    #[inline]
    fn parse_newer_ref(&mut self, reader: &mut Reader) -> CodecResult<PyObject> {
        let term_len = reader.read_u16()? as usize;

        // Temporarily switch atom representation to binary and then decode node
        let save_repr = self.atom_representation;
        self.atom_representation = AtomRepresentation::Str;
        let node = self.decode(reader)?;
        self.atom_representation = save_repr;

        let creation: u32 = reader.read_u32()?;

        let id: &[u8] = reader.read(term_len * 4)?;
        let bytes_id = PyBytes::new(self.py, id);

        let ref_obj = self.get_ref_pyclass();
        let py_ref = ref_obj.call(self.py, (node, creation, bytes_id), None)?;
        Ok(py_ref.into_object())
    }

    /// Given input _after_ the Fun tag byte, parse a fun (not useful in Python
    /// but we store all parts of it and can reconstruct it, if it will be sent out)
    #[inline]
    fn parse_fun(&mut self, reader: &mut Reader) -> CodecResult<PyObject> {
        let _size = reader.read_u32()?;
        let arity = reader.read_u8()? as usize;

        let uniq_md5 = reader.read(16)?;

        let index = reader.read_u32()?;
        let num_free = reader.read_u32()?;

        let module = self.decode(reader)?;
        let old_index = self.decode(reader)?;
        let old_uniq = self.decode(reader)?;
        let pid = self.decode(reader)?;

        // Decode num_free free variables following after pid
        let mut frozen_vars = Vec::<PyObject>::with_capacity(arity);
        for _i in 0..num_free {
            let py_val = self.decode(reader)?;
            frozen_vars.push(py_val);
        }
        let py_frozen_vars = PyTuple::new(self.py, frozen_vars.as_ref());

        let fun_obj = self.get_fun_pyclass();
        let py_fun = fun_obj.call(
            self.py,
            (
                module,
                arity,
                pid,
                index,
                uniq_md5,
                old_index,
                old_uniq,
                py_frozen_vars.into_object(),
            ),
            None,
        )?;
        Ok(py_fun.into_object())
    }
}
// end impl
