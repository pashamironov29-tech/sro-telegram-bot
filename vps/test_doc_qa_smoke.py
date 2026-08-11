#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from doc_qa import answer_from_document

q = "что такое градостроительный регламент"
r = answer_from_document(q)
print("ok", r.get("ok"))
print((r.get("text") or "")[:700])
