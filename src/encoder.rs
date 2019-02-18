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

use byteorder::{WriteBytesExt, BigEndian};
use cpython::*;
use std::{i32, u8, u16};
use std::io::{Write};

use super::consts;
use super::errors::*;
use std::borrow::Cow;


pub struct Encoder<'a> {
  pub py: Python<'a>, // Python instance will live at least as long as Encoder
  pub data: Vec<u8>,
  pub encode_hook: Option<PyObject>,
  // A function py_codec_impl.generic_serialize_object used for unknown classes
  pub cached_generic_serialize_fn: Option<PyObject>,
}


impl<'a> Encoder<'a> {
  pub fn new(py: Python, opt: PyObject) -> CodecResult<Encoder> {
    let py_opts = if opt == py.None() {
      PyDict::new(py)
    } else {
      PyDict::extract(py, &opt)?
    };
    Ok(Encoder {
      py,
      data: Vec::with_capacity(32),
      encode_hook: py_opts.get_item(py, "encode_hook"),
      cached_generic_serialize_fn: None,
    })
  }


  pub fn encode(&mut self, term: &PyObject) -> CodecResult<()> {
    let type_name = term.get_type(self.py).name(self.py).into_owned();
    let type_name_ref: &str = type_name.as_ref();
    match type_name_ref {
      "int" => {
        return self.write_int(&term)
      },
      "float" => {
        let val: f64 = FromPyObject::extract(self.py, term)?;
        return self.write_float(val)
      },
      "list" => {
        let as_list = PyList::extract(self.py, &term)?;
        self.write_list_no_tail(&as_list);
        self.data.push(consts::TAG_NIL_EXT);
        return Ok(())
      },
      "tuple" => {
        let as_tup = PyTuple::extract(self.py, &term)?;
        self.write_tuple(&as_tup);
        return Ok(())
      },
      "dict" => {
        let as_dict = PyDict::extract(self.py, &term)?;
        self.write_dict(&as_dict);
        return Ok(())
      },
      "Atom" => return self.write_atom(&term),
      "str" => {
        let as_str = PyString::extract(self.py, &term)?;
        return self.write_str(&as_str)
      },
      "bool" => {
        let val: bool = FromPyObject::extract(self.py, &term)?;
        return self.write_atom_from_cow(
          if val { Cow::from("true") } else { Cow::from("false") }
        )
      },
      "NoneType" => return self.write_atom_from_cow(Cow::from("undefined")),
      "ImproperList" => {
        let elements0 = term.getattr(self.py, "elements_")?;
        let elements = PyList::extract(self.py, &elements0)?;
        let tail = term.getattr(self.py, "tail_")?;
        self.write_list_no_tail(&elements);
        return self.encode(&tail)
      },
      "Pid" => return self.write_pid(&term),
      "Reference" => return self.write_ref(&term),
      "bytes" => {
        let py_bytes = PyBytes::extract(self.py, &term)?;
        return self.write_binary(&py_bytes)
      },
      "BitString" => return self.write_bitstring(&term),
      //"Fun" => return self.write_fun(&term),
      other => return self.write_unknown_object(type_name_ref, &term)
    };
  }


  /// For unknown object, check whether encode_hook is set, encode what it returns.
  /// If no encode_hook was set, check whether object has ``__etf__(self)`` member.
  /// Else encode object as Tuple(b'ClassName', Dict(b'field', values)) trying
  ///   to avoid circular loops.
  fn write_unknown_object(&mut self, name: &str, py_term: &PyObject) -> CodecResult<()> {
    match &self.encode_hook {
      Some(ref h1) => {
        let repr1 = h1.call(self.py, (py_term, ), None)?;
        return self.encode(&repr1)
      },
      None => match py_term.getattr(self.py, "__etf__") {
        Ok(h2) => {
          let repr2 = h2.call(self.py, NoArgs, None)?;
          return self.encode(&repr2)
        },
        Err(_) => return self.write_generic_unknown_object(&py_term),
      },
    }
  }


  fn write_generic_unknown_object(&mut self, py_term: &PyObject) -> CodecResult<()> {
    let py_fn = match &self.cached_generic_serialize_fn {
      Some(ref a) => a.clone_ref(self.py),
      None => {
        let pyimpl_m = self.py.import("term.py_codec_impl")?;
        let generic_fn = pyimpl_m.get(self.py, "generic_serialize_object")?;
        self.cached_generic_serialize_fn = Some(generic_fn.clone_ref(self.py));
        generic_fn
      },
    };
    let result_pair = py_fn.call(self.py, (py_term, self.py.None()), None)?;
    let py_pair: PyTuple = PyTuple::extract(self.py, &result_pair)?;
    let result = py_pair.get_item(self.py, 0);
    return self.encode(&result)
  }


  /// Writes list tag with elements, but no tail element (NIL or other). Ensure
  /// that the calling code is writing either a NIL or a tail term.
  #[inline]
  fn write_list_no_tail(&mut self, list: &PyList) -> CodecResult<()> {
    let size = list.len(self.py);
    self.data.push(consts::TAG_LIST_EXT);
    self.data.write_u32::<BigEndian>(size as u32);

    for i in 0..size {
      let item = list.get_item(self.py, i);
      self.encode(&item);
    }
    Ok(())
  }


  #[inline]
  fn write_tuple(&mut self, tup: &PyTuple) -> CodecResult<()> {
    let size = tup.len(self.py);
    if size < u8::MAX as usize {
      self.data.push(consts::TAG_SMALL_TUPLE_EXT);
      self.data.push(size as u8);
    } else {
      self.data.push(consts::TAG_LARGE_TUPLE_EXT);
      self.data.write_u32::<BigEndian>(size as u32);
    }

    for i in 0..size {
      let item = tup.get_item(self.py, i);
      self.encode(&item);
    }
    Ok(())
  }


  /// Writes Erlang map from Python dict.
  #[inline]
  fn write_dict(&mut self, py_dict: &PyDict) -> CodecResult<()> {
    let size = py_dict.len(self.py);
    self.data.push(consts::TAG_MAP_EXT);
    self.data.write_u32::<BigEndian>(size as u32);

    for (py_key, py_value) in py_dict.items(self.py) {
      self.encode(&py_key);
      self.encode(&py_value);
    }
    Ok(())
  }


  #[inline]
  fn write_int(&mut self, val: &PyObject) -> CodecResult<()> {
    let size: u64 = val.call_method(self.py, "bit_length", NoArgs, None)?.extract(self.py)?;
    let size: u32 = (size / 8 + 1) as u32;
    if size <= 4 {
      let v: i64 = FromPyObject::extract(self.py, val)?;
      self.write_4byte_int(v)
    } else {
      self.write_arbitrary_int(val, size)
    }
  }

  fn write_arbitrary_int(&mut self, val: &PyObject, size: u32) -> CodecResult<()> {
    if size < 256 {
      self.data.push(consts::TAG_SMALL_BIG_EXT);
      self.data.push(size as u8);
    } else {
      self.data.push(consts::TAG_LARGE_BIG_EXT);
      self.data.write_u32::<BigEndian>(size);
    }

    let ltz: bool = val.call_method(self.py, "__lt__", (0, ), None)?.extract(self.py)?;
    if ltz {
      self.data.push(1 as u8); // we have a negative value
      // we make new object that we multiply with -1 to switch sign, so that we get a positive
      // value to pack
      let r: PyObject = val.call_method(self.py, "__mul__", (-1, ), None)?.extract(self.py)?;
      let b: PyBytes = r.call_method(self.py, "to_bytes", (size, "little"), None)?.extract(self.py)?;
      let data: &[u8] = b.data(self.py);
      self.data.write(data);
    } else {
      self.data.push( 0 as u8);
      let b: PyBytes = val.call_method(self.py, "to_bytes", (size, "little"), None)?.extract(self.py)?;
      let data: &[u8] = b.data(self.py);
      self.data.write(data);
    }
    Ok(())
  }

  #[inline]
  fn write_4byte_int(&mut self, val: i64) -> CodecResult<()> {
    if val >= 0 && val <= u8::MAX as i64 {
      self.data.push(consts::TAG_SMALL_UINT);
      self.data.push(val as u8);
    } else if val >= i32::MIN as i64
        && val <= i32::MAX as i64 {
      self.data.push(consts::TAG_INT);
      self.data.write_i32::<BigEndian>(val as i32);
    } else {
      return Err(CodecError::IntegerEncodingRange {i: val})
    }

    Ok(())
  }


  #[inline]
  fn write_float(&mut self, val: f64) -> CodecResult<()> {
    self.data.push(consts::TAG_NEW_FLOAT_EXT);
    self.data.write_f64::<BigEndian>(val);
    Ok(())
  }


  /// Encode a UTF-8 Atom
  #[inline]
  fn write_atom(&mut self, py_atom: &PyObject) -> CodecResult<()> {
    let py_text0 = py_atom.getattr(self.py, "text_")?;
    let py_text: PyString = PyString::extract(self.py, &py_text0)?;
    let text = py_text.to_string(self.py)?;
    self.write_atom_from_cow(text)
  }


  /// Helper which writes an atom from a PyString's Copy-on-write string
  fn write_atom_from_cow(&mut self, text: Cow<str>) -> CodecResult<()> {
    let byte_array: &[u8] = text.as_ref().as_ref();
    let str_byte_length: usize = byte_array.len();

    if str_byte_length <= u8::MAX as usize {
      self.data.push(consts::TAG_SMALL_ATOM_UTF8_EXT);
      self.data.push(str_byte_length as u8); // 8bit length
      self.data.write(byte_array); // write &[u8] string content
    } else if str_byte_length <= u16::MAX as usize {
      self.data.push(consts::TAG_ATOM_UTF8_EXT);
      self.data.write_u16::<BigEndian>(str_byte_length as u16); // 16bit length
      self.data.write(byte_array); // write &[u8] string content
    } else {
      return Err(CodecError::AtomTooLong)
    }

    Ok(())
  }


  /// Encode a UTF-8 string
  #[inline]
  fn write_str(&mut self, py_str: &PyString) -> CodecResult<()> {
    let text = py_str.to_string(self.py)?;
    let byte_array: &[u8] = text.as_ref().as_ref();
    let str_byte_length: usize = byte_array.len();
    let can_be_encoded_as_bytes = can_be_encoded_as_byte_string(&text);

    if str_byte_length <= u8::MAX as usize && can_be_encoded_as_bytes {
      // Create an optimised byte-array structure and push bytes
      self.data.push(consts::TAG_STRING_EXT);
      self.data.write_u16::<BigEndian>(str_byte_length as u16); // 16bit length
      self.data.write(byte_array); // write &[u8] string content
    } else {
      // Create a list structure and push each codepoint as an integer
      self.data.push(consts::TAG_LIST_EXT);
      let chars_count = text.chars().count();
      self.data.write_u32::<BigEndian>(chars_count as u32); // chars, not bytes!
      for (_i, ch) in text.char_indices() {
        self.write_4byte_int(ch as i64)?
      }
      self.data.push(consts::TAG_NIL_EXT) // list terminator
    }

    Ok(())
  }


  /// Encode a Pid
  #[inline]
  fn write_pid(&mut self, py_pid: &PyObject) -> CodecResult<()> {
    let node_name = PyString::extract(
      self.py, &py_pid.getattr(self.py, "node_name_")?
    )?;

    let py_id = py_pid.getattr(self.py, "id_")?;
    let id: u32 = FromPyObject::extract(self.py, &py_id)?;

    let py_serial = py_pid.getattr(self.py, "serial_")?;
    let serial: u32 = FromPyObject::extract(self.py, &py_serial)?;

    let py_creation = py_pid.getattr(self.py, "creation_")?;
    let creation: u8 = FromPyObject::extract(self.py, &py_creation)?;

    self.data.push(consts::TAG_PID_EXT);
    self.write_atom_from_cow(node_name.to_string(self.py)?);
    self.data.write_u32::<BigEndian>(id);
    self.data.write_u32::<BigEndian>(serial);
    self.data.push(creation);

    Ok(())
  }


  /// Encode a Reference
  #[inline]
  fn write_ref(&mut self, py_ref: &PyObject) -> CodecResult<()> {
    let node_name = PyString::extract(
      self.py, &py_ref.getattr(self.py, "node_name_")?
    )?;

    let py_id: PyBytes = PyBytes::extract(
      self.py, &py_ref.getattr(self.py, "id_")?
    )?;
    let id = py_id.data(self.py);

    let py_creation = py_ref.getattr(self.py, "creation_")?;
    let creation: u8 = FromPyObject::extract(self.py, &py_creation)?;

    self.data.push(consts::TAG_NEW_REF_EXT);
    self.data.write_u16::<BigEndian>((id.len() / 4) as u16);
    self.write_atom_from_cow(node_name.to_string(self.py)?);
    self.data.push(creation);
    self.data.write(id);

    Ok(())
  }


  /// Encode a binary (byte-string)
  #[inline]
  fn write_binary(&mut self, py_bytes: &PyBytes) -> CodecResult<()> {
    let data: &[u8] = py_bytes.data(self.py);
    self.data.push(consts::TAG_BINARY_EXT);
    self.data.write_u32::<BigEndian>(data.len() as u32);
    self.data.write(data);
    Ok(())
  }


  /// Encode a Binary bit-string (last byte has less than 8 bits)
  #[inline]
  fn write_bitstring(&mut self, py_bits: &PyObject) -> CodecResult<()> {
    let py_bytes = PyBytes::extract(
      self.py, &py_bits.getattr(self.py, "value_")?
    )?;
    let data: &[u8] = py_bytes.data(self.py);

    let py_lbb = py_bits.getattr(self.py, "last_byte_bits_")?;
    let last_byte_bits: u8 = FromPyObject::extract(self.py, &py_lbb)?;

    self.data.push(consts::TAG_BIT_BINARY_EXT);
    self.data.write_u32::<BigEndian>(data.len() as u32);
    self.data.push(last_byte_bits);
    self.data.write(data);

    Ok(())
  }

} // end impl


/// Checks first 65535 characters whether they are single-byte and are not
/// extended code points
fn can_be_encoded_as_byte_string(s: &str) -> bool {
  for (i, ch) in s.char_indices() {
    if i > u16::MAX as usize {
      return false // too long, so result is false
    }
    if ch as u32 > u8::MAX as u32 {
      return false // is a unicode codepoint with value larger than 255
    }
  }
  return true // will fit in a 255-byte latin-1 string
}
