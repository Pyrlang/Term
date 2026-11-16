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

impl<'a> Reader<'a> {
    pub fn read_u32(&mut self) -> ReadResult<u32> {
        Ok(u32::from_be_bytes(self.read(4)?.try_into()?))
    }

    pub fn read_u64(&mut self) -> ReadResult<u64> {
        Ok(u64::from_be_bytes(self.read(8)?.try_into()?))
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
        self.read(1)?
            .first()
            .copied()
            .ok_or(ReadError::BufferTooShort)
    }

    pub fn read_with<T: Readable>(&mut self) -> ReadResult<T> {
        T::do_read(self)
    }

    pub fn peek(&self) -> ReadResult<u8> {
        self.data
            .get(self.offset)
            .copied()
            .ok_or(ReadError::BufferTooShort)
    }

    /// The next `n` bytes; on failure the reader does not move.
    pub fn read(&mut self, n: usize) -> ReadResult<&'a [u8]> {
        let end = self
            .offset
            .checked_add(n)
            .ok_or(ReadError::BufferTooShort)?;
        let slice = self
            .data
            .get(self.offset..end)
            .ok_or(ReadError::BufferTooShort)?;
        self.offset = end;
        Ok(slice)
    }

    pub fn rest(&self) -> &'a [u8] {
        self.data.get(self.offset..).unwrap_or_default()
    }

    /// How many bytes are left to read.
    pub fn remaining(&self) -> usize {
        self.data.len().saturating_sub(self.offset)
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
