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

use super::errors::*;

/// Get dict value with string key, expect it to be string too, or return
/// the default value.
pub fn get_str_opt(py: Python, opts: &PyDict,
                   optname: &str, default: &str) -> CodecResult<String>
{
  match opts.get_item(py, optname) {
    Some(val) => {
      let py_str: PyString = PyString::extract(py, &val)?;
      let s = py_str.to_string_lossy(py).into_owned();
      Ok(s)
    },
    None => {
      Ok(default.to_string())
    },
  }
}


/// Given a dict or a possibly None, return dict
pub fn maybe_dict(py: Python, dict_or_none: PyObject) -> PyDict {
  if dict_or_none == py.None() {
    PyDict::new(py)
  } else {
    PyDict::extract(py, &dict_or_none).unwrap()
  }
}


#[derive(Eq, PartialEq)]
pub enum AtomRepresentation {
  TermAtom,
  Bytes,
  Str,
}


#[derive(Eq, PartialEq)]
pub enum ByteStringRepresentation {
  Bytes,
  Str,
  IntList
}


/// Option: "atom" => "bytes" | "str" | "Atom" (as Atom class, default)
pub fn get_atom_opt(py: Python, opts1: &PyDict) -> CodecResult<AtomRepresentation>
{
  let opt_s = get_str_opt(py, &opts1, "atom", "Atom")?;
  match opt_s.as_ref() {
    "bytes" => Ok(AtomRepresentation::Bytes),
    "str" => Ok(AtomRepresentation::Str),
    "Atom" => Ok(AtomRepresentation::TermAtom),
    other => {
      let txt = format!(
        "'atom' option is '{}' while expected: bytes, str, Atom", other);
      Err(CodecError::BadOptions {txt})
    }
  }
}


/// Option: "byte_string" => "bytes" | "str" | "int_list" (default: str)
pub fn get_byte_str_opt(py: Python, opts1: &PyDict) -> CodecResult<ByteStringRepresentation>
{
  let opt_s: String = get_str_opt(py, &opts1, "byte_string", "str")?;
  match opt_s.as_ref() {
    "bytes" => Ok(ByteStringRepresentation::Bytes),
    "str" => Ok(ByteStringRepresentation::Str),
    "int_list" => Ok(ByteStringRepresentation::IntList),
    other => {
      let txt = format!(
        "'byte_string' option is '{}' while expected: bytes, str", other);
      Err(CodecError::BadOptions {txt})
    }
  }
}
