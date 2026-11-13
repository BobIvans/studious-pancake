#!/usr/bin/env python3
"""Synthetic layout tests; NOT live proof."""
import base64
import unittest
from probe_structural import decode_fields, decode_captured_account, layout

def fixture(schema: dict, discriminator: str) -> bytes:
    total = schema.get("account_size_bytes", schema.get("prefix_len_bytes"))
    raw=bytearray(total)
    raw[:8]=bytes(schema[discriminator])
    fields=schema.get("fields",schema.get("prefix_fields"))
    for index, f in enumerate(fields):
        if f["type"]=="pubkey":
            val=bytes([index+1])*32
        elif f["type"].startswith("bytes"):
            val=bytes(f["bytes"])
        else:
            val=(index+1).to_bytes(f["bytes"],"little",signed=False)
        raw[f["offset"]:f["offset"]+f["bytes"]]=val
    return bytes(raw)

class TestStructural(unittest.TestCase):
    def test_jupiter_positive_structural_no_capacity(self):
        s=layout("jupiter_token_reserve_layout.json")
        raw=fixture(s,"discriminator")
        result=decode_captured_account({"owner":s["owner_program_id"],"executable":False,"data":[base64.b64encode(raw).decode(),"base64"]},"jupiter_lend")
        self.assertEqual(result["status"],"STRUCTURAL_ONLY_NOT_FLASH_CAPACITY")
        self.assertEqual(result["raw_length"],192)
        self.assertEqual(result["qualified_edges"],[])
        self.assertFalse(result["send_enabled"])
        self.assertIn("mint",result["structural"])
    def test_kamino_positive_prefix_only(self):
        s=layout("kamino_reserve_prefix_layout.json")
        raw=fixture(s,"reserve_discriminator")+bytes(2048)
        result=decode_captured_account({"owner":s["official_program_id"],"executable":False,"data":[base64.b64encode(raw).decode(),"base64"]},"kamino")
        self.assertEqual(result["status"],"STRUCTURAL_ONLY_NOT_FLASH_CAPACITY")
        self.assertIn("total_available_amount",result["structural"])
        self.assertNotIn("flash_loan_fee",result["structural"])
    def test_bad_owner(self):
        s=layout("jupiter_token_reserve_layout.json")
        raw=fixture(s,"discriminator")
        with self.assertRaisesRegex(ValueError,"OWNER"):
            decode_captured_account({"owner":"wrong","executable":False,"data":[base64.b64encode(raw).decode(),"base64"]},"jupiter_lend")
    def test_tampered_discriminator(self):
        s=layout("jupiter_token_reserve_layout.json")
        raw=bytearray(fixture(s,"discriminator"));raw[0]^=0xff
        with self.assertRaisesRegex(ValueError,"DISCRIMINATOR"):
            decode_fields(bytes(raw),s,exact_length=True)
    def test_short_account(self):
        s=layout("kamino_reserve_prefix_layout.json")
        raw=fixture(s,"reserve_discriminator")[:-1]
        with self.assertRaisesRegex(ValueError,"SIZE"):
            decode_fields(raw,s,exact_length=False)
    def test_bad_encoding(self):
        s=layout("jupiter_token_reserve_layout.json")
        with self.assertRaisesRegex(ValueError,"ENCODING"):
            decode_captured_account({"owner":s["owner_program_id"],"executable":False,"data":["dummy","hex"]},"jupiter_lend")

if __name__=="__main__":
    unittest.main()
