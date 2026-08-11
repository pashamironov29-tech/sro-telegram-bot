#!/usr/bin/env python3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from doc_qa import warmup, find_relevant_chunks

print(warmup())
for c in find_relevant_chunks("контрольный комитет состав", 3):
    print("-", c["title"])
