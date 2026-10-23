"""Evidence-backed research workspace; no implicit collection or execution."""
import hashlib
import json
import io
from importlib import metadata
from pathlib import Path
import httpx
import networkx as nx
from cryptography import x509
from defusedxml import ElementTree

# Optional analysis dependencies are explicit so a missing native wheel does not
# prevent the dashboard from starting. Availability is shown to the admin.
try:
    from scapy.utils import RawPcapReader
except ImportError:
    RawPcapReader=None
try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup=None
try:
    import dns.message
except ImportError:
    dns=None
try:
    import capstone
except ImportError:
    capstone=None
try:
    import pefile
except ImportError:
    pefile=None
try:
    from elftools.elf.elffile import ELFFile
except ImportError:
    ELFFile=None
try:
    import yara
except ImportError:
    yara=None


def library_status():
    catalog=json.loads(Path(__file__).with_name('research-libraries.json').read_text())
    for item in catalog['libraries']:
        try:item['installed_version']=metadata.version(item['package'])
        except metadata.PackageNotFoundError:item['installed_version']=None
        available={'scapy':RawPcapReader,'beautifulsoup4':BeautifulSoup,'dnspython':dns,
                   'capstone':capstone,'pefile':pefile,'pyelftools':ELFFile,'yara-python':yara}.get(item['package'],True)
        item['available']=available is not None and item['installed_version'] is not None
        item['pinned_version_installed']=item['installed_version']==item['version']
    return catalog


def _bytes(value,limit=2_000_000):
    if not isinstance(value,bytes) or not 1<=len(value)<=limit:
        raise ValueError(f'Supply 1 through {limit} explicit bytes')
    return {'source_sha256':hashlib.sha256(value).hexdigest(),'execution':'none','outbound_requests':0}


def _require(module,name):
    if module is None:
        raise ValueError(name+' is unavailable; install requirements-research.txt in the project environment')


def html_metadata(value):
    result=_bytes(value,524288);_require(BeautifulSoup,'beautifulsoup4')
    page=BeautifulSoup(value,'html.parser')
    for element in page(['script','style','noscript','template']):element.decompose()
    title=page.title.get_text(' ',strip=True)[:300] if page.title else None
    text=page.get_text(' ',strip=True)
    return {**result,'title':title,'text_excerpt':text[:2000],'text_truncated':len(text)>2000,
            'limitation':'Supplied HTML parsed as reference text; embedded resources and links were not fetched.'}


def inspect_capture(value):
    result=_bytes(value);_require(RawPcapReader,'scapy')
    # Accept uncompressed capture bytes only; gzip could inflate beyond the byte bound.
    if value[:4] not in (b'\xd4\xc3\xb2\xa1',b'\xa1\xb2\xc3\xd4',b'\x4d\x3c\xb2\xa1',b'\xa1\xb2\x3c\x4d',b'\x0a\x0d\x0d\x0a'):
        raise ValueError('An uncompressed PCAP/PCAPNG capture is required')
    count,total=0,0
    reader=RawPcapReader(io.BytesIO(value))
    try:
        for packet,_ in reader:
            if count==1000:return {**result,'examined_packets':count,'captured_bytes':total,'truncated':True}
            count+=1;total+=len(packet)
    finally:reader.close()
    return {**result,'examined_packets':count,'captured_bytes':total,'truncated':False,
            'limitation':'Capture metadata only; no sniffing, packet transmission or endpoint contact.'}


def inspect_dns(value):
    result=_bytes(value,65535);_require(dns,'dnspython')
    message=dns.message.from_wire(value)
    return {**result,'message_id':message.id,'flags':message.flags,
            'questions':[question.to_text()[:500] for question in message.question[:20]],
            'answers':[answer.to_text()[:1000] for answer in message.answer[:20]],
            'limitation':'Supplied wire message parsed offline; no DNS resolver or zone transfer was contacted.'}


def disassemble(value,architecture='x86_64'):
    result=_bytes(value,65536);_require(capstone,'capstone')
    choices={'x86':(capstone.CS_ARCH_X86,capstone.CS_MODE_32),
             'x86_64':(capstone.CS_ARCH_X86,capstone.CS_MODE_64),
             'arm64':(capstone.CS_ARCH_ARM64,capstone.CS_MODE_ARM)}
    if architecture not in choices:raise ValueError('Choose x86, x86_64 or arm64')
    engine=capstone.Cs(*choices[architecture])
    rows=[{'offset':instruction.address,'mnemonic':instruction.mnemonic,'operands':instruction.op_str[:300]}
          for instruction in engine.disasm(value,0,count=200)]
    return {**result,'architecture':architecture,'instructions':rows,
            'limitation':'At most 200 decoded instructions; supplied bytes were never executed or emulated.'}


def inspect_pe(value):
    result=_bytes(value);_require(pefile,'pefile')
    image=pefile.PE(data=value,fast_load=True)
    try:return {**result,'machine':image.FILE_HEADER.Machine,'entry_rva':image.OPTIONAL_HEADER.AddressOfEntryPoint,
                'declared_sections':image.FILE_HEADER.NumberOfSections,
                'sections':[{'name':section.Name.rstrip(b'\x00').decode('ascii','replace'),
                             'virtual_size':section.Misc_VirtualSize,'raw_size':section.SizeOfRawData}
                            for section in image.sections[:128]],
                'limitation':'Static PE header metadata only; imports and code were not executed.'}
    finally:image.close()


def inspect_elf(value):
    result=_bytes(value);_require(ELFFile,'pyelftools')
    image=ELFFile(io.BytesIO(value))
    count=image.num_sections()
    return {**result,'architecture':image.get_machine_arch(),'bits':image.elfclass,
            'endianness':'little' if image.little_endian else 'big','type':image['e_type'],
            'entry':image['e_entry'],'declared_sections':count,
            'sections':[{'type':image.get_section(i)['sh_type'],'bytes':image.get_section(i)['sh_size']} for i in range(min(count,128))],
            'limitation':'Static ELF metadata only; supplied binaries were never loaded or executed.'}


def scan_signatures(value,rules):
    result=_bytes(value);_require(yara,'yara-python')
    if not isinstance(rules,str) or not 1<=len(rules)<=16384:raise ValueError('Supply at most 16384 characters of YARA source')
    compiled=yara.compile(source=rules,includes=False,error_on_warning=True)
    matches=compiled.match(data=value,timeout=2)
    return {**result,'rules_sha256':hashlib.sha256(rules.encode()).hexdigest(),
            'matches':[{'rule':match.rule,'namespace':match.namespace,'tags':match.tags[:20]} for match in matches[:100]],
            'limitation':'Signature matches are leads, not malware verdicts. No process scans, includes or file execution.'}


def inspect_reference_url(value):
    if not isinstance(value,str) or len(value)>4096:
        raise ValueError('Bounded reference URL required')
    url=httpx.URL(value)
    if url.scheme not in ('http','https') or not url.host or url.username or url.password:
        raise ValueError('HTTP URL without credentials required')
    return {'url':str(url),'host':url.host,'scheme':url.scheme,'port':url.port,'outbound_requests':0,'limitations':['Syntax inspection only; endpoint not contacted.']}


def certificate_metadata(pem):
    if not isinstance(pem,bytes) or len(pem)>65536:
        raise ValueError('Supplied PEM bytes limited to 65536')
    cert=x509.load_pem_x509_certificate(pem)
    from cryptography.hazmat.primitives import hashes
    return {'subject':cert.subject.rfc4514_string(),'issuer':cert.issuer.rfc4514_string(),'serial_number':str(cert.serial_number),'not_valid_before':cert.not_valid_before_utc.isoformat(),'not_valid_after':cert.not_valid_after_utc.isoformat(),'sha256_fingerprint':cert.fingerprint(hashes.SHA256()).hex(),'source_sha256':hashlib.sha256(pem).hexdigest(),'outbound_requests':0,'limitations':['Supplied certificate parsed; trust, revocation and live endpoint identity not verified.']}


def inspect_xml(value):
    if not isinstance(value,bytes) or len(value)>262144:
        raise ValueError('Supplied XML bytes limited to 262144')
    root=ElementTree.fromstring(value,forbid_dtd=True,forbid_entities=True,forbid_external=True)
    return {'root_tag':root.tag,'elements':sum(1 for _ in root.iter()),'source_sha256':hashlib.sha256(value).hexdigest(),'execution':'none','outbound_requests':0}


def analyze_topology(value):
    if not isinstance(value,dict) or set(value)-{'authorized','nodes','links','entry','max_hops'} or value.get('authorized') is not True:
        raise ValueError('Explicitly authorized inventory schema required')
    nodes,links,entry=value.get('nodes'),value.get('links'),value.get('entry')
    hops=value.get('max_hops',6)
    if type(hops) is not int or not 0<=hops<=6:
        raise ValueError('Hop limit must be 0..6')
    if not isinstance(nodes,list) or not 1<=len(nodes)<=100 or not isinstance(links,list) or len(links)>300:
        raise ValueError('Inventory limited to 100 nodes and 300 links')
    def text(item,key):
        result=item.get(key)
        if not isinstance(result,str) or not result.strip() or len(result)>2048:
            raise ValueError('Invalid inventory string: '+key)
        return result
    graph,observed=nx.DiGraph(),nx.DiGraph()
    clean_nodes,clean_links=[],[]
    for node in nodes:
        if not isinstance(node,dict) or set(node)!={'id','label','kind'}:
            raise ValueError('Node requires id, label, kind')
        clean={key:text(node,key) for key in ('id','label','kind')}
        if clean['id'] in graph:raise ValueError('Duplicate node identity')
        clean_nodes.append(clean);graph.add_node(clean['id']);observed.add_node(clean['id'])
    if not isinstance(entry,str) or entry not in graph:raise ValueError('Entry must identify a node')
    seen=set()
    for link in links:
        if not isinstance(link,dict) or set(link)!={'source','target','status','evidence'}:
            raise ValueError('Link requires source, target, status, evidence')
        source,target=text(link,'source'),text(link,'target')
        if source not in graph or target not in graph or (source,target) in seen:
            raise ValueError('Invalid or duplicate directed relation')
        if link['status'] not in ('observed','hypothesis') or not isinstance(link['evidence'],str) or len(link['evidence'])>2048:
            raise ValueError('Invalid relation status or evidence')
        if link['status']=='observed' and not link['evidence'].strip():raise ValueError('Observed relations require evidence')
        seen.add((source,target));graph.add_edge(source,target)
        if link['status']=='observed':observed.add_edge(source,target)
        clean_links.append(dict(link))
    reachable=nx.single_source_shortest_path_length(observed,entry,cutoff=hops)
    conditional=nx.single_source_shortest_path_length(graph,entry,cutoff=hops)
    source=json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()
    return {'nodes':clean_nodes,'links':clean_links,'entry':entry,'max_hops':hops,'derived_reachable_ids':sorted(reachable),'conditional_reachable_ids':sorted(conditional),'hypothesis_only_reachable_ids':sorted(set(conditional)-set(reachable)),'source_sha256':hashlib.sha256(source).hexdigest(),'execution':'none','outbound_requests':0,'limitations':['Graph reachability from caller-supplied relationships is not actual access or compromise.','Observed labels and evidence references are caller assertions, not independently verified.','Conditional paths may depend on hypotheses; no probing, exploitation or propagation occurred.']}


class ResearchWorkspace:
    def __init__(self,store_root):self.store_root=Path(store_root)
    def references(self,limit=100):
        from evidence_store import EvidenceStore
        return {'retrieval_kind':'stored_snapshot','records':EvidenceStore(self.store_root).list_records(limit),'training_occurred':False}
    def collect(self,fetch=None):
        import collection
        return collection.run(self.store_root,fetch=fetch)
    def live_public(self,query,role,bus):
        import live_data
        return live_data.collect(query,role,bus)
    def hak5(self,query,limit=5):
        import hak5_catalog
        return hak5_catalog.search(query,root=self.store_root.parent,limit=limit)
    analyze_topology=staticmethod(analyze_topology)
    libraries=staticmethod(library_status)

    def search_references(self,query):
        import knowledge
        result=knowledge.lookup(query[:500],2)
        return {'documentation':result['results'],'repository_metadata':self.hak5(query[:500],2),
                'retrieval_kind':'stored_snapshot','training_occurred':False}

    def inspect(self,request):
        import base64
        if not isinstance(request,dict) or set(request)-{'kind','data_base64','rules','architecture'} or not {'kind','data_base64'}<=set(request):
            raise ValueError('Specify kind and base64-encoded supplied bytes')
        encoded=request['data_base64']
        if not isinstance(encoded,str) or len(encoded)>20000:raise ValueError('UI inspection accepts up to 15000 supplied bytes')
        try:value=base64.b64decode(encoded,validate=True)
        except (ValueError,TypeError) as error:raise ValueError('Invalid base64 evidence') from error
        kind=request['kind']
        operations={'html':html_metadata,'pcap':inspect_capture,'dns':inspect_dns,'pe':inspect_pe,'elf':inspect_elf,'xml':inspect_xml,'certificate':certificate_metadata}
        if kind in operations:return operations[kind](value)
        if kind=='disassembly':return disassemble(value,request.get('architecture','x86_64'))
        if kind=='yara':return scan_signatures(value,request.get('rules'))
        raise ValueError('Unknown offline research inspection')


def model_spread(value):
    """Compare bounded relationship reachability before and after containment."""
    if not isinstance(value,dict) or set(value)!={'inventory','contained','steps'}:
        raise ValueError('Spread model requires inventory, contained node IDs and steps')
    inventory=analyze_topology(value['inventory'])
    contained=value['contained'];steps=value['steps']
    ids={node['id'] for node in inventory['nodes']}
    if not isinstance(contained,list) or any(not isinstance(node,str) or node not in ids for node in contained) or len(set(contained))!=len(contained):
        raise ValueError('Containment must list unique supplied inventory node IDs')
    if type(steps) is not int or not 1<=steps<=20:
        raise ValueError('Spread model steps must be 1 through 20')
    graph=nx.DiGraph();graph.add_nodes_from(ids)
    graph.add_edges_from((link['source'],link['target']) for link in inventory['links'])
    blocked=set(contained)
    red={inventory['entry']};blue=red-blocked
    timeline=[{'step':0,'red_reachable':sorted(red),'blue_reachable':sorted(blue)}]
    for step in range(1,steps+1):
        red=red|{target for source in red for target in graph.successors(source)}
        blue=(blue|{target for source in blue for target in graph.successors(source)})-blocked
        timeline.append({'step':step,'red_reachable':sorted(red),'blue_reachable':sorted(blue)})
    return {**inventory,'timeline':timeline,'contained':contained,'model_kind':'in_memory_relationship_simulation',
            'prevented_reachability_ids':sorted(red-blue),
            'limitations':inventory['limitations']+['All supplied links, including hypotheses, are assumed traversable in this what-if model.','Containment removes listed nodes from the blue graph. Reachability is not infection, exploitability or actual containment.','No payloads, replication, command-and-control, active probes or endpoint changes occur.']}
