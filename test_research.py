"""Parser and graph tests; generated certificate/inventories are test fixtures only."""
import copy
import base64
import struct
from pathlib import Path
from unittest.mock import patch
import datetime
import unittest
from cryptography import x509
from cryptography.hazmat.primitives import hashes,serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from defusedxml.common import DefusedXmlException
import research

class ResearchTests(unittest.TestCase):
    def inventory(self):
        return {'authorized':True,'entry':'a','nodes':[{'id':i,'label':i,'kind':'fixture'} for i in 'abc'],'links':[{'source':'a','target':'b','status':'observed','evidence':'fixture inventory record 1'},{'source':'b','target':'c','status':'hypothesis','evidence':''}]}
    def test_conditional_graph_not_compromise(self):
        data=self.inventory();result=research.analyze_topology(data)
        self.assertEqual(result['derived_reachable_ids'],['a','b'])
        self.assertEqual(result['conditional_reachable_ids'],['a','b','c'])
        self.assertEqual(result['hypothesis_only_reachable_ids'],['c'])
        self.assertEqual(result['execution'],'none');self.assertEqual(result['outbound_requests'],0)
        data['max_hops']=1
        self.assertEqual(research.analyze_topology(data)['conditional_reachable_ids'],['a','b'])
    def test_invalid_inventory(self):
        for mutation in (lambda d:d.update(authorized=False),lambda d:d.update(max_hops=7),lambda d:d['links'][0].update(evidence=''),lambda d:d['links'][0].update(target='missing'),lambda d:d['nodes'].append(d['nodes'][0]),lambda d:d.update(nodes=d['nodes']*34)):
            data=self.inventory();mutation(data)
            with self.assertRaises(ValueError):research.analyze_topology(data)
    def test_reference_url_no_fetch(self):
        self.assertEqual(research.inspect_reference_url('https://example.org/docs')['outbound_requests'],0)
        for value in ('https://user:pass@example.org','file:///etc/passwd'):
            with self.assertRaises(ValueError):research.inspect_reference_url(value)
    def test_safe_xml(self):
        self.assertEqual(research.inspect_xml(b'<root><item/></root>')['elements'],2)
        with self.assertRaises(DefusedXmlException):
            research.inspect_xml(b'<!DOCTYPE r [<!ENTITY x SYSTEM "file:///etc/passwd">]><r>&x;</r>')
    def test_certificate_generated_fixture(self):
        key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
        name=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'test-fixture.invalid')])
        now=datetime.datetime.now(datetime.timezone.utc)
        cert=x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key()).serial_number(1).not_valid_before(now).not_valid_after(now+datetime.timedelta(days=1)).sign(key,hashes.SHA256())
        result=research.certificate_metadata(cert.public_bytes(serialization.Encoding.PEM))
        self.assertEqual(result['subject'],'CN=test-fixture.invalid');self.assertEqual(result['outbound_requests'],0)
        self.assertEqual(len(result['sha256_fingerprint']),64)

    def test_supplied_html_capture_and_dns_are_offline(self):
        result=research.html_metadata(b'<title>Fixture</title><p>Reference</p><script>excluded()</script>')
        self.assertNotIn('excluded',result['text_excerpt'])
        self.assertEqual(result['outbound_requests'],0)
        capture=struct.pack('<IHHIIII',0xa1b2c3d4,2,4,0,0,65535,1)+struct.pack('<IIII',1,0,4,4)+b'TEST'
        self.assertEqual(research.inspect_capture(capture)['examined_packets'],1)
        with self.assertRaises(ValueError):research.inspect_capture(b'\x1f\x8bcompressed fixture')
        message=b'\x00\x01\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00'
        self.assertEqual(research.inspect_dns(message)['message_id'],1)
        self.assertEqual(research.inspect_dns(message)['outbound_requests'],0)

    def test_optional_native_libraries_fail_explicitly_and_registry_is_observed(self):
        for name,operation in [('capstone',lambda:research.disassemble(b'\x90')),('pefile',lambda:research.inspect_pe(b'MZ')),('ELFFile',lambda:research.inspect_elf(b'\x7fELF')),('yara',lambda:research.scan_signatures(b'fixture','rule fixture {condition: true}'))]:
            with patch.object(research,name,None):
                with self.assertRaisesRegex(ValueError,'unavailable'):operation()
        status=research.library_status()
        self.assertEqual(len(status['libraries']),11)
        self.assertTrue(all('installed_version' in row for row in status['libraries']))

    def test_supplied_inspection_api_bounds_and_no_paths(self):
        workspace=research.ResearchWorkspace(Path('/unused-test-path'))
        result=workspace.inspect({'kind':'html','data_base64':base64.b64encode(b'<p>fixture</p>').decode()})
        self.assertIn('fixture',result['text_excerpt'])
        for request in ({'kind':'elf','path':'/etc/passwd'}, {'kind':'html','data_base64':'bad!!'}, {'kind':'html','data_base64':'A'*20001}, {'kind':'shell','data_base64':'Zml4dHVyZQ=='}):
            with self.assertRaises(ValueError):workspace.inspect(request)

if __name__=='__main__':unittest.main()
