import json
import threading
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import pytest
from novelviz.providers import text_call,comfy_call,bind_workflow,ProviderError,endpoint
from novelviz.storage import DEFAULTS

@pytest.fixture
def server():
    class Handler(BaseHTTPRequestHandler):
        calls=[]; fail=False
        def log_message(self,*args):pass
        def do_POST(self):
            body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            self.calls.append((self.path,body))
            if self.fail:self.send_response(503); self.end_headers();self.wfile.write(b'PRIVATE');return
            self.send_response(200); self.send_header('Content-Type','application/json'); self.end_headers()
            self.wfile.write(json.dumps({'prompt_id':'p1'} if self.path=='/prompt' else {'choices':[{'message':{'content':'真实协议模拟输出'}}]}).encode())
        def do_GET(self):
            self.send_response(200); self.end_headers()
            if self.path.startswith('/history'):
                self.wfile.write(json.dumps({'p1':{'outputs':{'9':{'images':[{'filename':'x.png','type':'output','subfolder':''}]}},'status':{'completed':True}}}).encode())
            else:self.wfile.write(b'fake-image-bytes')
    s=ThreadingHTTPServer(('127.0.0.1',0),Handler); t=threading.Thread(target=s.serve_forever,daemon=True);t.start()
    yield f'http://127.0.0.1:{s.server_port}',Handler
    s.shutdown();s.server_close()

def test_text_protocol_and_no_fallback(server):
    url,h=server; p=dict(DEFAULTS,provider='openai',endpoint=url+'/v1',model='test')
    assert text_call(p,[{'role':'user','content':'问题'}],'上下文')=='真实协议模拟输出'
    assert h.calls[0][1]['max_tokens']==2048
    h.fail=True
    with pytest.raises(ProviderError,match='503'):text_call(p,[{'role':'user','content':'再次'}],'')
    assert len(h.calls)==2 # exactly one POST per explicit call, including failure

def test_comfy_mapping_and_single_submission(server,tmp_path):
    url,h=server
    flow={'6':{'class_type':'CLIPTextEncode','inputs':{'text':'old'}}}
    bound=bind_workflow(flow,{'prompt':['6','text']},{'prompt':'new'})
    assert flow['6']['inputs']['text']=='old'
    assert bound['6']['inputs']['text']=='new'
    progress=[]; out=comfy_call(url,bound,tmp_path,threading.Event(),progress.append)
    assert len(h.calls)==1 and progress==[{'remote_id':'p1'}]
    assert len(out)==1

def test_invalid_mapping():
    with pytest.raises(ProviderError):bind_workflow({'nodes':[]},{'prompt':['6','text']},{'prompt':'a'})
    with pytest.raises(ProviderError):bind_workflow({'6':{'class_type':'X','inputs':{}}},{'prompt':['6','text']},{'prompt':'a'})

@pytest.mark.parametrize('url',['file:///tmp/x','https://key:secret@example.com/v1','https://example.com/v1?key=secret'])
def test_credentials_in_address_rejected(url):
    with pytest.raises(ProviderError):endpoint(url)

def test_cancel_before_submit(server,tmp_path):
    url,h=server; cancel=threading.Event();cancel.set()
    with pytest.raises(ProviderError):comfy_call(url,{},tmp_path,cancel,lambda _:None)
    assert h.calls==[]
