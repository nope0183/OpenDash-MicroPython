'''Runs before main.py on every boot.'''
import gc
import machine

try:
    machine.freq(240_000_000)
except Exception:
    pass
gc.collect()
