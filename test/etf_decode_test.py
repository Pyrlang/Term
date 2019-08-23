import unittest

from term import py_codec_impl as py_impl
import term.native_codec_impl as native_impl
from term.atom import Atom, StrictAtom
from term.pid import Pid
from term.reference import Reference
from term.fun import Fun
from term.list import list_to_unicode_str


class TestETFDecode(unittest.TestCase):
    def test_decode_atom_py(self):
        self._decode_atom(py_impl)
        self._decode_atom_utf8(py_impl)

    def test_decode_atom_native(self):
        self._decode_atom(native_impl)
        self._decode_atom_utf8(native_impl)

    def _decode_atom(self, codec):
        """ Try an atom 'hello' encoded as Latin1 atom (16-bit length)
            or small atom (8bit length)
        """
        b1 = bytes([131, py_impl.TAG_ATOM_EXT,
                    0, 5,
                    104, 101, 108, 108, 111])
        (t1, tail1) = codec.binary_to_term(b1, None)
        self.assertTrue(isinstance(t1, Atom), "Result must be Atom object")
        self.assertEqual(t1, "hello")
        self.assertEqual(tail1, b'')

        b2 = bytes([131, py_impl.TAG_SMALL_ATOM_EXT,
                    5,
                    104, 101, 108, 108, 111])
        (t2, tail2) = codec.binary_to_term(b2, None)
        self.assertTrue(isinstance(t2, Atom), "Result must be Atom object")
        self.assertEqual(t2, "hello")
        self.assertEqual(tail2, b'')

    def _decode_atom_utf8(self, codec):
        b1 = bytes([131, py_impl.TAG_ATOM_UTF8_EXT,
                    0, 6,
                    108, 195, 164, 103, 101, 116])
        (t1, tail1) = codec.binary_to_term(b1, None)
        self.assertTrue(isinstance(t1, Atom), "Result must be Atom object")
        self.assertTrue(isinstance(t1, str), "Result must be str")
        self.assertEqual(t1, u"läget")
        self.assertEqual(tail1, b'')

    # ----------------

    def test_decode_atom_as_string_py(self):
        self._decode_atom_as_string(py_impl)

    def test_decode_atom_as_string_native(self):
        self._decode_atom_as_string(native_impl)

    def _decode_atom_as_string(self, codec):
        """ Try an atom 'hello' to a Python string """
        b1 = bytes([131, py_impl.TAG_ATOM_EXT,
                    0, 5,
                    104, 101, 108, 108, 111])
        (t2, tail2) = codec.binary_to_term(b1, {"atom": "str"})
        self.assertTrue(isinstance(t2, str),
                        "Expected str, have: " + t2.__class__.__name__)
        self.assertEqual(t2, "hello")
        self.assertEqual(tail2, b'')

        (t3, tail3) = codec.binary_to_term(b1, {"atom": "bytes"})
        self.assertTrue(isinstance(t3, bytes),
                        "Expected bytes, have: " + t3.__class__.__name__)
        self.assertEqual(t3, b'hello')
        self.assertEqual(tail3, b'')

    # ----------------

    def test_decode_atom_as_strict_py(self):
        self._decode_atom_as_strict(py_impl)

    def test_decode_atom_as_strict_native(self):
        self._decode_atom_as_strict(native_impl)

    def _decode_atom_as_strict(self, codec):
        b1 = bytes([131, py_impl.TAG_ATOM_EXT,
                    0, 5,
                    104, 101, 108, 108, 111])
        (t1, tail1) = codec.binary_to_term(b1, {"atom": "StrictAtom"})
        self.assertTrue(isinstance(t1, StrictAtom), "Result must be StrictAtom "
                                                    "got {}".format(type(t1)))
        self.assertEqual(t1, "hello")
        self.assertEqual(tail1, b'')

        b2 = bytes([131, py_impl.TAG_SMALL_ATOM_EXT,
                    5,
                    104, 101, 108, 108, 111])
        (t2, tail2) = codec.binary_to_term(b2, {"atom": "StrictAtom"})
        self.assertTrue(isinstance(t2, StrictAtom), "Result must be Atom "
                                                    "object")
        self.assertEqual(t2, "hello")
        self.assertEqual(tail2, b'')

    # ----------------

    def test_decode_atom_custom_callable_py(self):
        self._decode_atom_custom_callable(py_impl)
        self._decode_atom_custom_class(py_impl)

    def test_decode_atom_custom_callable_native(self):
        self._decode_atom_custom_callable(native_impl)
        self._decode_atom_custom_class(native_impl)

    def _decode_atom_custom_callable(self, codec):
        b1 = bytes([131, py_impl.TAG_ATOM_EXT,
                    0, 5,
                    104, 101, 108, 108, 111])

        a_fun = lambda x: bytes(x.encode('utf8'))
        (t1, tail1) = codec.binary_to_term(b1, {"atom_call": a_fun})
        self.assertTrue(isinstance(t1, bytes))
        self.assertEqual(t1, b"hello")
        self.assertEqual(tail1, b'')

    def _decode_atom_custom_class(self, codec):

        b1 = bytes([131, py_impl.TAG_ATOM_EXT,
                    0, 5,
                    104, 101, 108, 108, 111])

        class A(str):
            pass

        class B:
            def __init__(self, text):
                self._text = text

        (t1, tail1) = codec.binary_to_term(b1, {"atom_call": str})
        self.assertTrue(isinstance(t1, str))
        self.assertEqual(t1, "hello")
        self.assertEqual(tail1, b'')

        (t2, tail2) = codec.binary_to_term(b1, {"atom_call": A})
        self.assertTrue(isinstance(t2, str))
        self.assertTrue(isinstance(t2, A))
        self.assertEqual(t1, "hello")
        self.assertEqual(tail1, b'')

        (t3, tail3) = codec.binary_to_term(b1, {"atom_call": B})
        self.assertTrue(isinstance(t3, B))
        self.assertEqual(t3._text, "hello")
        self.assertEqual(tail1, b'')

    # ----------------

    def test_decode_str_py(self):
        self._decode_str_ascii(py_impl)
        self._decode_str_unicode(py_impl)
        self._decode_str_int_list(py_impl)

    def test_decode_str_native(self):
        self._decode_str_ascii(native_impl)
        self._decode_str_unicode(native_impl)
        self._decode_str_int_list(py_impl)

    def _decode_str_ascii(self, codec):
        """ A string with bytes, encoded as optimized byte array. """
        b1 = bytes([131, py_impl.TAG_STRING_EXT,
                    0, 5,
                    104, 101, 108, 108, 111])
        (t1, tail1) = codec.binary_to_term(b1, None)
        self.assertTrue(isinstance(t1, str), "Result must be str")
        self.assertEqual(t1, "hello")
        self.assertEqual(tail1, b'')

        (t2, tail2) = codec.binary_to_term(b1, {"byte_string": "bytes"})
        self.assertTrue(isinstance(t2, bytes),
                        "Result must be bytes, got " + t2.__class__.__name__)
        self.assertEqual(t2, b"hello")
        self.assertEqual(tail2, b'')


    def _decode_str_int_list(self, codec):
        """ A string with bytes, encoded as optimized byte array. """
        b1 = bytes([131, py_impl.TAG_STRING_EXT,
                    0, 5,
                    104, 101, 108, 108, 111])
        (t1, tail1) = codec.binary_to_term(b1, {"byte_string": "int_list"})
        self.assertEqual(t1, [104, 101, 108, 108, 111])
        self.assertEqual(tail1, b'')

    def _decode_str_unicode(self, codec):
        """ A string with emoji, encoded as a list of unicode integers. """
        b1 = bytes([131, py_impl.TAG_LIST_EXT,
                    0, 0, 0, 3,  # length
                    py_impl.TAG_INT, 0, 0, 38, 34,  # 32-bit radiation hazard
                    py_impl.TAG_SMALL_INT, 32,      # 8-bit space (32)
                    py_impl.TAG_INT, 0, 0, 38, 35,  # 32-bit bio-hazard
                    py_impl.TAG_NIL_EXT  # list tail: NIL
                    ])
        (t1, tail) = codec.binary_to_term(b1, None)
        self.assertTrue(isinstance(t1, list), "Result must be a list")
        self.assertEqual(tail, b'')
        self.assertEqual(list_to_unicode_str(t1), u"☢ ☣")

    # ----------------

    def test_decode_pid_py(self):
        self._decode_pid(py_impl)

    def test_decode_pid_native(self):
        self._decode_pid(native_impl)

    def _decode_pid(self, codec):
        """ Try a pid """
        data = bytes([131, 103, 100, 0, 13, 101, 114, 108, 64, 49, 50, 55, 46,
                      48, 46, 48, 46, 49, 0, 0, 0, 64, 0, 0, 0, 0, 1])
        (val, tail) = codec.binary_to_term(data, None)
        self.assertTrue(isinstance(val, Pid))
        self.assertEqual(tail, b'')

    # ----------------

    def test_decode_ref_py(self):
        self._decode_ref(py_impl)

    def test_decode_ref_native(self):
        self._decode_ref(native_impl)

    def _decode_ref(self, codec):
        """ Try a reference """
        b1 = bytes([131, 114, 0, 3, 100, 0, 13, 101, 114, 108, 64, 49, 50,
                    55, 46, 48, 46, 48, 46, 49, 1, 0, 0, 1, 58, 0, 0, 0, 2,
                    0, 0, 0, 0])
        (t1, tail) = codec.binary_to_term(b1, None)
        self.assertTrue(isinstance(t1, Reference))
        self.assertEqual(tail, b'')

    # ----------------

    def test_decode_tuple_py(self):
        self._decode_tuple(py_impl)

    def test_decode_tuple_native(self):
        self._decode_tuple(native_impl)

    def _decode_tuple(self, codec):
        """ Try decode some tuple values """
        data1 = bytes([131, py_impl.TAG_SMALL_TUPLE_EXT,
                       2,
                       py_impl.TAG_SMALL_INT, 1,
                       py_impl.TAG_ATOM_EXT, 0, 2, 111, 107])
        (val1, tail1) = codec.binary_to_term(data1, None)
        self.assertEqual((1, Atom("ok")), val1)
        self.assertEqual(tail1, b'')

        data2 = bytes([131, py_impl.TAG_LARGE_TUPLE_EXT,
                       0, 0, 0, 2,
                       py_impl.TAG_SMALL_INT, 1,
                       py_impl.TAG_ATOM_EXT, 0, 2, 111, 107])
        (val2, tail2) = codec.binary_to_term(data2, None)
        self.assertEqual((1, Atom("ok")), val2)
        self.assertEqual(tail2, b'')

        # Empty tuple
        data3 = bytes([131, py_impl.TAG_SMALL_TUPLE_EXT, 0])
        (val3, tail3) = codec.binary_to_term(data3, None)
        self.assertEqual((), val3)
        self.assertEqual(tail3, b'')


# ----------------

    def test_decode_list_py(self):
        self._decode_list(py_impl)

    def test_decode_list_native(self):
        self._decode_list(native_impl)

    def _decode_list(self, codec):
        """ Try decode some list values """
        data1 = bytes([131, py_impl.TAG_NIL_EXT])
        (val1, tail1) = codec.binary_to_term(data1, None)
        self.assertEqual([], val1)
        self.assertEqual(tail1, b'')

        # Test data is [1, ok]
        data2 = bytes([131, py_impl.TAG_LIST_EXT,
                       0, 0, 0, 2,
                       py_impl.TAG_SMALL_INT, 1,
                       py_impl.TAG_ATOM_EXT, 0, 2, 111, 107,
                       py_impl.TAG_NIL_EXT])
        (val2, tail2) = codec.binary_to_term(data2, None)
        self.assertTrue(isinstance(val2, list),
                        "Expected list, got: %s (%s)"
                        % (val2.__class__.__name__, val2))
        self.assertEqual(val2, [1, Atom("ok")])
        self.assertEqual(tail2, b'')

    # ----------------

    def test_decode_map_py(self):
        self._decode_map(py_impl)

    def test_decode_map_native(self):
        self._decode_map(native_impl)

    def _decode_map(self, codec):
        """ Try a map #{1 => 2, ok => error} """
        data = bytes([131,
                      py_impl.TAG_MAP_EXT, 0, 0, 0, 2,
                      py_impl.TAG_SMALL_INT, 1,
                      py_impl.TAG_SMALL_INT, 2,
                      py_impl.TAG_ATOM_EXT, 0, 2, 111, 107,
                      py_impl.TAG_ATOM_EXT, 0, 5, 101, 114, 114, 111, 114])
        (val, tail) = codec.binary_to_term(data, None)
        self.assertTrue(isinstance(val, dict))
        self.assertEqual(val, {1: 2, Atom("ok"): Atom("error")})
        self.assertEqual(tail, b'')

    # ----------------

    def test_float_py(self):
        self._float(py_impl)

    def test_float_native(self):
        self._float(native_impl)

    def _float(self, codec):
        """ Try decode a prepared double Pi """
        data = bytes([py_impl.ETF_VERSION_TAG,
                      py_impl.TAG_NEW_FLOAT_EXT,  # a 8-byte IEEE double
                      64, 9, 33, 251, 84, 68, 45, 17])
        negative = bytes([py_impl.ETF_VERSION_TAG,
                          py_impl.TAG_NEW_FLOAT_EXT,
                          192, 71, 188, 40, 245, 194, 143, 92])
        (val, tail) = codec.binary_to_term(data, None)
        (nval, ntail) = codec.binary_to_term(negative, None)
        self.assertEqual(val, 3.14159265358979)
        self.assertEqual(tail, b'')
        self.assertEqual(nval, -47.47)
        self.assertEqual(ntail, b'')

    # ----------------
    def test_float_in_packed_type_py(self):
        self._float_in_packed_type(py_impl)

    def test_float_in_packed_type_native(self):
        self._float_in_packed_type(native_impl)

    def _float_in_packed_type(self, codec):
        example = bytes([py_impl.ETF_VERSION_TAG, py_impl.TAG_SMALL_TUPLE_EXT, 3,
                         py_impl.TAG_NEW_FLOAT_EXT, 64, 9, 30, 184, 81, 235, 133, 31,
                         py_impl.TAG_SMALL_INT, 13,
                         py_impl.TAG_NEW_FLOAT_EXT, 64, 1, 194, 143, 92, 40, 245, 195])
        val, tail = codec.binary_to_term(example, None)
        self.assertEqual(val, (3.14, 13, 2.22))
        self.assertEqual(tail, b'')

    # ----------------

    def test_decode_int_py(self):
        self._decode_int(py_impl)

    def test_decode_int_native(self):
        self._decode_int(native_impl)

    def _decode_int(self, codec):
        positive = bytes([131, 98, 0, 0, 18, 139])  # 4747
        negative = bytes([131, 98, 255, 255, 237, 117])  # -4747
        (positive_val, positive_tail) = codec.binary_to_term(positive, None)
        (negative_val, negative_tail) = codec.binary_to_term(negative, None)
        self.assertEqual(positive_val, 4747)
        self.assertEqual(positive_tail, b'')
        self.assertEqual(negative_val, -4747)
        self.assertEqual(negative_tail, b'')

    # ----------------

    def test_decode_small_big_py(self):
        self._decode_small_big(py_impl)

    def test_decode_small_big_native(self):
        self._decode_small_big(native_impl)

    def _decode_small_big(self, codec):
        positive = bytes([131, 110, 9, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1])  # 2 ** 64
        negative = bytes([131, 110, 9, 1, 0, 0, 0, 0, 0, 0, 0, 0, 1])  # - (2 ** 64)
        (positive_val, positive_tail) = codec.binary_to_term(positive, None)
        (negative_val, negative_tail) = codec.binary_to_term(negative, None)
        self.assertEqual(positive_val, 2 ** 64)
        self.assertEqual(positive_tail, b'')
        self.assertEqual(negative_val, -(2 ** 64))
        self.assertEqual(negative_tail, b'')

    # ----------------

    def test_decode_small_big_random_bytes_py(self):
        self._decode_small_big_random_bytes(py_impl)

    def test_decode_small_big_random_bytes_native(self):
        self._decode_small_big_random_bytes(native_impl)

    def _decode_small_big_random_bytes(self, codec):
        positive = bytes([py_impl.ETF_VERSION_TAG, py_impl.TAG_SMALL_BIG_EXT, 13, 0,
                          210, 10, 63, 78, 238, 224, 115, 195, 246, 15, 233, 142, 1
                          ])
        negative = bytes([py_impl.ETF_VERSION_TAG, py_impl.TAG_SMALL_BIG_EXT, 13, 1,
                          210, 10, 63, 78, 238, 224, 115, 195, 246, 15, 233, 142, 1
                          ])
        (positive_val, positive_tail) = codec.binary_to_term(positive, None)
        (negative_val, negative_tail) = codec.binary_to_term(negative, None)
        self.assertEqual(positive_val, 123456789012345678901234567890)
        self.assertEqual(positive_tail, b'')
        self.assertEqual(negative_val, -123456789012345678901234567890)
        self.assertEqual(negative_tail, b'')

    # ----------------

    def test_decode_large_big_py(self):
        self._decode_large_big(py_impl)

    def test_decode_large_big_native(self):
        self._decode_large_big(native_impl)

    def _decode_large_big(self, codec):
        positive = bytes([131, 111, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
                          0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
                          0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
                          0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
                          0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
                          0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
                          0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
                          0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
                          0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
                          0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1])  # 2 ** 2040
        negative = bytes([131, 111, 0, 0, 1, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
                          0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
                          0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
                          0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
                          0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
                          0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
                          0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
                          0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
                          0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
                          0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1])  # - (2 ** 2040)
        (positive_val, positive_tail) = codec.binary_to_term(positive, None)
        (negative_val, negative_tail) = codec.binary_to_term(negative, None)
        self.assertEqual(positive_val, 2 ** 2040)
        self.assertEqual(positive_tail, b'')
        self.assertEqual(negative_val, -(2 ** 2040))
        self.assertEqual(negative_tail, b'')

    # ----------------

    def test_decode_binary_py(self):
        self._decode_binary(py_impl)

    def test_decode_binary_native(self):
        self._decode_binary(native_impl)

    def _decode_binary(self, codec):
        """ Decode binary to term.Binary and to Python bytes and compare.
            Binary is <<34>>.
        """
        data1 = bytes([131, 109, 0, 0, 0, 1, 34])
        (val1, tail1) = codec.binary_to_term(data1, None)
        self.assertEqual(val1, b'"')
        self.assertEqual(tail1, b'')

    # ----------------

    def test_decode_hook_py(self):
        self._decode_int(py_impl)

    def test_decode_hook_native(self):
        self._decode_int(native_impl)

    def _decode_int(self, codec):
        def negate_hook(x):
            return -x

        positive = bytes([131, 98, 0, 0, 18, 139])  # 4747
        (negative_val, tail) = codec.binary_to_term(positive, {'decode_hook': {'int': negate_hook}})
        self.assertEqual(negative_val, -4747)

    # ----------------

    def test_decode_fun_py(self):
        self._decode_fun(py_impl)

    def test_decode_fun_native(self):
        self._decode_fun(native_impl)

    def _decode_fun(self, codec):
        data = bytes([131, 112, 0, 0, 0, 72, 0, 37, 73, 174, 126, 251, 115,
                      143, 183, 98, 224, 72, 249, 253, 111, 254, 159, 0, 0,
                      0, 0, 0, 0, 0, 1, 100, 0, 5, 116, 101, 115, 116, 49,
                      97, 0, 98, 1, 42, 77, 115, 103, 100, 0, 13, 110, 111,
                      110, 111, 100, 101, 64, 110, 111, 104, 111, 115, 116,
                      0, 0, 0, 58, 0, 0, 0, 0, 0, 97, 123])
        (val, tail) = codec.binary_to_term(data, None)
        self.assertTrue(isinstance(val, Fun))
        self.assertEqual(tail, b'')

    # ----------------

    def test_decode_compressed_py(self):
        self._decode_compressed(py_impl)

    def test_decode_compressed_native(self):
        self._decode_compressed(native_impl)

    def _decode_compressed(self, codec):
        """ tries to decode compressed data
        """
        compressed_data = b'\x83P\x00\x00\x01\xc4x\x9c5\x90QR\x831\x08\x84\xebM\xf6\x00\x9d\x9eB\xdf|\xf5\x00\x98\xd0\xcaL\x08i\x02\x9d\xde\xce\xabI\xfc\xf5-\x04Xv?=\x9d^\xbe\xdfm\xb2B\xc6\nE\xb5f\x13K\x1c\xa4\xecg\x14\xeb\x8b\x8b\xb3\xc7\x04U\x19\xb2\xa4H\xbf\x81\x9bdwq\xcd\r\xb0\xc4R\xabp\xd6\x91\xdb\xd2\x8bT\xa9\xd1\x1d\xe1h\xf4\x99\xfa`?\xb4\x19J\xb7N\xa0&\xf7\xa0\x0b>\x1c\xdcES\x1c*\xfb\xf1\xc8\x92\xf4\x8c{\xc8B\xb7\xe53*\xf8\xc9\xb3\x88\x93\x8buDk\xa4\xc5\x0e\xe5=\x94\xa6\xf6\xa5_I\x199\x0c\xa6t\xae\xe9\xc9\x8e\x04y\xca/x\xdd\x92\x14\xce\x90\x19\xe9\xe4\x08+\x1d\x93\xc7\xe4/\xee\x95g&\xcf\x8f\x87\xb5\x18y\x8e\xd3N&\x05\xaf\xc5(\xd2\xda?\xa2\x0c\x14\xb8\xc6M\xc8\xd1\xb7!\x0c\x9aY\xc4\xbc\xe0\xedYx8\xc7\xe6\x98\x0c\xac\x14\xe2\x92s%\x86T\xf2\xbd\x91)\xc64\xa9\xdc7\xc5M*\x8f\x96h\x83vn\xd8\xf5\x9a\x98\t\x95\x17\xcf\xddUk\xdb\x06m@\x928\xd6\x1f\xd7\xd0\x0b~\x00'
        decoded_data = b'Lorem ipsum dolor sit amet, consectetur adipisicing elit, sed do eiusmod tempor incididunt ut labore et dolore magna aliqua. Ut enim ad minim veniam, quis nostrud exercitation ullamco laboris nisi ut aliquip ex ea commodo consequat. Duis aute irure dolor in reprehenderit in voluptate velit esse cillum dolore eu fugiat nulla pariatur. Excepteur sint occaecat cupidatat non proident, sunt in culpa qui officia deserunt mollit anim id est laborum. '
        (val, tail) = codec.binary_to_term(compressed_data, None)
        self.assertTrue(val == decoded_data)
        self.assertEqual(tail, b'')

    # ----------------

    def test_decode_hook_compressed_py(self):
        self._decode_hook_compressed(py_impl)

    def test_decode_hook_compressed_native(self):
        self._decode_hook_compressed(native_impl)

    def _decode_hook_compressed(self, codec):
        """ tries to decode a compressed string, and convert it to unicode using
            a decode_hook.
        """
        def unicode_hook(x):
            return x.decode()

        compressed_data = b'\x83P\x00\x00\x01\xc4x\x9c5\x90QR\x831\x08\x84\xebM\xf6\x00\x9d\x9eB\xdf|\xf5\x00\x98\xd0\xcaL\x08i\x02\x9d\xde\xce\xabI\xfc\xf5-\x04Xv?=\x9d^\xbe\xdfm\xb2B\xc6\nE\xb5f\x13K\x1c\xa4\xecg\x14\xeb\x8b\x8b\xb3\xc7\x04U\x19\xb2\xa4H\xbf\x81\x9bdwq\xcd\r\xb0\xc4R\xabp\xd6\x91\xdb\xd2\x8bT\xa9\xd1\x1d\xe1h\xf4\x99\xfa`?\xb4\x19J\xb7N\xa0&\xf7\xa0\x0b>\x1c\xdcES\x1c*\xfb\xf1\xc8\x92\xf4\x8c{\xc8B\xb7\xe53*\xf8\xc9\xb3\x88\x93\x8buDk\xa4\xc5\x0e\xe5=\x94\xa6\xf6\xa5_I\x199\x0c\xa6t\xae\xe9\xc9\x8e\x04y\xca/x\xdd\x92\x14\xce\x90\x19\xe9\xe4\x08+\x1d\x93\xc7\xe4/\xee\x95g&\xcf\x8f\x87\xb5\x18y\x8e\xd3N&\x05\xaf\xc5(\xd2\xda?\xa2\x0c\x14\xb8\xc6M\xc8\xd1\xb7!\x0c\x9aY\xc4\xbc\xe0\xedYx8\xc7\xe6\x98\x0c\xac\x14\xe2\x92s%\x86T\xf2\xbd\x91)\xc64\xa9\xdc7\xc5M*\x8f\x96h\x83vn\xd8\xf5\x9a\x98\t\x95\x17\xcf\xddUk\xdb\x06m@\x928\xd6\x1f\xd7\xd0\x0b~\x00'
        decoded_data = 'Lorem ipsum dolor sit amet, consectetur adipisicing elit, sed do eiusmod tempor incididunt ut labore et dolore magna aliqua. Ut enim ad minim veniam, quis nostrud exercitation ullamco laboris nisi ut aliquip ex ea commodo consequat. Duis aute irure dolor in reprehenderit in voluptate velit esse cillum dolore eu fugiat nulla pariatur. Excepteur sint occaecat cupidatat non proident, sunt in culpa qui officia deserunt mollit anim id est laborum. '

        (val, tail) = codec.binary_to_term(compressed_data, {'decode_hook': {'bytes': unicode_hook}})
        self.assertTrue(isinstance(val, str))
        self.assertTrue(val == decoded_data)
        self.assertEqual(tail, b'')


    # ----------------

    def test_special_py(self):
        self._special(py_impl)

    def test_special_native(self):
        self._special(native_impl)

    def _special(self, codec):
        """ Test decoding true, false, undefined=None """
        data1 = bytes([py_impl.ETF_VERSION_TAG,
                       py_impl.TAG_SMALL_ATOM_UTF8_EXT, 4]) + b'true'
        (val1, tail1) = codec.binary_to_term(data1, None)
        self.assertEqual(val1, True)
        self.assertEqual(tail1, b'')

        data2 = bytes([py_impl.ETF_VERSION_TAG,
                       py_impl.TAG_SMALL_ATOM_UTF8_EXT, 5]) + b'false'
        (val2, tail2) = codec.binary_to_term(data2, None)
        self.assertEqual(val2, False)
        self.assertEqual(tail2, b'')

        data3 = bytes([py_impl.ETF_VERSION_TAG,
                       py_impl.TAG_SMALL_ATOM_UTF8_EXT, 9]) + b'undefined'
        (val3, tail3) = codec.binary_to_term(data3, None)
        self.assertEqual(val3, None)
        self.assertEqual(tail3, b'')


if __name__ == '__main__':
    unittest.main()
