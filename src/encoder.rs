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

use super::classes;
use super::consts;
use super::decoder;
use super::errors::{CodecError, CodecResult};
use super::helpers;
use pyo3::exceptions::PyUnicodeEncodeError;
use pyo3::ffi;
use pyo3::intern;
use pyo3::prelude::*;
use pyo3::types::{PyBool, PyBytes, PyDict, PyFloat, PyInt, PyList, PyString, PyTuple, PyType};
use std::borrow::Cow;
use std::collections::HashSet;
use std::ffi::c_int;

pub struct Encoder<'py> {
    pub py: Python<'py>, // Python instance will live at least as long as Encoder
    pub data: Vec<u8>,
    // Binaries of at least DEFER_BINARY bytes, not copied into `data`: each
    // belongs at its offset in `data`, and `into_bytes` puts it there.
    deferred: Vec<(usize, Bound<'py, PyBytes>)>,
    // The total size of the binaries in `deferred`.
    deferred_len: usize,
    // The "encode_hook" option; None when it is missing or empty.
    encode_hook: Option<Bound<'py, PyDict>>,
    catch_all: Option<Bound<'py, PyAny>>,
    // Option "max_depth": how deeply compound values may nest.
    max_depth: usize,
    // The term classes, for telling what a value is.
    classes: &'static classes::TermClasses,
}

/// What a value encodes as (see `Encoder::kind_of`).
#[derive(Clone, Copy)]
enum Kind {
    Int,
    Float,
    Str,
    Bool,
    List,
    Tuple,
    Dict,
    None,
    Bytes,
    Atom,
    ImproperList,
    Pid,
    Port,
    Export,
    Fun,
    Record,
    Reference,
    BitString,
    /// No encoding of its own: a substitute is encoded instead.
    Other,
}

/// The children of a compound value being encoded (see `Encoder::encode`).
enum Children<'py> {
    List(Bound<'py, PyList>),
    Tuple(Bound<'py, PyTuple>),
    /// A dict's `items()` snapshot: two children (key, value) per item.
    Pairs(Bound<'py, PyList>),
}

/// What follows the children of a compound value.
enum After<'py> {
    Nothing,
    /// NIL_EXT: a proper list.
    Nil,
    /// The tail of an improper list, encoded as one more child.
    Tail(Bound<'py, PyAny>),
    /// Fill in the Size of the NEW_FUN_EXT whose Size field is at offset
    /// `at` of `data`, `start` of the whole output (see `Encoder::len`).
    FunSize {
        at: usize,
        start: usize,
    },
}

/// A compound value whose children are being encoded. `container` keeps the
/// value alive, so its address identifies it while it is open.
struct Frame<'py> {
    container: Bound<'py, PyAny>,
    children: Children<'py>,
    count: usize,
    next: usize,
    after: After<'py>,
}

impl<'py> Frame<'py> {
    /// The next child to encode, or None when the frame is finished (its
    /// closing NIL_EXT, if any, is then written to `data`; `deferred_len`
    /// is `Encoder::deferred_len`).
    fn next_child(
        &mut self,
        data: &mut Vec<u8>,
        deferred_len: usize,
    ) -> CodecResult<Option<Bound<'py, PyAny>>> {
        if self.next < self.count {
            let i = self.next;
            self.next += 1;
            let child = match &self.children {
                Children::List(list) => list.get_item(i)?,
                Children::Tuple(tuple) => tuple.get_item(i)?,
                Children::Pairs(items) => items.get_item(i / 2)?.get_item(i % 2)?,
            };
            return Ok(Some(child));
        }
        match std::mem::replace(&mut self.after, After::Nothing) {
            After::Nothing => Ok(None),
            After::Nil => {
                data.push(consts::TAG_NIL_EXT);
                Ok(None)
            }
            After::Tail(tail) => Ok(Some(tail)),
            After::FunSize { at, start } => {
                let end = data.len().saturating_add(deferred_len);
                patch_fun_size(data, at, end.saturating_sub(start))?;
                Ok(None)
            }
        }
    }
}

/// Fill in the Size of a NEW_FUN_EXT whose Size field is at offset `at`:
/// `size` bytes from that field to the end of the fun.
fn patch_fun_size(data: &mut [u8], at: usize, size: usize) -> CodecResult<()> {
    let size = length_u32(size)?;
    let field = data
        .get_mut(at..at.saturating_add(4))
        .ok_or(CodecError::BadValue("Size field is missing"))?;
    field.copy_from_slice(&size.to_be_bytes());
    Ok(())
}

/// Open frames up to this depth are checked for a cycle by scanning the
/// stack; deeper ones by a set (TERM-24: a set per call cost as much as
/// encoding a small term).
const SCAN_DEPTH: usize = 32;

/// The containers of the open frames, for finding a value that contains
/// itself. Empty until the stack first grows past `SCAN_DEPTH`; from then on
/// it holds the address of every open container.
#[derive(Default)]
struct OpenSet {
    deep: Option<HashSet<usize>>,
}

impl OpenSet {
    /// Note `container` as open above `stack`; false if it is open already.
    fn insert(&mut self, stack: &[Frame<'_>], container: &Bound<'_, PyAny>) -> bool {
        let addr = container.as_ptr() as usize;
        if self.deep.is_none() {
            if stack.len() < SCAN_DEPTH {
                return !stack.iter().any(|f| f.container.is(container));
            }
            let set = stack.iter().map(|f| f.container.as_ptr() as usize);
            self.deep = Some(set.collect());
        }
        self.deep.as_mut().is_some_and(|set| set.insert(addr))
    }

    /// Note `container` as closed.
    fn remove(&mut self, container: &Bound<'_, PyAny>) {
        if let Some(set) = &mut self.deep {
            set.remove(&(container.as_ptr() as usize));
        }
    }
}

/// What starting to encode a value gives.
enum Step<'py> {
    /// The value is written.
    Done,
    /// Its header is written; its children follow.
    Open(Frame<'py>),
    /// Encode this value in its place.
    Substitute(Bound<'py, PyAny>),
}

/// An exact `int` (not `bool`) from `min` to MAX_SMALL, or `IntegerRange`.
fn small_int(value: &Bound<'_, PyAny>, min: i64, what: &'static str) -> CodecResult<i64> {
    match value.extract::<i64>() {
        Ok(v) if value.is_exact_instance_of::<PyInt>() && v >= min && v <= decoder::MAX_SMALL => {
            Ok(v)
        }
        _ => Err(CodecError::IntegerRange { what }),
    }
}

/// A 32-bit length or count field, or `TooLong`.
fn length_u32(size: usize) -> CodecResult<u32> {
    u32::try_from(size).map_err(|_| CodecError::TooLong { size })
}

impl<'py> Encoder<'py> {
    pub fn new(py: Python<'py>, opt: &Bound<'py, PyAny>) -> CodecResult<Encoder<'py>> {
        let mut encoder = Encoder {
            py,
            data: Vec::with_capacity(32),
            deferred: Vec::new(),
            deferred_len: 0,
            encode_hook: None,
            catch_all: None,
            max_depth: decoder::DEFAULT_MAX_DEPTH,
            classes: classes::term_classes(py)?,
        };
        let Some(py_opts) = helpers::options(opt)? else {
            return Ok(encoder);
        };
        if let Some(h1) = py_opts.get_item(intern!(py, "encode_hook"))? {
            let hooks = h1.cast_into::<PyDict>()?;
            encoder.catch_all = hooks.get_item(intern!(py, "catch_all"))?;
            encoder.encode_hook = (!hooks.is_empty()).then_some(hooks);
        }
        encoder.max_depth =
            helpers::get_positive_int_opt(&py_opts, "max_depth", decoder::DEFAULT_MAX_DEPTH)?;
        Ok(encoder)
    }

    /// The size of the output so far: `data` and the deferred binaries.
    fn len(&self) -> usize {
        self.data.len().saturating_add(self.deferred_len)
    }

    /// The finished output: `data` with the deferred binaries in their
    /// places, written once into the `bytes` object (TERM-27: building it
    /// in a `Vec` and copying it took two fresh buffers, and their page
    /// faults cost twenty copies of a 1 MB binary).
    pub fn into_bytes(self) -> CodecResult<Bound<'py, PyBytes>> {
        if self.deferred.is_empty() {
            return Ok(PyBytes::new(self.py, &self.data));
        }
        let total = self
            .data
            .len()
            .checked_add(self.deferred_len)
            .ok_or(CodecError::TooLong {
                size: self.deferred_len,
            })?;
        let bytes = PyBytes::new_with(self.py, total, |out| {
            let mut pos = 0usize;
            let mut from = 0usize;
            for (at, chunk) in &self.deferred {
                put(out, &mut pos, self.data.get(from..*at))?;
                put(out, &mut pos, Some(chunk.as_bytes()))?;
                from = *at;
            }
            put(out, &mut pos, self.data.get(from..))
        })?;
        Ok(bytes)
    }

    /// Encode a value and append it to `data`.
    ///
    /// Iterative: compound values wait on an explicit stack of `Frame`, at
    /// most `max_depth` of them, so the native stack does not grow with the
    /// nesting. A value that contains itself is an error, and so is a chain
    /// of more than `max_depth` substitutions (hooks that keep returning
    /// values with no encoding of their own).
    pub fn encode(&mut self, py_term: &Bound<'py, PyAny>) -> CodecResult<()> {
        let mut stack: Vec<Frame<'py>> = Vec::new();
        let mut open = OpenSet::default();
        let mut value = py_term.clone();
        let mut substitutions = 0usize;
        loop {
            match self.start_value(&value)? {
                Step::Substitute(other) => {
                    substitutions += 1;
                    if substitutions > self.max_depth {
                        return Err(CodecError::TooManySubstitutions {
                            max_depth: self.max_depth,
                        });
                    }
                    value = other;
                    continue;
                }
                Step::Open(frame) => {
                    if stack.len() >= self.max_depth {
                        return Err(CodecError::TooDeep {
                            max_depth: self.max_depth,
                        });
                    }
                    if !open.insert(&stack, &frame.container) {
                        let type_name = frame.container.get_type().name()?.to_string();
                        return Err(CodecError::Cyclic { type_name });
                    }
                    stack.push(frame);
                }
                Step::Done => {}
            }
            substitutions = 0;
            // The next child of the innermost open value; close finished ones.
            loop {
                let Some(frame) = stack.last_mut() else {
                    return Ok(());
                };
                if let Some(child) = frame.next_child(&mut self.data, self.deferred_len)? {
                    value = child;
                    break;
                }
                open.remove(&frame.container);
                stack.pop();
            }
        }
    }

    /// Write a value; or write the header of a compound value and return its
    /// frame; or return the value to encode in its place. If the type name
    /// (`__name__`) of the value is in encode_hook, what the hook returns is
    /// used instead.
    fn start_value(&mut self, py_term: &Bound<'py, PyAny>) -> CodecResult<Step<'py>> {
        if let Some(encode_hook) = &self.encode_hook {
            let type_name = py_term.get_type().name()?;
            if let Some(h1) = encode_hook.get_item(type_name)? {
                let repr1 = h1.call1((py_term,))?;
                return self.start_default(&repr1);
            }
        }
        self.start_default(py_term)
    }

    /// What `term` encodes as, by its type as the Python codec decides it:
    /// the exact builtin type, then the term classes by `isinstance` in the
    /// Python codec's order. An exact term class is found by identity first,
    /// which gives the same answer (no term class derives from another but
    /// `StrictAtom` from `Atom`) without a subclass check per class.
    fn kind_of(&self, term: &Bound<'py, PyAny>) -> CodecResult<Kind> {
        if term.is_exact_instance_of::<PyInt>() {
            return Ok(Kind::Int);
        }
        if term.is_exact_instance_of::<PyFloat>() {
            return Ok(Kind::Float);
        }
        if term.is_exact_instance_of::<PyString>() {
            return Ok(Kind::Str);
        }
        if term.is_exact_instance_of::<PyBool>() {
            return Ok(Kind::Bool);
        }
        if term.is_exact_instance_of::<PyList>() {
            return Ok(Kind::List);
        }
        if term.is_exact_instance_of::<PyTuple>() {
            return Ok(Kind::Tuple);
        }
        if term.is_exact_instance_of::<PyDict>() {
            return Ok(Kind::Dict);
        }
        if term.is_none() {
            return Ok(Kind::None);
        }
        if term.is_exact_instance_of::<PyBytes>() {
            return Ok(Kind::Bytes);
        }
        let c = self.classes;
        let classes: [(&Py<PyType>, Kind); 10] = [
            (&c.atom, Kind::Atom),
            (&c.strict_atom, Kind::Atom),
            (&c.improper_list, Kind::ImproperList),
            (&c.pid, Kind::Pid),
            (&c.port, Kind::Port),
            (&c.export, Kind::Export),
            (&c.fun, Kind::Fun),
            (&c.record, Kind::Record),
            (&c.reference, Kind::Reference),
            (&c.bitstring, Kind::BitString),
        ];
        let ty = term.get_type_ptr();
        if let Some((_, kind)) = classes
            .iter()
            .find(|(cls, _)| std::ptr::eq(cls.as_ptr().cast(), ty))
        {
            return Ok(*kind);
        }
        for (cls, kind) in classes {
            if term.is_instance(cls.bind(self.py))? {
                return Ok(kind);
            }
        }
        Ok(Kind::Other)
    }

    /// Write `term` as its type says (see `kind_of`).
    fn start_default(&mut self, term: &Bound<'py, PyAny>) -> CodecResult<Step<'py>> {
        let py = self.py;
        match self.kind_of(term)? {
            Kind::Int => self.write_int(term)?,
            Kind::Float => {
                let val: f64 = term.extract()?;
                if !val.is_finite() {
                    return Err(CodecError::NonFiniteFloat { f: val });
                }
                self.write_float(val)?
            }
            Kind::List => {
                let list = term.cast::<PyList>()?;
                if list.is_empty() {
                    // `[]` is NIL_EXT alone, as OTP writes it
                    self.data.push(consts::TAG_NIL_EXT);
                    return Ok(Step::Done);
                }
                let count = list.len();
                self.data.push(consts::TAG_LIST_EXT);
                self.data.push_u32(length_u32(count)?);
                return Ok(self.open(term, Children::List(list.clone()), count, After::Nil));
            }
            Kind::Tuple => {
                let tuple = term.cast::<PyTuple>()?;
                let count = tuple.len();
                if let Ok(small) = u8::try_from(count) {
                    self.data.push(consts::TAG_SMALL_TUPLE_EXT);
                    self.data.push(small);
                } else {
                    self.data.push(consts::TAG_LARGE_TUPLE_EXT);
                    self.data.push_u32(length_u32(count)?);
                }
                return Ok(self.open(term, Children::Tuple(tuple.clone()), count, After::Nothing));
            }
            Kind::Dict => {
                // `items()` is a snapshot list, so a hook that changes the
                // dict while it is encoded cannot break the iteration.
                let items = term.cast::<PyDict>()?.items();
                let pairs = items.len();
                self.data.push(consts::TAG_MAP_EXT);
                self.data.push_u32(length_u32(pairs)?);
                let count = pairs
                    .checked_mul(2)
                    .ok_or(CodecError::TooLong { size: pairs })?;
                return Ok(self.open(term, Children::Pairs(items), count, After::Nothing));
            }
            Kind::Atom => self.write_atom(term)?,
            Kind::Str => self.write_str(term.cast::<PyString>()?)?,
            Kind::Bool => self.write_atom_from_cow(Cow::from(if term.is_truthy()? {
                "true"
            } else {
                "false"
            }))?,
            Kind::None => self.write_atom_from_cow(Cow::from("undefined"))?,
            Kind::ImproperList => {
                let elements = term
                    .getattr(intern!(py, "_elements"))?
                    .cast_into::<PyList>()?;
                let tail = term.getattr(intern!(py, "_tail"))?;
                if elements.is_empty() {
                    // `[... | T]` with no elements is `T` itself
                    return Ok(Step::Substitute(tail));
                }
                let count = elements.len();
                self.data.push(consts::TAG_LIST_EXT);
                self.data.push_u32(length_u32(count)?);
                return Ok(self.open(term, Children::List(elements), count, After::Tail(tail)));
            }
            Kind::Pid => self.write_pid(term)?,
            Kind::Port => self.write_port(term)?,
            Kind::Export => self.write_export(term)?,
            Kind::Fun => return self.start_fun(term),
            Kind::Record => return self.start_record(term),
            Kind::Reference => self.write_ref(term)?,
            Kind::Bytes => self.write_binary(term.cast::<PyBytes>()?)?,
            Kind::BitString => self.write_bitstring(term)?,
            Kind::Other => return Ok(Step::Substitute(self.substitute(term)?)),
        }
        Ok(Step::Done)
    }

    /// A frame for a compound value whose header is written; a value with no
    /// children is finished already.
    fn open(
        &self,
        container: &Bound<'py, PyAny>,
        children: Children<'py>,
        count: usize,
        after: After<'py>,
    ) -> Step<'py> {
        if count == 0 {
            return Step::Done;
        }
        Step::Open(Frame {
            container: container.clone(),
            children,
            count,
            next: 0,
            after,
        })
    }

    /// The value that stands for an object with no encoding of its own: what
    /// the "catch_all" hook or the object's ``__etf__()`` returns, else
    /// the `(b'ClassName', {b'field': value})` tuple of
    /// `py_codec_impl.generic_serialize_object`.
    fn substitute(&mut self, py_term: &Bound<'py, PyAny>) -> CodecResult<Bound<'py, PyAny>> {
        if let Some(h1) = &self.catch_all {
            return Ok(h1.call1((py_term,))?);
        }
        if let Ok(h2) = py_term.getattr(intern!(self.py, "__etf__")) {
            return Ok(h2.call0()?);
        }
        let py_fn = classes::generic_serialize(self.py)?;
        let result_pair = py_fn.call1((py_term, self.py.None()))?;
        let py_pair = result_pair.cast::<PyTuple>()?;
        Ok(py_pair.get_item(0)?)
    }

    /// Writes an exact int: SMALL_INTEGER_EXT for 0..255, INTEGER_EXT for a
    /// signed 32-bit value, otherwise a bignum.
    #[inline]
    fn write_int(&mut self, val: &Bound<'py, PyAny>) -> CodecResult<()> {
        let mut overflow: c_int = 0;
        // SAFETY: `val` is a live object for the whole call (the `Bound`
        // holds a reference and proves this thread is attached to the
        // interpreter), and `overflow` is a valid `c_int` to write to; the
        // call keeps neither pointer. Unlike `extract::<i64>`, it reports a
        // value beyond 64 bits, and its sign, without raising OverflowError:
        // the exception was most of the cost of a bignum (TERM-26).
        let v = unsafe { ffi::PyLong_AsLongLongAndOverflow(val.as_ptr(), &mut overflow) };
        if overflow != 0 {
            return self.write_py_bignum(val, overflow < 0);
        }
        if v == -1 {
            if let Some(error) = PyErr::take(self.py) {
                return Err(error.into());
            }
        }
        self.write_i64(v);
        Ok(())
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
    fn write_py_bignum(&mut self, val: &Bound<'py, PyAny>, negative: bool) -> CodecResult<()> {
        let py = self.py;
        let magnitude = if negative { val.abs()? } else { val.clone() };
        let bits: u64 = magnitude
            .call_method0(intern!(py, "bit_length"))?
            .extract()?;
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
        let b = magnitude.call_method1(intern!(py, "to_bytes"), (size, intern!(py, "little")))?;
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

    /// Writes an atom: SMALL_ATOM_UTF8_EXT when the UTF-8 text fits 255
    /// bytes, else ATOM_UTF8_EXT; at most 255 characters (up to 1020 bytes).
    fn write_atom_from_cow(&mut self, text: Cow<str>) -> CodecResult<()> {
        decoder::check_atom_chars(text.chars().count())?;
        let bytes = text.as_bytes();
        if let Ok(small) = u8::try_from(bytes.len()) {
            self.data.push(consts::TAG_SMALL_ATOM_UTF8_EXT);
            self.data.push(small);
        } else {
            // At most 255 characters of at most 4 bytes: fits 16 bits.
            let len = u16::try_from(bytes.len()).map_err(|_| CodecError::AtomTooLong {
                chars: text.chars().count(),
            })?;
            self.data.push(consts::TAG_ATOM_UTF8_EXT);
            self.data.push_u16(len);
        }
        self.data.extend_from_slice(bytes);
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
        // ASCII text is its own Latin-1 bytes: one copy (TERM-25).
        if text.is_ascii() {
            if let Ok(short) = u16::try_from(text.len()) {
                self.data.reserve(3 + text.len());
                self.data.push(consts::TAG_STRING_EXT);
                self.data.push_u16(short);
                self.data.extend_from_slice(text.as_bytes());
                return Ok(());
            }
        }
        let size = py_str.len()?; // characters, kept by CPython
        if let Ok(short) = u16::try_from(size) {
            let start = self.data.len();
            self.data.reserve(3 + size);
            self.data.push(consts::TAG_STRING_EXT);
            self.data.push_u16(short);
            let latin1 = if size >= LATIN1_BY_PYTHON {
                match latin1_bytes(py_str)? {
                    Some(bytes) => {
                        self.data.extend_from_slice(bytes.as_bytes());
                        true
                    }
                    None => false,
                }
            } else {
                // One pass; a code point above 255 undoes it.
                text.chars().all(|ch| match u8::try_from(ch) {
                    Ok(byte) => {
                        self.data.push(byte);
                        true
                    }
                    Err(_) => false,
                })
            };
            if latin1 {
                return Ok(());
            }
            self.data.truncate(start);
        }
        self.data.push(consts::TAG_LIST_EXT);
        self.data
            .push_u32(u32::try_from(size).map_err(|_| CodecError::TooLong { size })?);
        for ch in text.chars() {
            self.write_i64(i64::from(u32::from(ch)));
        }
        self.data.push(consts::TAG_NIL_EXT);
        Ok(())
    }

    /// Encode a Pid
    #[inline]
    fn write_pid(&mut self, py_pid: &Bound<'py, PyAny>) -> CodecResult<()> {
        let node_name = py_pid.getattr(intern!(self.py, "node_name_"))?;
        let node_name = node_name.cast::<PyString>()?;

        let id: u32 = py_pid.getattr(intern!(self.py, "id_"))?.extract()?;
        let serial: u32 = py_pid.getattr(intern!(self.py, "serial_"))?.extract()?;
        let creation: u32 = py_pid.getattr(intern!(self.py, "creation_"))?.extract()?;

        self.data.push(consts::TAG_NEW_PID_EXT);
        self.write_atom_from_cow(node_name.to_cow()?)?;
        self.data.push_u32(id);
        self.data.push_u32(serial);
        self.data.push_u32(creation);

        Ok(())
    }

    /// Encode an Export (`fun M:F/A`): EXPORT_EXT with Module, Function, then
    /// Arity as OTP writes integers.
    fn write_export(&mut self, py_export: &Bound<'py, PyAny>) -> CodecResult<()> {
        let module = py_export.getattr(intern!(self.py, "module_"))?;
        let function = py_export.getattr(intern!(self.py, "function_"))?;
        let arity = small_int(
            &py_export.getattr(intern!(self.py, "arity_"))?,
            0,
            "EXPORT_EXT arity",
        )?;
        self.data.push(consts::TAG_EXPORT_EXT);
        self.write_atom_from_cow(module.cast::<PyString>()?.to_cow()?)?;
        self.write_atom_from_cow(function.cast::<PyString>()?.to_cow()?)?;
        self.write_i64(arity);
        Ok(())
    }

    /// Start a Record: RECORD_EXT up to its values, which follow as children.
    fn start_record(&mut self, record: &Bound<'py, PyAny>) -> CodecResult<Step<'py>> {
        let fields = record.getattr(intern!(self.py, "fields_"))?;
        let Ok(fields) = fields.cast::<PyDict>() else {
            return Err(CodecError::BadValue("Record fields must be a dict"));
        };
        let exported = record.getattr(intern!(self.py, "exported_"))?;
        let Ok(exported) = exported.cast::<PyBool>() else {
            return Err(CodecError::BadValue("Record exported must be a bool"));
        };
        let module = record.getattr(intern!(self.py, "module_"))?;
        let name = record.getattr(intern!(self.py, "name_"))?;
        // Snapshots, as for a dict: names and values in the same order.
        let names = fields.keys();
        let values = fields.values();
        let count = names.len();

        self.data.push(consts::TAG_RECORD_EXT);
        self.data.push_u32(length_u32(count)?);
        self.data.push(u8::from(exported.is_true()));
        self.write_atom_from_cow(module.cast::<PyString>()?.to_cow()?)?;
        self.write_atom_from_cow(name.cast::<PyString>()?.to_cow()?)?;
        for field in names.iter() {
            let Ok(field) = field.cast::<PyString>() else {
                return Err(CodecError::BadValue("Record field names must be atoms"));
            };
            self.write_atom_from_cow(field.to_cow()?)?;
        }
        Ok(self.open(record, Children::List(values), count, After::Nothing))
    }

    /// Start a Fun: NEW_FUN_EXT up to its free variables, which follow as
    /// children; Size is filled in once they are written.
    fn start_fun(&mut self, fun: &Bound<'py, PyAny>) -> CodecResult<Step<'py>> {
        let free = fun.getattr(intern!(self.py, "free_"))?;
        let (children, count) = if let Ok(list) = free.cast::<PyList>() {
            (Children::List(list.clone()), list.len())
        } else if let Ok(tuple) = free.cast::<PyTuple>() {
            (Children::Tuple(tuple.clone()), tuple.len())
        } else {
            return Err(CodecError::BadValue(
                "Fun free variables must be a list of at most 255",
            ));
        };
        if count > decoder::MAX_FUN_FREE {
            return Err(CodecError::BadValue(
                "Fun free variables must be a list of at most 255",
            ));
        }
        let py_uniq = fun.getattr(intern!(self.py, "uniq_"))?;
        let uniq = match py_uniq.cast::<PyBytes>() {
            Ok(b) if b.as_bytes().len() == 16 => b.as_bytes(),
            _ => return Err(CodecError::BadValue("Fun uniq must be 16 bytes")),
        };
        let arity = u8::try_from(small_int(
            &fun.getattr(intern!(self.py, "arity_"))?,
            0,
            "Fun arity",
        )?)
        .map_err(|_| CodecError::IntegerRange { what: "Fun arity" })?;
        let index = u32::try_from(small_int(
            &fun.getattr(intern!(self.py, "index_"))?,
            0,
            "Fun index",
        )?)
        .map_err(|_| CodecError::IntegerRange { what: "Fun index" })?;
        let old_index = small_int(
            &fun.getattr(intern!(self.py, "old_index_"))?,
            decoder::MIN_SMALL,
            "Fun OldIndex",
        )?;
        let old_uniq = small_int(
            &fun.getattr(intern!(self.py, "old_uniq_"))?,
            decoder::MIN_SMALL,
            "Fun OldUniq",
        )?;
        let module = fun.getattr(intern!(self.py, "module_"))?;
        let Ok(module) = module.cast::<PyString>() else {
            return Err(CodecError::BadValue("Fun module must be an atom"));
        };
        let pid = fun.getattr(intern!(self.py, "pid_"))?;
        if !pid.is_instance(self.classes.pid.bind(self.py))? {
            return Err(CodecError::BadValue("Fun pid must be a Pid"));
        }

        self.data.push(consts::TAG_NEW_FUN_EXT);
        let size_at = self.data.len();
        let size_start = self.len();
        self.data.push_u32(0); // Size, filled in by patch_fun_size
        self.data.push(arity);
        self.data.extend_from_slice(uniq);
        self.data.push_u32(index);
        self.data.push_u32(length_u32(count)?);
        self.write_atom_from_cow(module.to_cow()?)?;
        self.write_i64(old_index);
        self.write_i64(old_uniq);
        self.write_pid(&pid)?;
        if count == 0 {
            let size = self.len().saturating_sub(size_start);
            patch_fun_size(&mut self.data, size_at, size)?;
            return Ok(Step::Done);
        }
        Ok(self.open(
            fun,
            children,
            count,
            After::FunSize {
                at: size_at,
                start: size_start,
            },
        ))
    }

    /// Encode a Port: always V4_PORT_EXT, as OTP 26+ writes every port.
    fn write_port(&mut self, py_port: &Bound<'py, PyAny>) -> CodecResult<()> {
        let node_name = py_port.getattr(intern!(self.py, "node_name_"))?;
        let node_name = node_name.cast::<PyString>()?;
        let id: u64 = py_port.getattr(intern!(self.py, "id_"))?.extract()?;
        let creation: u32 = py_port.getattr(intern!(self.py, "creation_"))?.extract()?;

        self.data.push(consts::TAG_V4_PORT_EXT);
        self.write_atom_from_cow(node_name.to_cow()?)?;
        self.data.extend(id.to_be_bytes());
        self.data.push_u32(creation);
        Ok(())
    }

    /// Encode a Reference
    #[inline]
    fn write_ref(&mut self, py_ref: &Bound<'py, PyAny>) -> CodecResult<()> {
        let node_name = py_ref.getattr(intern!(self.py, "node_name_"))?;
        let node_name = node_name.cast::<PyString>()?;

        let py_id = py_ref.getattr(intern!(self.py, "id_"))?;
        let id = py_id.cast::<PyBytes>()?.as_bytes();

        let creation: u32 = py_ref.getattr(intern!(self.py, "creation_"))?.extract()?;
        let words = match u16::try_from(id.len() / 4) {
            Ok(w) if id.len() % 4 == 0 && (1..=consts::MAX_REF_WORDS).contains(&w) => w,
            _ => return Err(CodecError::BadRefId { size: id.len() }),
        };

        self.data.push(consts::TAG_NEWER_REF_EXT);
        self.data.push_u16(words);
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
        self.data.push_u32(length_u32(data.len())?);
        if data.len() < DEFER_BINARY {
            self.data.extend_from_slice(data);
        } else {
            self.deferred.push((self.data.len(), py_bytes.clone()));
            self.deferred_len = self.deferred_len.saturating_add(data.len());
        }
        Ok(())
    }

    /// Encode a BitString: BIT_BINARY_EXT with the unused low bits of the
    /// last byte cleared; a whole last byte (8 bits) is a plain binary.
    #[inline]
    fn write_bitstring(&mut self, py_bits: &Bound<'py, PyAny>) -> CodecResult<()> {
        let py_value = py_bits.getattr(intern!(self.py, "value_"))?;
        let data: &[u8] = py_value.cast::<PyBytes>()?.as_bytes();
        let last_byte_bits: u8 = py_bits
            .getattr(intern!(self.py, "last_byte_bits_"))?
            .extract()?;
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

/// Binaries of at least this many bytes are not copied into the encoder's
/// buffer but straight into the result (see `Encoder::into_bytes`).
const DEFER_BINARY: usize = 4096;

/// Copy `src` into `out` at `pos` and move `pos` past it; None or a `src`
/// that does not fit is an error (it cannot happen: `out` is sized from
/// the same parts).
fn put(out: &mut [u8], pos: &mut usize, src: Option<&[u8]>) -> PyResult<()> {
    let missing = || PyErr::from(CodecError::BadValue("encoder output does not add up"));
    let src = src.ok_or_else(missing)?;
    let end = pos.checked_add(src.len()).ok_or_else(missing)?;
    out.get_mut(*pos..end)
        .ok_or_else(missing)?
        .copy_from_slice(src);
    *pos = end;
    Ok(())
}

/// Non-ASCII strings of at least this many characters are encoded to
/// Latin-1 by CPython (one copy; the Rust loop took ten times as long).
/// Shorter ones stay in Rust: a string that is not Latin-1 makes CPython
/// raise, and the exception costs more than the loop.
const LATIN1_BY_PYTHON: usize = 1024;

/// `text.encode("latin-1")`, or None if a character is above 255.
fn latin1_bytes<'py>(text: &Bound<'py, PyString>) -> CodecResult<Option<Bound<'py, PyBytes>>> {
    let py = text.py();
    match text.call_method1(intern!(py, "encode"), (intern!(py, "latin-1"),)) {
        Ok(bytes) => Ok(Some(bytes.cast_into::<PyBytes>()?)),
        Err(e) if e.is_instance_of::<PyUnicodeEncodeError>(py) => Ok(None),
        Err(e) => Err(e.into()),
    }
}

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
