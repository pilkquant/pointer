"""Wrapper for native extension."""

import ctypes
import cffi

ffi = cffi.FFI()
ffi.cdef("int printf(const char *, ...);")


def call_native():
    """Call into native code."""
    lib = ffi.dlopen(None)
    lib.printf(b"Hello from native!\n")
