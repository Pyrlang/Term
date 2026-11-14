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

use flate2::{Decompress, FlushDecompress, Status};
use pyo3::exceptions::PyTypeError;
use pyo3::prelude::*;
use pyo3::types::{PyBool, PyBytes, PyDict, PyInt, PyList, PyTuple};
use pyo3::IntoPyObjectExt;
use std::borrow::Cow;
use std::str;

use crate::reader::{Readable, Reader};

use super::consts;
use super::errors::{CodecError, CodecResult};
use super::helpers;
use super::helpers::{AtomRepresentation, BitstringRepresentation, ByteStringRepresentation};

/// Default of option "max_depth": how deeply terms may nest.
pub const DEFAULT_MAX_DEPTH: usize = 4096;

/// Default of option "max_size": the largest size, in bytes, that a
/// compressed term may declare for its data (256 MiB).
pub const DEFAULT_MAX_SIZE: usize = 256 * 1024 * 1024;

/// Most elements reserved ahead for one compound term; more grow on demand.
const PREALLOC_MAX: usize = 4096;

/// Bytes added to the output buffer at a time while inflating.
const INFLATE_CHUNK: usize = 64 * 1024;

pub struct Decoder<'py> {
    py: Python<'py>, // Python instance will live at least as long as Decoder
    atom_representation: AtomRepresentation,
    bytestring_repr: ByteStringRepresentation,
    bitstring_repr: BitstringRepresentation,
    // Options "max_depth" and "max_size" (resource limits).
    max_depth: usize,
    max_size: usize,

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
    cached_bitstring_pyclass: Option<Bound<'py, PyAny>>,
}

/// A compound term whose children are being decoded (see `Decoder::decode`).
/// `remaining` counts the children still to come.
enum Frame<'py> {
    /// LIST_EXT elements.
    List {
        items: Vec<Bound<'py, PyAny>>,
        remaining: usize,
    },
    /// All elements read; a tail that is not NIL comes next.
    ListTail { items: Vec<Bound<'py, PyAny>> },
    Tuple {
        items: Vec<Bound<'py, PyAny>>,
        remaining: usize,
    },
    /// Keys and values in turn; `key` holds a key while its value is read.
    Map {
        dict: Bound<'py, PyDict>,
        key: Option<Bound<'py, PyAny>>,
        remaining: usize,
    },
    /// NEW_FUN_EXT: Module, OldIndex, OldUniq, Pid, then the free variables.
    Fun {
        arity: u8,
        uniq: Bound<'py, PyBytes>,
        index: u32,
        items: Vec<Bound<'py, PyAny>>,
        remaining: usize,
    },
}

/// What reading the start of a term gives.
enum Start<'py> {
    Value(Bound<'py, PyAny>),
    Open(Frame<'py>),
}

/// A frame after it took a child (or just opened): still waiting for more,
/// or finished as a value (`true` if the decode hook already saw it).
enum Progress<'py> {
    Waiting(Frame<'py>),
    Done(Bound<'py, PyAny>, bool),
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

/// Read a count field (32 bits, or 8 if `small`) and return it if the input
/// can hold that many elements of at least `per_element` bytes each; checked
/// before anything is allocated.
fn read_count(
    reader: &mut Reader,
    small: bool,
    per_element: usize,
    what: &'static str,
) -> CodecResult<usize> {
    let count = if small {
        usize::from(reader.read_u8()?)
    } else {
        reader.read_u32()? as usize
    };
    let remaining = reader.remaining();
    match count.checked_mul(per_element) {
        Some(need) if need <= remaining => Ok(count),
        _ => Err(CodecError::TooManyElements {
            what,
            count,
            remaining,
        }),
    }
}

/// A vector for `count` children, reserving no more than `PREALLOC_MAX`.
fn items_for<'py>(count: usize) -> Vec<Bound<'py, PyAny>> {
    Vec::with_capacity(count.min(PREALLOC_MAX))
}

/// The data of a compressed term: exactly `declared` bytes and a complete
/// zlib stream. Inflates at most about `declared + INFLATE_CHUNK` bytes, so a
/// stream that holds more fails without producing it.
fn inflate(input: &[u8], declared: usize, max_size: usize) -> CodecResult<Vec<u8>> {
    if declared > max_size {
        return Err(CodecError::CompressedTooLarge { declared, max_size });
    }
    let mut out = Vec::new();
    let mut z = Decompress::new(true);
    loop {
        if out.len() > declared {
            return Err(CodecError::CompressedSizeMismatch);
        }
        if out.len() == out.capacity() {
            out.reserve(INFLATE_CHUNK.min(declared - out.len() + 1));
        }
        let consumed =
            usize::try_from(z.total_in()).map_err(|_| CodecError::CompressedSizeMismatch)?;
        let rest = input.get(consumed..).unwrap_or_default();
        let before = (z.total_in(), out.len());
        let status = z
            .decompress_vec(rest, &mut out, FlushDecompress::None)
            .map_err(|e| CodecError::Compressed { txt: e.to_string() })?;
        if status == Status::StreamEnd {
            break;
        }
        if (z.total_in(), out.len()) == before && out.len() < out.capacity() {
            // No progress with room to write: the input ends inside the stream.
            return Err(CodecError::CompressedIncomplete);
        }
    }
    if out.len() != declared {
        return Err(CodecError::CompressedSizeMismatch);
    }
    Ok(out)
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
        let bitstring_repr = helpers::get_bitstring_opt(&opts1)?;
        let max_depth = helpers::get_positive_int_opt(&opts1, "max_depth", DEFAULT_MAX_DEPTH)?;
        let max_size = helpers::get_positive_int_opt(&opts1, "max_size", DEFAULT_MAX_SIZE)?;

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
            bitstring_repr,
            max_depth,
            max_size,
            decode_hook,
            atom_call,
            cached_atom_pyclass: None,
            cached_node_atom_pyclass: None,
            cached_pid_pyclass: None,
            cached_ref_pyclass: None,
            cached_fun_pyclass: None,
            cached_improper_list_pyclass: None,
            cached_bitstring_pyclass: None,
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
            let declared = reader.read_u32()? as usize;
            let decompressed = inflate(reader.rest(), declared, self.max_size)?;
            let mut decompressed_reader = (&decompressed).into();
            self.decode_and_wrap(&mut decompressed_reader)
        } else {
            // Second byte was not consumed, so restart parsing from the second byte
            self.decode_and_wrap(reader)
        }
    }

    /// Decodes binary External Term Format (ETF) into a Python structure.
    /// Every value in it, the term itself included, passes through the decode
    /// hook of its type, children first.
    ///
    /// Iterative: compound terms wait on an explicit stack of `Frame`, at most
    /// `max_depth` of them, so the native stack does not grow with the nesting.
    pub fn decode(&mut self, reader: &mut Reader) -> CodecResult<Bound<'py, PyAny>> {
        let mut stack: Vec<Frame<'py>> = Vec::new();
        loop {
            let progress = match self.start_term(reader)? {
                Start::Value(value) => Progress::Done(value, false),
                Start::Open(frame) => self.open(frame, reader)?,
            };
            let (mut value, mut hooked) = match progress {
                Progress::Waiting(frame) => {
                    if stack.len() >= self.max_depth {
                        return Err(CodecError::TooDeep {
                            max_depth: self.max_depth,
                        });
                    }
                    stack.push(frame);
                    continue;
                }
                Progress::Done(value, hooked) => (value, hooked),
            };
            // Pass finished values up to the frames waiting for them.
            loop {
                if !hooked {
                    value = self.apply_hook(value)?;
                }
                let Some(frame) = stack.pop() else {
                    return Ok(value);
                };
                match self.add_child(frame, value, reader)? {
                    Progress::Waiting(frame) => {
                        stack.push(frame);
                        break;
                    }
                    Progress::Done(v, h) => {
                        value = v;
                        hooked = h;
                    }
                }
            }
        }
    }

    /// `value` passed through the decode hook for its type name, if any.
    fn apply_hook(&self, value: Bound<'py, PyAny>) -> CodecResult<Bound<'py, PyAny>> {
        if self.decode_hook.is_empty() {
            return Ok(value);
        }
        let type_name = value.get_type().name()?;
        match self.decode_hook.get_item(type_name)? {
            Some(h1) => Ok(h1.call1((value,))?),
            None => Ok(value),
        }
    }

    /// Read the next term: its value, or a frame for a compound term whose
    /// children follow.
    fn start_term(&mut self, reader: &mut Reader) -> CodecResult<Start<'py>> {
        let tag = reader.read_u8()?;
        let value = match tag {
            consts::TAG_ATOM_EXT => self.parse_latin1_atom::<u16>(reader),
            consts::TAG_ATOM_UTF8_EXT => self.parse_utf8_atom::<u16>(reader),
            consts::TAG_SMALL_ATOM_EXT => self.parse_latin1_atom::<u8>(reader),
            consts::TAG_SMALL_ATOM_UTF8_EXT => self.parse_utf8_atom::<u8>(reader),
            consts::TAG_BINARY_EXT => self.parse_binary(reader),
            consts::TAG_BIT_BINARY_EXT => self.parse_bitstring(reader),
            consts::TAG_NIL_EXT => Ok(PyList::empty(self.py).into_any()),
            consts::TAG_LIST_EXT => {
                // The elements and then the tail, at least one byte each.
                let count = read_count(reader, false, 1, "LIST_EXT")?;
                return Ok(Start::Open(Frame::List {
                    items: items_for(count),
                    remaining: count,
                }));
            }
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
            consts::TAG_MAP_EXT => {
                let pairs = read_count(reader, false, 2, "MAP_EXT")?;
                return Ok(Start::Open(Frame::Map {
                    dict: PyDict::new(self.py),
                    key: None,
                    remaining: pairs,
                }));
            }
            consts::TAG_SMALL_TUPLE_EXT => {
                let arity = read_count(reader, true, 1, "SMALL_TUPLE_EXT")?;
                return Ok(Start::Open(Frame::Tuple {
                    items: items_for(arity),
                    remaining: arity,
                }));
            }
            consts::TAG_LARGE_TUPLE_EXT => {
                let arity = read_count(reader, false, 1, "LARGE_TUPLE_EXT")?;
                return Ok(Start::Open(Frame::Tuple {
                    items: items_for(arity),
                    remaining: arity,
                }));
            }
            consts::TAG_PID_EXT => self.parse_pid(reader),
            consts::TAG_NEW_PID_EXT => self.parse_new_pid(reader),
            consts::TAG_NEW_REF_EXT => self.parse_ref(reader),
            consts::TAG_NEWER_REF_EXT => self.parse_newer_ref(reader),
            consts::TAG_NEW_FUN_EXT => {
                let _size = reader.read_u32()?; // OTP ignores it too (TERM-05)
                let arity = reader.read_u8()?;
                let uniq = PyBytes::new(self.py, reader.read(16)?);
                let index = reader.read_u32()?;
                let num_free = read_count(reader, false, 1, "NEW_FUN_EXT")?;
                // Module, OldIndex, OldUniq and Pid come before the free variables.
                let remaining = num_free.saturating_add(4);
                return Ok(Start::Open(Frame::Fun {
                    arity,
                    uniq,
                    index,
                    items: items_for(remaining),
                    remaining,
                }));
            }
            _ => Err(CodecError::UnknownTermTagByte { b: tag }),
        }?;
        Ok(Start::Value(value))
    }

    /// A frame just started: waiting if children follow, else finished.
    fn open(&mut self, frame: Frame<'py>, reader: &mut Reader) -> CodecResult<Progress<'py>> {
        match frame {
            Frame::List {
                items,
                remaining: 0,
            } => self.list_end(items, reader),
            Frame::Tuple {
                items,
                remaining: 0,
            } => Ok(Progress::Done(
                PyTuple::new(self.py, items)?.into_any(),
                false,
            )),
            Frame::Map {
                dict, remaining: 0, ..
            } => Ok(Progress::Done(dict.into_any(), false)),
            frame => Ok(Progress::Waiting(frame)),
        }
    }

    /// All elements of a list are read: a NIL tail makes a proper list. NIL is
    /// not a value of its own, so no decode hook sees it. Any other tail is
    /// decoded next.
    fn list_end(
        &mut self,
        items: Vec<Bound<'py, PyAny>>,
        reader: &mut Reader,
    ) -> CodecResult<Progress<'py>> {
        if reader.peek()? == consts::TAG_NIL_EXT {
            reader.read_u8()?;
            return Ok(Progress::Done(
                PyList::new(self.py, items)?.into_any(),
                false,
            ));
        }
        Ok(Progress::Waiting(Frame::ListTail { items }))
    }

    /// Give a frame its next child: waiting while more follow, else finished.
    fn add_child(
        &mut self,
        frame: Frame<'py>,
        value: Bound<'py, PyAny>,
        reader: &mut Reader,
    ) -> CodecResult<Progress<'py>> {
        match frame {
            Frame::List {
                mut items,
                remaining,
            } => {
                items.push(value);
                let remaining = remaining.saturating_sub(1);
                if remaining == 0 {
                    return self.list_end(items, reader);
                }
                Ok(Progress::Waiting(Frame::List { items, remaining }))
            }
            Frame::ListTail { items } => {
                if items.is_empty() {
                    // A zero-length list is its tail, already hooked:
                    // <<108,0,0,0,0,97,42>> is 42 (binary_SUITE:robustness).
                    return Ok(Progress::Done(value, true));
                }
                let py_list = PyList::new(self.py, items)?;
                let cls = cached_class(
                    self.py,
                    &mut self.cached_improper_list_pyclass,
                    "term.list",
                    "ImproperList",
                )?;
                Ok(Progress::Done(cls.call1((py_list, value))?, false))
            }
            Frame::Tuple {
                mut items,
                remaining,
            } => {
                items.push(value);
                let remaining = remaining.saturating_sub(1);
                if remaining == 0 {
                    return Ok(Progress::Done(
                        PyTuple::new(self.py, items)?.into_any(),
                        false,
                    ));
                }
                Ok(Progress::Waiting(Frame::Tuple { items, remaining }))
            }
            Frame::Map {
                dict,
                key: None,
                remaining,
            } => Ok(Progress::Waiting(Frame::Map {
                dict,
                key: Some(value),
                remaining,
            })),
            Frame::Map {
                dict,
                key: Some(key),
                remaining,
            } => {
                if let Err(error) = dict.set_item(&key, value) {
                    if !error.is_instance_of::<PyTypeError>(self.py) {
                        return Err(error.into());
                    }
                    let type_name = key.get_type().name()?.to_string();
                    return Err(CodecError::UnhashableKey { type_name, error });
                }
                let remaining = remaining.saturating_sub(1);
                if remaining == 0 {
                    return Ok(Progress::Done(dict.into_any(), false));
                }
                Ok(Progress::Waiting(Frame::Map {
                    dict,
                    key: None,
                    remaining,
                }))
            }
            Frame::Fun {
                arity,
                uniq,
                index,
                mut items,
                remaining,
            } => {
                items.push(value);
                let remaining = remaining.saturating_sub(1);
                if remaining == 0 {
                    return Ok(Progress::Done(
                        self.make_fun(arity, uniq, index, items)?,
                        false,
                    ));
                }
                Ok(Progress::Waiting(Frame::Fun {
                    arity,
                    uniq,
                    index,
                    items,
                    remaining,
                }))
            }
        }
    }

    /// Build a `term.fun.Fun` from its header fields and its decoded parts:
    /// Module, OldIndex, OldUniq, Pid, then the free variables.
    fn make_fun(
        &mut self,
        arity: u8,
        uniq: Bound<'py, PyBytes>,
        index: u32,
        items: Vec<Bound<'py, PyAny>>,
    ) -> CodecResult<Bound<'py, PyAny>> {
        let mut parts = items.into_iter();
        // Tuple fields are evaluated left to right.
        let (Some(module), Some(old_index), Some(old_uniq), Some(pid)) =
            (parts.next(), parts.next(), parts.next(), parts.next())
        else {
            return Err(CodecError::BadFun);
        };
        let free_vars = PyTuple::new(self.py, parts)?;
        let fun_cls = cached_class(self.py, &mut self.cached_fun_pyclass, "term.fun", "Fun")?;
        Ok(fun_cls.call1((
            module, arity, pid, index, uniq, old_index, old_uniq, free_vars,
        ))?)
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
        let val = if sign == 0 { val } else { val.neg()? };
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
    /// A whole last byte (8 bits) makes a binary, as OTP decodes it. Otherwise
    /// the "bitstring" option picks `(bytes, last_byte_bits)` or `BitString`.
    #[inline]
    fn parse_bitstring(&mut self, in_bytes: &mut Reader) -> CodecResult<Bound<'py, PyAny>> {
        let sz = in_bytes.read_u32()? as usize;
        let last_byte_bits: u8 = in_bytes.read_u8()?;
        helpers::check_bits(sz, last_byte_bits)?;
        let bin = in_bytes.read(sz)?;
        if last_byte_bits == 8 {
            return Ok(PyBytes::new(self.py, bin).into_any());
        }
        let py_bytes = PyBytes::new(self.py, &helpers::mask_last_byte(bin, last_byte_bits));
        let py_bits = last_byte_bits.into_bound_py_any(self.py)?;
        match self.bitstring_repr {
            BitstringRepresentation::Tuple => {
                Ok(PyTuple::new(self.py, [py_bytes.into_any(), py_bits])?.into_any())
            }
            BitstringRepresentation::BitString => {
                let cls = cached_class(
                    self.py,
                    &mut self.cached_bitstring_pyclass,
                    "term.bitstring",
                    "BitString",
                )?;
                Ok(cls.call1((py_bytes, py_bits))?)
            }
        }
    }

    /// Given input _after_ string tag, parse remaining bytes: one character
    /// (code point 0..255, so Latin-1) per byte.
    #[inline]
    fn parse_string(&self, reader: &mut Reader) -> CodecResult<Bound<'py, PyAny>> {
        let sz = reader.read_u16()? as usize;
        let arr = reader.read(sz)?;
        let result = match self.bytestring_repr {
            ByteStringRepresentation::Str => arr
                .iter()
                .map(|&b| char::from(b))
                .collect::<String>()
                .into_bound_py_any(self.py)?,
            ByteStringRepresentation::Bytes => PyBytes::new(self.py, arr).into_any(),
            ByteStringRepresentation::IntList => {
                PyList::new(self.py, arr.iter().copied())?.into_any()
            }
        };
        Ok(result)
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

#[cfg(test)]
mod tests {
    use super::inflate;
    use crate::errors::CodecError;
    use flate2::{write::ZlibEncoder, Compression};
    use std::io::Write;

    fn deflate(data: &[u8]) -> Vec<u8> {
        let mut e = ZlibEncoder::new(Vec::new(), Compression::default());
        e.write_all(data).unwrap();
        e.finish().unwrap()
    }

    #[test]
    fn inflate_needs_exact_size_and_whole_stream() {
        let data = vec![7u8; 100_000];
        let z = deflate(&data);
        assert_eq!(inflate(&z, data.len(), usize::MAX).unwrap(), data);
        assert!(matches!(
            inflate(&z, data.len() - 1, usize::MAX),
            Err(CodecError::CompressedSizeMismatch)
        ));
        assert!(matches!(
            inflate(&z, data.len() + 1, usize::MAX),
            Err(CodecError::CompressedSizeMismatch)
        ));
        // The Adler-32 trailer cut off.
        assert!(matches!(
            inflate(&z[..z.len() - 2], data.len(), usize::MAX),
            Err(CodecError::CompressedIncomplete)
        ));
        assert!(matches!(
            inflate(&z, data.len(), data.len() - 1),
            Err(CodecError::CompressedTooLarge { .. })
        ));
    }

    #[test]
    fn inflate_stops_a_bomb_early() {
        // 64 MiB of zeros declared as 1 KiB: fails after about one chunk.
        let z = deflate(&vec![0u8; 64 * 1024 * 1024]);
        assert!(matches!(
            inflate(&z, 1024, usize::MAX),
            Err(CodecError::CompressedSizeMismatch)
        ));
    }
}
