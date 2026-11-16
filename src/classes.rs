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

//! The Python classes of the `term` package that the codec builds and
//! recognises, imported once per process instead of once per call.

use pyo3::prelude::*;
use pyo3::sync::PyOnceLock;
use pyo3::types::PyType;

/// The term classes (TERM-24: importing them on every call cost more than
/// decoding a small term).
pub struct TermClasses {
    pub atom: Py<PyType>,
    pub strict_atom: Py<PyType>,
    pub improper_list: Py<PyType>,
    pub pid: Py<PyType>,
    pub port: Py<PyType>,
    pub export: Py<PyType>,
    pub fun: Py<PyType>,
    pub record: Py<PyType>,
    pub reference: Py<PyType>,
    pub bitstring: Py<PyType>,
}

// Filled on the first codec call; an import that fails is retried next call.
static CLASSES: PyOnceLock<TermClasses> = PyOnceLock::new();

// `py_codec_impl.generic_serialize_object`, for objects with no encoding of
// their own; imported only when the encoder first meets one.
static GENERIC_SERIALIZE: PyOnceLock<Py<PyAny>> = PyOnceLock::new();

/// One class from a module of the `term` package.
fn class(py: Python<'_>, module: &str, name: &str) -> PyResult<Py<PyType>> {
    Ok(py
        .import(module)?
        .getattr(name)?
        .cast_into::<PyType>()?
        .unbind())
}

/// The term classes, imported on first use.
pub fn term_classes(py: Python<'_>) -> PyResult<&'static TermClasses> {
    CLASSES.get_or_try_init(py, || {
        Ok(TermClasses {
            atom: class(py, "term.atom", "Atom")?,
            strict_atom: class(py, "term.atom", "StrictAtom")?,
            improper_list: class(py, "term.list", "ImproperList")?,
            pid: class(py, "term.pid", "Pid")?,
            port: class(py, "term.port", "Port")?,
            export: class(py, "term.fun", "Export")?,
            fun: class(py, "term.fun", "Fun")?,
            record: class(py, "term.record", "Record")?,
            reference: class(py, "term.reference", "Reference")?,
            bitstring: class(py, "term.bitstring", "BitString")?,
        })
    })
}

/// `py_codec_impl.generic_serialize_object`, imported on first use.
pub fn generic_serialize(py: Python<'_>) -> PyResult<&Bound<'_, PyAny>> {
    GENERIC_SERIALIZE
        .get_or_try_init(py, || {
            Ok::<_, PyErr>(
                py.import("term.py_codec_impl")?
                    .getattr("generic_serialize_object")?
                    .unbind(),
            )
        })
        .map(|f| f.bind(py))
}
