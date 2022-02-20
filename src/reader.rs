use std::{array::TryFromSliceError, io::Read};

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
            Err(ReadError)
        }
    }

    pub fn read(&mut self, n: usize) -> ReadResult<&'a [u8]> {
        let old_offset = self.offset;
        self.offset += n;
        if self.offset <= self.data.len() {
            Ok(&self.data[old_offset..self.offset])
        } else {
            Err(ReadError)
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

#[derive(Debug)]
pub struct ReadError;

impl From<TryFromSliceError> for ReadError {
    fn from(_: TryFromSliceError) -> Self {
        ReadError
    }
}
