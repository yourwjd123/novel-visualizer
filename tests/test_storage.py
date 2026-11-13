import json
from pathlib import Path
import pytest
from novelviz.storage import Store,Project,DEFAULTS,read_document,safe_name

def test_account_isolation_and_settings_export(tmp_path):
    s=Store(tmp_path); a=s.accounts[0]; b=s.create_account('第二账户')
    cfg=s.settings(a); cfg.update(model='mine',theme='dark',api_key='SECRET',endpoint='https://secret.example/v1',system='自定义提示词 SECRET')
    s.save_settings(a,cfg)
    assert s.settings(b)['model']==''
    dest=tmp_path/'export.json'; s.export_settings(a,dest,secrets=['SECRET'])
    text=dest.read_text('utf-8')
    assert 'SECRET' not in text and '自定义提示词' in text and 'secret.example' not in text
    s.import_settings(b,dest); assert s.settings(b)['theme']=='dark'
    assert 'api_key' not in s.settings(a)

def test_delete_account_archives_projects(tmp_path):
    s=Store(tmp_path); a=s.accounts[0]; p=s.create_project(a,'书'); p.close(); s.create_account('其他')
    s.delete_account(a)
    assert len(s.accounts)==1
    assert list((tmp_path/'已归档账户').glob('*/项目/*/08_项目数据/project.json'))

def test_project_shared_assets_and_snapshot_versions(tmp_path):
    s=Store(tmp_path); p=s.create_project(s.accounts[0],'小说')
    s1=p.add_segment('一','第一段'); s2=p.add_segment('二','第二段')
    p.save_asset(dict(name='人物',kind='人物',source='原文明确',review='已确认',description='第一章穿布衣'))
    d=p.load_node(s1,1); d['final']='方案一'; first=p.confirm(s1,1,d)
    d['final']='方案二'; second=p.confirm(s1,1,d)
    assert first.read_text('utf-8')=='方案一' and second.read_text('utf-8')=='方案二'
    assert p.load_node(s2,1)['final']=='' and len(p.assets())==1
    assert len(list((p.path/'03_对话记录'/s1).glob('*.md')))==1
    p.close()

def test_restart_marks_interrupted_jobs_unknown(tmp_path):
    s=Store(tmp_path); p=s.create_project(s.accounts[0],'小说')
    p.save_job(dict(id='j1',status='running',kind='文本对话'))
    path=p.path; p.close(); p=Project(path)
    assert p.jobs()[0]['status']=='unknown'
    p.close()

def test_relative_paths_and_original_copy(tmp_path):
    src=tmp_path/'小说.txt'; src.write_text('你好\n世界',encoding='utf-8')
    s=Store(tmp_path/'data'); p=s.create_project(s.accounts[0],'书'); sid=p.add_segment('章节',read_document(src),src)
    record=p.segments()[0]
    assert not Path(record['file']).is_absolute()
    assert (p.path/record['source']).read_text('utf-8')=='你好\n世界'
    (p.path/record['file']).write_text('外部修改',encoding='utf-8'); assert p.segment_text(sid)=='外部修改'
    p.close()

@pytest.mark.parametrize('name',['CON','../危险名称','一:二/三'])
def test_portable_names(name):
    result=safe_name(name); assert '/' not in result and ':' not in result and result!='CON'

def test_docx_and_epub(tmp_path):
    from docx import Document
    from ebooklib import epub
    d=Document(); d.add_paragraph('第一章'); d.add_paragraph('小说正文'); f=tmp_path/'a.docx'; d.save(f)
    assert '小说正文' in read_document(f)
    book=epub.EpubBook(); book.set_identifier('test'); book.set_title('书'); book.set_language('zh')
    c=epub.EpubHtml(title='章节',file_name='chapter.xhtml',lang='zh'); c.content='<h1>第一章</h1><p>渡口</p>'; book.add_item(c); book.spine=[c]
    book.add_item(epub.EpubNcx()); book.add_item(epub.EpubNav()); e=tmp_path/'a.epub'; epub.write_epub(e,book)
    assert '渡口' in read_document(e)

def test_known_credentials_redacted_from_project_files(tmp_path):
    s=Store(tmp_path);p=s.create_project(s.accounts[0],'书');p.secrets=['MY_SECRET']
    sid=p.add_segment('第一章','普通原文');d=p.load_node(sid,0);d['final']='方案 MY_SECRET';d['messages']=[dict(role='assistant',content='MY_SECRET')]
    p.confirm(sid,0,d);p.save_job(dict(id='x',status='failed',params={'system':'MY_SECRET'}))
    for file in p.path.rglob('*'):
        if file.suffix in ('.md','.json'):
            assert 'MY_SECRET' not in file.read_text('utf-8')
    assert 'MY_SECRET' not in json.dumps(p.load_node(sid,0))
    p.close()
