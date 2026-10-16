# asm.py VA [VA...] : disassemble function(s) from a PE executable by recursive descent (follows jumps, not calls)
import os, sys, re, struct, lief, capstone, csv
pe = lief.PE.parse(os.environ["PE_EXE"]); base = pe.optional_header.imagebase
text = next(s for s in pe.sections if s.name == '.text')
T0 = base + text.virtual_address; TB = bytes(text.content)
md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
names = {}
for r in (csv.reader(open(os.environ['SYMBOL_CSV'])) if os.environ.get('SYMBOL_CSV') else []):  # optional local symbol CSV: addr,_,name
    try: names[int(r[0], 16)] = r[2]
    except: pass
def one(va):
    seen = {}; work = [va]
    while work:
        a = work.pop()
        while a not in seen:
            i = next(md.disasm(TB[a - T0:a - T0 + 16], a), None)
            if i is None: break
            seen[a] = i
            m = i.mnemonic
            if m.startswith('j') and i.op_str.startswith('0x'):
                work.append(int(i.op_str, 16))
                if m == 'jmp': break
            elif m == 'jmp' or m.startswith('ret') or m == 'int3': break
            a += i.size
    print(f'; {va:#x} {names.get(va, "")}  ({len(seen)} insns)')
    prev = None
    for a in sorted(seen):
        i = seen[a]
        if prev is not None and a != prev: print('    ; ---')
        extra = ''
        if i.mnemonic in ('call', 'jmp') and i.op_str.startswith('0x'):
            t = int(i.op_str, 16); extra = '  ; ' + names.get(t, '')
        m = re.search(r'\[rip ([+-]) (0x[0-9a-f]+)\]', i.op_str)
        if m:
            t = a + i.size + (int(m.group(2), 16) * (1 if m.group(1) == '+' else -1))
            try:
                raw = bytes(pe.get_content_from_virtual_address(t, 16))
                fl = struct.unpack('<4f', raw); 
                extra += f'  ; [{t:#x}] {names.get(t, "")} f={fl[0]:.9g} ({fl[1]:.6g},{fl[2]:.6g},{fl[3]:.6g}) q={struct.unpack("<Q", raw[:8])[0]:#x}'
            except Exception: extra += f'  ; [{t:#x}]'
        print(f'{a:x}  {i.mnemonic:8s} {i.op_str}{extra}')
        prev = a + i.size
for a in sys.argv[1:]: one(int(a, 16))
