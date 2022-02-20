// Copyright 2022, Erlang Solutions Ltd, and S2HC Sweden AB
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

use thiserror::Error;

use std::array::TryFromSliceError;
use std::io::{BufRead, Read};

type ReadResult<T> = Result<T, ReadError>;

pub struct Reader<'a> {
    data: &'a [u8],
    offset: usize,
}

impl<'a> From<&'a [u8]> for Reader<'a> {
    fn from(data: &'a [u8]) -> Self {
        Self { data, offset: 0 }
    }
}

impl<'a> From<&'a Vec<u8>> for Reader<'a> {
    fn from(data: &'a Vec<u8>) -> Self {
        Self { data, offset: 0 }
    }
}

// impl<'a> From<&'a [u8]> for Reader<'a> {
//     fn from(data: &'a [u8]) -> Self {
//         Self { data, offset: 0 }
//     }
// }

impl<'a> Reader<'a> {
    pub fn read_u32(&mut self) -> ReadResult<u32> {
        Ok(u32::from_be_bytes(self.read(4)?.try_into()?))
    }

    pub fn read_i32(&mut self) -> ReadResult<i32> {
        Ok(i32::from_be_bytes(self.read(4)?.try_into()?))
    }

    pub fn read_u16(&mut self) -> ReadResult<u16> {
        Ok(u16::from_be_bytes(self.read(2)?.try_into()?))
    }

    pub fn read_f64(&mut self) -> ReadResult<f64> {
        Ok(f64::from_be_bytes(self.read(8)?.try_into()?))
    }

    pub fn read_u8(&mut self) -> ReadResult<u8> {
        Ok(self.read(1)?[0])
    }

    pub fn read_with<T: Readable>(&mut self) -> ReadResult<T> {
        T::do_read(self)
    }

    pub fn peek(&self) -> ReadResult<u8> {
        if self.offset < self.data.len() {
            Ok(self.data[self.offset])
        } else {
            Err(ReadError::BufferTooShort)
        }
    }

    pub fn read(&mut self, n: usize) -> ReadResult<&'a [u8]> {
        let old_offset = self.offset;
        self.offset += n;
        if self.offset <= self.data.len() {
            Ok(&self.data[old_offset..self.offset])
        } else {
            Err(ReadError::BufferTooShort)
        }
    }

    pub fn rest(&self) -> &'a [u8] {
        &self.data[self.offset..]
    }

    // pub fn done(&self) -> bool {
    //     self.data.len() <= self.offset
    // }
}

impl<'a> Read for Reader<'a> {
    fn read(&mut self, buf: &mut [u8]) -> std::io::Result<usize> {
        let to_read = (self.data.len() - self.offset).min(buf.len());
        let slice = self.read(to_read).unwrap();
        buf.copy_from_slice(slice);
        Ok(to_read)
    }
}

impl<'a> BufRead for Reader<'a> {
    fn fill_buf(&mut self) -> std::io::Result<&[u8]> {
        Ok(self.rest())
    }

    fn consume(&mut self, amt: usize) {
        self.offset += amt;
    }
}

pub trait Readable
where
    Self: Sized,
{
    fn do_read(reader: &mut Reader) -> ReadResult<Self>;
}

impl Readable for u32 {
    fn do_read(reader: &mut Reader) -> ReadResult<Self> {
        reader.read_u32()
    }
}
impl Readable for u16 {
    fn do_read(reader: &mut Reader) -> ReadResult<Self> {
        reader.read_u16()
    }
}
impl Readable for u8 {
    fn do_read(reader: &mut Reader) -> ReadResult<Self> {
        reader.read_u8()
    }
}
impl Readable for f64 {
    fn do_read(reader: &mut Reader) -> ReadResult<Self> {
        reader.read_f64()
    }
}
impl Readable for i32 {
    fn do_read(reader: &mut Reader) -> ReadResult<Self> {
        reader.read_i32()
    }
}

#[derive(Debug, Error)]
pub enum ReadError {
    #[error("Buffer too short")]
    BufferTooShort,
    #[error("Buffer too short to read value")]
    BufferTooShortForValue(#[from] TryFromSliceError),
}
