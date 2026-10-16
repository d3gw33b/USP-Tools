# Minimal Win64 emulator for calling pure functions inside a Windows PE executable, using unicorn.
# Imported CRT math functions are serviced in Python (float32 via numpy / libm via ctypes).
import struct, ctypes, ctypes.util, math, lief
import numpy as np
from unicorn import *
from unicorn.x86_const import *

libm = ctypes.CDLL(ctypes.util.find_library('m'))
def _f(name, nargs=1, dbl=False):
    fn = getattr(libm, name); t = ctypes.c_double if dbl else ctypes.c_float
    fn.restype = t; fn.argtypes = [t] * nargs; return fn
F32 = {n: _f(n) for n in ['roundf', 'floorf', 'ceilf', 'sinf', 'cosf', 'tanf', 'sqrtf', 'expf', 'exp2f', 'logf', 'log2f',
                          'log10f', 'atanf', 'asinf', 'acosf']}
F32.update({n: _f(n, 2) for n in ['fmodf', 'powf', 'atan2f']})
F64 = {n: _f(n, 1, True) for n in ['sqrt', 'exp2', 'log2', 'log', 'exp', 'cos', 'floor', 'log10', 'round']}
F64.update({n: _f(n, 2, True) for n in ['pow']})

STK, STK_SZ = 0x7f0000000000, 0x400000
HEAP, HEAP_SZ = 0x7e0000000000, 0x10000000
IMP = 0x7d0000000000
TLS = 0x7c0000000000
RET = 0x7b0000000000

class Emu:
    def __init__(self, exe):
        pe = lief.PE.parse(exe); self.base = base = pe.optional_header.imagebase
        mu = self.mu = Uc(UC_ARCH_X86, UC_MODE_64)
        hi = max(base + s.virtual_address + s.virtual_size for s in pe.sections)
        mu.mem_map(base, (hi - base + 0xfff) & ~0xfff)
        for s in pe.sections: mu.mem_write(base + s.virtual_address, bytes(s.content))
        self.image = (base, hi)
        for a, n in ((STK, STK_SZ), (HEAP, HEAP_SZ), (IMP, 0x100000), (TLS, 0x100000), (RET, 0x1000)):
            mu.mem_map(a, n)
        mu.mem_write(IMP, b'\xc3' * 0x100000)
        self.imp = {}
        i = 0
        for lib in pe.imports:
            for e in lib.entries:
                if e.iat_address:
                    fake = IMP + i * 16; i += 1
                    mu.mem_write(base + e.iat_address, struct.pack('<Q', fake)); self.imp[fake] = e.name or f'ord{e.ordinal}'
        # TLS: gs:[0x58] -> array of per-module TLS block pointers; index from __tls_index (whatever it is) all -> one block
        mu.mem_write(TLS, struct.pack('<Q', TLS + 0x1000) * 0x200)
        mu.mem_write(TLS + 0x58, struct.pack('<Q', TLS + 0x8000))
        mu.mem_write(TLS + 0x8000, struct.pack('<Q', TLS + 0x10000) * 0x100)
        mu.reg_write(UC_X86_REG_GS_BASE, TLS)
        self.heap = HEAP; self.hooks = {}; self.trace_unknown = True
        mu.hook_add(UC_HOOK_CODE, self._imp_hook, begin=IMP, end=IMP + 0x100000)
        self.hookset = set()

    # ---------- memory helpers
    def alloc(self, n, align=16):
        self.heap = (self.heap + align - 1) & ~(align - 1); a = self.heap; self.heap += n
        self.mu.mem_write(a, b'\0' * n); return a
    def reset_heap(self): self.heap = HEAP
    def w(self, a, b): self.mu.mem_write(a, b)
    def r(self, a, n): return bytes(self.mu.mem_read(a, n))
    def wf(self, a, *fs): self.w(a, struct.pack(f'<{len(fs)}f', *fs))
    def rf(self, a, n=1): return struct.unpack(f'<{n}f', self.r(a, 4 * n))
    def cstr(self, a, n=256): return self.r(a, n).split(b'\0')[0].decode('latin1')

    def hook(self, va, fn):
        """replace function at va by python fn(emu) -> rax (int) or ('f', float)"""
        self.hooks[va] = fn
        if va not in self.hookset:
            self.hookset.add(va); self.mu.hook_add(UC_HOOK_CODE, self._fn_hook, begin=va, end=va)

    def _ret(self, val):
        mu = self.mu
        if isinstance(val, tuple) and val[0] == 'f':
            mu.reg_write(UC_X86_REG_XMM0, struct.unpack('<I', struct.pack('<f', val[1]))[0])
        elif isinstance(val, tuple) and val[0] == 'd':
            mu.reg_write(UC_X86_REG_XMM0, struct.unpack('<Q', struct.pack('<d', val[1]))[0])
        elif val is not None:
            mu.reg_write(UC_X86_REG_RAX, val & 0xffffffffffffffff)
        rsp = mu.reg_read(UC_X86_REG_RSP); ra = struct.unpack('<Q', self.r(rsp, 8))[0]
        mu.reg_write(UC_X86_REG_RSP, rsp + 8); mu.reg_write(UC_X86_REG_RIP, ra)

    def xf(self, i):
        return struct.unpack('<f', struct.pack('<I', self.mu.reg_read(UC_X86_REG_XMM0 + i) & 0xffffffff))[0]
    def xd(self, i):
        return struct.unpack('<d', struct.pack('<Q', self.mu.reg_read(UC_X86_REG_XMM0 + i) & 0xffffffffffffffff))[0]
    def arg(self, i):
        return self.mu.reg_read([UC_X86_REG_RCX, UC_X86_REG_RDX, UC_X86_REG_R8, UC_X86_REG_R9][i])

    def _fn_hook(self, mu, addr, size, ud):
        if addr in self.hooks: self._ret(self.hooks[addr](self))

    def _imp_hook(self, mu, addr, size, ud):
        n = self.imp.get(addr)
        if n is None: return
        if n in F32:
            k = 2 if n in ('fmodf', 'powf', 'atan2f') else 1
            v = F32[n](*[self.xf(i) for i in range(k)]); self._ret(('f', v))
        elif n in F64:
            k = 2 if n == 'pow' else 1
            self._ret(('d', F64[n](*[self.xd(i) for i in range(k)])))
        elif n == 'toupper':
            c = self.arg(0) & 0xff; self._ret(ord(chr(c).upper()) if 97 <= c <= 122 else c)
        elif n in ('memcpy', 'memmove'):
            d, s, k = self.arg(0), self.arg(1), self.arg(2); self.w(d, self.r(s, k)); self._ret(d)
        elif n == 'memset':
            d, c, k = self.arg(0), self.arg(1), self.arg(2); self.w(d, bytes([c & 0xff]) * k); self._ret(d)
        elif n == 'strncat':
            d, s, k = self.arg(0), self.arg(1), self.arg(2)
            dl = len(self.r(d, 4096).split(b'\0')[0]); sb = self.r(s, 4096).split(b'\0')[0][:k]
            self.w(d + dl, sb + b'\0'); self._ret(d)
        elif n == 'strlen':
            self._ret(len(self.r(self.arg(0), 65536).split(b'\0')[0]))
        else:
            raise RuntimeError(f'unhandled import {n} called')

    # ---------- calling
    def call(self, va, *args, ret='i', limit=50_000_000):
        """args: ints (or addresses) and floats; Win64 positional convention."""
        mu = self.mu
        sp = STK + STK_SZ - 0x1000
        stack_args = args[4:]
        sp -= 8 * max(len(stack_args), 0) + 0x20
        sp &= ~0xf
        for i, a in enumerate(stack_args):
            if isinstance(a, float): mu.mem_write(sp + 0x20 + 8 * i, struct.pack('<fI', a, 0))
            else: mu.mem_write(sp + 0x20 + 8 * i, struct.pack('<Q', a & 0xffffffffffffffff))
        sp -= 8; mu.mem_write(sp, struct.pack('<Q', RET))
        mu.reg_write(UC_X86_REG_RSP, sp)
        IR = [UC_X86_REG_RCX, UC_X86_REG_RDX, UC_X86_REG_R8, UC_X86_REG_R9]
        for i, a in enumerate(args[:4]):
            if isinstance(a, float):
                mu.reg_write(UC_X86_REG_XMM0 + i, struct.unpack('<I', struct.pack('<f', a))[0])
            else: mu.reg_write(IR[i], a & 0xffffffffffffffff)
        mu.emu_start(va, RET, count=limit)
        if mu.reg_read(UC_X86_REG_RIP) != RET:
            raise RuntimeError(f'did not return; rip={mu.reg_read(UC_X86_REG_RIP):#x}')
        if ret == 'f': return self.xf(0)
        if ret == 'd': return self.xd(0)
        return mu.reg_read(UC_X86_REG_RAX)
