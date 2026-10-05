#!/usr/bin/env python3
"""Patch QuickFIX 1.15.1's x86-only atomic implementation for Apple ARM."""

from __future__ import annotations

import argparse
from pathlib import Path


OLD = """    static int atomic_exchange_and_add(int * pw, int dv)
    {
      // int r = *pw;
      // *pw += dv;
      // return r;

      int r;

      __asm__ __volatile__
        (
          \"lock\\n\\t\"
          \"xadd %1, %0\":
          \"+m\"(*pw), \"=r\"(r) : // outputs (%0, %1)
          \"1\"(dv) : // inputs (%2 == %1)
          \"memory\", \"cc\" // clobbers
        );

      return r;
    }
"""

NEW = """    static int atomic_exchange_and_add(int * pw, int dv)
    {
      return __atomic_fetch_add(pw, dv, __ATOMIC_SEQ_CST);
    }
"""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    args = parser.parse_args()
    target = args.source / "C++" / "AtomicCount.h"
    text = target.read_text()
    if NEW in text:
        print(f"Already patched: {target}")
        return 0
    if OLD not in text:
        raise RuntimeError(f"Unexpected AtomicCount.h; refusing blind patch: {target}")
    target.write_text(text.replace(OLD, NEW, 1))
    print(f"Patched ARM atomic primitive: {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
