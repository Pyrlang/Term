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

#![allow(unused)]

pub const ETF_VERSION_TAG: u8 = 131;

pub const TAG_ATOM_CACHE_REF: u8 = 82;
pub const TAG_ATOM_EXT: u8 = 100;
pub const TAG_ATOM_UTF8_EXT: u8 = 118;

pub const TAG_BINARY_EXT: u8 = 109;
pub const TAG_BIT_BINARY_EXT: u8 = 77;

pub const TAG_COMPRESSED: u8 = 80;

pub const TAG_EXPORT_EXT: u8 = 113;

pub const TAG_FLOAT_EXT: u8 = 99;

pub const TAG_INT: u8 = 98;

pub const TAG_LARGE_BIG_EXT: u8 = 111;
pub const TAG_LARGE_TUPLE_EXT: u8 = 105;
pub const TAG_LIST_EXT: u8 = 108;
pub const TAG_LOCAL_EXT: u8 = 121;

pub const TAG_MAP_EXT: u8 = 116;

pub const TAG_NEW_FLOAT_EXT: u8 = 70;
pub const TAG_NEW_FUN_EXT: u8 = 112;
pub const TAG_NEW_REF_EXT: u8 = 114;
pub const TAG_NIL_EXT: u8 = 106;

pub const TAG_PID_EXT: u8 = 103;
pub const TAG_PORT_EXT: u8 = 102;
pub const TAG_RECORD_EXT: u8 = 67;
pub const TAG_REFERENCE_EXT: u8 = 101;

pub const TAG_SMALL_ATOM_EXT: u8 = 115;
pub const TAG_SMALL_ATOM_UTF8_EXT: u8 = 119;
pub const TAG_SMALL_BIG_EXT: u8 = 110;
pub const TAG_SMALL_UINT: u8 = 97;
pub const TAG_SMALL_TUPLE_EXT: u8 = 104;
pub const TAG_STRING_EXT: u8 = 107;

pub const TAG_NEW_PID_EXT: u8 = 88;
pub const TAG_NEW_PORT_EXT: u8 = 89;
pub const TAG_NEWER_REF_EXT: u8 = 90;
pub const TAG_V4_PORT_EXT: u8 = 120;

/// Largest creation of the old tags with an 8-bit creation (PID_EXT,
/// PORT_EXT, REFERENCE_EXT, NEW_REFERENCE_EXT): ERTS_MAX_TINY_CREATION.
pub const MAX_TINY_CREATION: u8 = 3;

/// Most characters in an atom (MAX_ATOM_CHARACTERS).
pub const MAX_ATOM_CHARS: usize = 255;

/// Most ID words in a reference (ERTS_MAX_REF_NUMBERS, OTP 24+).
pub const MAX_REF_WORDS: u16 = 5;

/// The first ID word of REFERENCE_EXT and NEW_REFERENCE_EXT is below this
/// (MAX_REFERENCE: 18 bits).
pub const MAX_OLD_REF_FIRST_WORD: u32 = 1 << 18;
