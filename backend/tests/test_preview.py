"""文件预览与元数据接口测试"""
import io
import time
import os


def _upload(client, content, filename):
    data = {'file': (io.BytesIO(content), filename)}
    resp = client.post('/api/upload', data=data, content_type='multipart/form-data')
    return resp.get_json()['file_id']


def test_list_files_includes_uploaded_at(client):
    """文件列表应包含创建时间字段"""
    _upload(client, b'hello', 'meta_list.txt')
    resp = client.get('/api/files')
    assert resp.status_code == 200
    item = resp.get_json()[0]
    assert 'uploaded_at' in item
    assert item['uploaded_at']


def test_meta_text_file(client):
    """文本文件元数据：分类、类型、摘要与可用操作"""
    file_id = _upload(client, '第一行内容\n第二行'.encode('utf-8'), 'note.txt')

    resp = client.get(f'/api/files/{file_id}/meta')
    assert resp.status_code == 200
    data = resp.get_json()
    assert data['id'] == file_id
    assert data['name'] == 'note.txt'
    assert data['category'] == 'text'
    assert data['file_type'] == '文本文件'
    assert data['previewable'] is True
    assert data['available'] is True
    assert data['summary'].startswith('开头内容：第一行内容')
    assert data['actions'] == {'download': True, 'preview': True, 'share': True}
    assert data['uploaded_at']


def test_meta_not_found(client):
    """元数据查询不存在文件返回 404"""
    resp = client.get('/api/files/does-not-exist/meta')
    assert resp.status_code == 404
    assert '不存在' in resp.get_json()['error']


def test_meta_missing_on_disk(client, db_conn):
    """记录存在但磁盘文件缺失时，元数据标记不可用且操作关闭"""
    file_id = _upload(client, b'data', 'ghost.txt')
    cursor = db_conn.cursor()
    cursor.execute('SELECT path FROM files WHERE id = ?', (file_id,))
    os.remove(cursor.fetchone()['path'])

    resp = client.get(f'/api/files/{file_id}/meta')
    data = resp.get_json()
    assert resp.status_code == 200
    assert data['available'] is False
    assert data['previewable'] is False
    assert data['actions']['download'] is False
    assert data['actions']['preview'] is False


def test_preview_text_content(client):
    """文本预览返回开头内容"""
    file_id = _upload(client, 'line1\nline2'.encode('utf-8'), 'p.txt')

    resp = client.get(f'/api/files/{file_id}/preview')
    assert resp.status_code == 200
    data = resp.get_json()
    assert data['previewable'] is True
    assert data['payload']['kind'] == 'text'
    assert 'line1' in data['payload']['content']
    assert data['content_url'] == f'/api/files/{file_id}/content'


def test_preview_text_truncated(client):
    """超长文本预览应标记截断"""
    file_id = _upload(client, b'a' * 70000, 'big.txt')

    resp = client.get(f'/api/files/{file_id}/preview')
    data = resp.get_json()
    assert data['payload']['truncated'] is True
    assert len(data['payload']['content'].encode('utf-8')) <= 64 * 1024


def test_preview_image_metadata_and_content(client):
    """图片可预览且内容接口内联返回"""
    # 1x1 PNG
    png = bytes.fromhex(
        '89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4'
        '890000000d49444154789c63000100000500010d0a2db40000000049454e44ae'
        '426082'
    )
    file_id = _upload(client, png, 'pixel.png')

    meta = client.get(f'/api/files/{file_id}/meta').get_json()
    assert meta['category'] == 'image'
    assert '1 × 1' in meta['summary']

    preview = client.get(f'/api/files/{file_id}/preview').get_json()
    assert preview['payload']['kind'] == 'image'

    content = client.get(f'/api/files/{file_id}/content')
    assert content.status_code == 200
    assert content.mimetype == 'image/png'
    assert 'attachment' not in content.headers.get('Content-Disposition', '')
    assert content.headers.get('Content-Security-Policy')
    assert content.headers.get('X-Content-Type-Options') == 'nosniff'


def test_preview_unsupported_type(client):
    """压缩包不可预览，返回 422 与失败说明"""
    file_id = _upload(client, b'PK\x03\x04binary', 'archive.zip')

    resp = client.get(f'/api/files/{file_id}/preview')
    assert resp.status_code == 422
    data = resp.get_json()
    assert data['previewable'] is False
    assert data['error']
    assert '下载' in data['error']

    meta = client.get(f'/api/files/{file_id}/meta').get_json()
    assert meta['previewable'] is False
    assert meta['file_type'] == '压缩包'


def test_preview_record_gone(client, db_conn):
    """预览时文件被删除，返回 404；磁盘缺失返回 410"""
    file_id = _upload(client, b'data', 'gone.txt')

    cursor = db_conn.cursor()
    cursor.execute('DELETE FROM files WHERE id = ?', (file_id,))
    db_conn.commit()
    assert client.get(f'/api/files/{file_id}/preview').status_code == 404

    file_id2 = _upload(client, b'data2', 'gone2.txt')
    cursor.execute('SELECT path FROM files WHERE id = ?', (file_id2,))
    os.remove(cursor.fetchone()['path'])
    assert client.get(f'/api/files/{file_id2}/preview').status_code == 410
    assert client.get(f'/api/files/{file_id2}/content').status_code == 410


def test_preview_does_not_require_auth(client):
    """预览与元数据对访客开放（与文件列表、分享页一致）"""
    file_id = _upload(client, b'open', 'open.txt')
    assert client.get(f'/api/files/{file_id}/meta').status_code == 200
    assert client.get(f'/api/files/{file_id}/preview').status_code == 200
    assert client.get(f'/api/files/{file_id}/content').status_code == 200


def test_meta_reflects_renamed_record(client, db_conn):
    """目录数据变化（重命名）后重新进入应看到一致元数据"""
    file_id = _upload(client, b'{"k": 1}', 'before.json')

    cursor = db_conn.cursor()
    cursor.execute('UPDATE files SET name = ? WHERE id = ?', ('after.json', file_id))
    db_conn.commit()

    data = client.get(f'/api/files/{file_id}/meta').get_json()
    assert data['name'] == 'after.json'
    assert data['category'] == 'text'

    listing = client.get('/api/files').get_json()
    listed = next(f for f in listing if f['id'] == file_id)
    assert listed['name'] == 'after.json'


def test_existing_capabilities_unaffected(client, auth_token):
    """新增接口不影响原有取件、入库与分享能力"""
    file_id = _upload(client, b'keep working', 'keep.txt')

    # 取件（下载）仍需鉴权
    assert client.get(f'/api/download/{file_id}').status_code == 401
    dl = client.get(
        f'/api/download/{file_id}',
        headers={'Authorization': f'Bearer {auth_token}'}
    )
    assert dl.status_code == 200
    assert dl.data == b'keep working'

    # 分享（协作）正常
    share = client.post(
        '/api/share',
        json={'file_id': file_id},
        headers={'Authorization': f'Bearer {auth_token}'}
    )
    assert share.status_code == 200
    share_id = share.get_json()['share_id']
    assert client.get(f'/api/share/{share_id}/download').status_code == 200
