"""文件预览与元数据模块测试"""
import io
import os
import time

import preview_service


def _upload(client, content, filename):
    data = {'file': (io.BytesIO(content), filename)}
    resp = client.post('/api/upload', data=data, content_type='multipart/form-data')
    assert resp.status_code == 200
    return resp.get_json()['file_id']


# ---------- 元数据接口 ----------

def test_metadata_text_file(client):
    """文本文件返回完整元数据与内容摘要"""
    file_id = _upload(client, '第一行\n第二行\n第三行'.encode('utf-8'), 'note.txt')

    resp = client.get(f'/api/files/{file_id}')
    assert resp.status_code == 200
    data = resp.get_json()

    assert data['id'] == file_id
    assert data['name'] == 'note.txt'
    assert data['size'] == len('第一行\n第二行\n第三行'.encode('utf-8'))
    assert data['file_type'] == 'text'
    assert data['type_label'] == '文本文件'
    assert data['previewable'] is True
    assert data['available'] is True
    assert data['stored'] is True
    assert 'download' in data['actions']
    assert 'share' in data['actions']
    assert data['created_at']
    summary = data['summary']
    assert summary['kind'] == 'text'
    assert '第一行' in summary['text']
    assert summary['lines'] == 3
    assert summary['chars'] > 0


def test_metadata_not_found(client):
    """不存在的文件返回 404"""
    resp = client.get('/api/files/no-such-file')
    assert resp.status_code == 404
    assert '不存在' in resp.get_json()['error']


def test_metadata_unsupported_type(client):
    """不支持预览的类型仍返回元数据，但标记为不可预览"""
    file_id = _upload(client, b'PK\x03\x04binary', 'archive.zip')

    resp = client.get(f'/api/files/{file_id}')
    assert resp.status_code == 200
    data = resp.get_json()
    assert data['file_type'] == 'other'
    assert data['previewable'] is False
    assert data['summary']['kind'] == 'other'


def test_metadata_missing_on_disk(client, db_conn):
    """数据库有记录但磁盘文件丢失：元数据可见、available=False"""
    file_id = _upload(client, b'hello', 'ghost.txt')

    cursor = db_conn.cursor()
    cursor.execute('SELECT path FROM files WHERE id = ?', (file_id,))
    path = cursor.fetchone()['path']
    os.remove(path)

    resp = client.get(f'/api/files/{file_id}')
    assert resp.status_code == 200
    data = resp.get_json()
    assert data['available'] is False
    assert data['stored'] is False
    assert data['summary']['kind'] == 'missing'


def test_metadata_binary_with_text_extension(client):
    """扩展名是文本但内容是二进制：摘要降级为不可预览说明"""
    file_id = _upload(client, b'\x00\x01\x02binary\x00data', 'fake.txt')

    resp = client.get(f'/api/files/{file_id}')
    data = resp.get_json()
    assert data['file_type'] == 'text'
    assert data['summary']['kind'] == 'other'


def test_list_files_includes_created_at(client):
    """文件列表包含创建时间字段"""
    _upload(client, b'abc', 'listed.txt')
    resp = client.get('/api/files')
    assert resp.status_code == 200
    files = resp.get_json()
    assert len(files) >= 1
    assert all(f['created_at'] for f in files)
    assert any(f['name'] == 'listed.txt' for f in files)


# ---------- 预览内容接口 ----------

def test_preview_text_full(client):
    """文本预览公开可读，返回完整内容"""
    file_id = _upload(client, 'hello preview'.encode('utf-8'), 'doc.txt')

    resp = client.get(f'/api/files/{file_id}/preview')
    assert resp.status_code == 200
    assert resp.data.decode('utf-8') == 'hello preview'
    assert resp.headers['Content-Type'].startswith('text/plain')
    assert resp.headers['X-Content-Type-Options'] == 'nosniff'
    assert resp.headers['Content-Disposition'] == 'inline'


def test_preview_without_auth(client, auth_token):
    """预览无需登录；下载仍需要鉴权"""
    file_id = _upload(client, b'public preview', 'open.txt')

    # 无 token 可预览
    preview_resp = client.get(f'/api/files/{file_id}/preview')
    assert preview_resp.status_code == 200

    # 无 token 不能下载（既有能力不受影响）
    download_resp = client.get(f'/api/download/{file_id}')
    assert download_resp.status_code == 401


def test_preview_range_header(client):
    """支持标准 Range 头断点读取"""
    file_id = _upload(client, b'0123456789', 'range.txt')

    resp = client.get(f'/api/files/{file_id}/preview', headers={'Range': 'bytes=2-5'})
    assert resp.status_code == 206
    assert resp.data == b'2345'
    assert resp.headers['Content-Range'] == 'bytes 2-5/10'
    assert resp.headers['X-Content-Start'] == '2'
    assert resp.headers['X-Content-End'] == '5'
    assert resp.headers['X-Content-Total'] == '10'
    assert resp.headers['Accept-Ranges'] == 'bytes'


def test_preview_range_start_query(client):
    """支持 ?start= 查询参数，模拟中断后从当前位置继续"""
    content = 'abcdefghij'.encode('utf-8')
    file_id = _upload(client, content, 'resume.txt')

    first = client.get(f'/api/files/{file_id}/preview?start=0')
    assert first.status_code == 206
    assert first.data == content

    # 中断后从偏移 4 继续
    resumed = client.get(f'/api/files/{file_id}/preview?start=4')
    assert resumed.status_code == 206
    assert resumed.data == b'efghij'
    assert resumed.headers['Content-Range'] == 'bytes 4-9/10'


def test_preview_range_suffix(client):
    """支持 bytes=-N 形式的范围"""
    file_id = _upload(client, b'0123456789', 'suffix.txt')
    resp = client.get(f'/api/files/{file_id}/preview', headers={'Range': 'bytes=-3'})
    assert resp.status_code == 206
    assert resp.data == b'789'


def test_preview_multibyte_chunks_reconstruct(client):
    """分块读取多字节文本，按边界对齐后可无损还原"""
    content = '中文内容测试ABC一二三'.encode('utf-8')
    file_id = _upload(client, content, 'multi.txt')

    # 用刻意不对齐字符的 5 字节窗口逐块读取
    assembled = b''
    pos = 0
    seen_ranges = []
    while pos < len(content):
        resp = client.get(
            f'/api/files/{file_id}/preview',
            headers={'Range': f'bytes={pos}-{pos + 4}'}
        )
        assert resp.status_code == 206
        data = resp.data
        start = int(resp.headers['X-Content-Start'])
        end = int(resp.headers['X-Content-End'])
        seen_ranges.append((start, end))
        # 每块必须能独立解码
        data.decode('utf-8')
        assembled += data
        pos = end + 1

    assert assembled == content
    assert assembled.decode('utf-8') == '中文内容测试ABC一二三'
    # 区间必须连续无重叠
    for (s1, e1), (s2, e2) in zip(seen_ranges, seen_ranges[1:]):
        assert s2 == e1 + 1


def test_align_text_range_unit(tmp_path):
    """字符边界对齐单元测试"""
    data = '你好ab'.encode('utf-8')  # 你=0-2 好=3-5 a=6 b=7
    p = tmp_path / 't.txt'
    p.write_bytes(data)

    # 切断“你”的起点对齐到 3
    assert preview_service.align_text_range(str(p), 1, 7) == (3, 7)
    # 终点切到“好”内部时补齐到 5
    s, e = preview_service.align_text_range(str(p), 0, 4)
    assert (s, e) == (0, 5)
    # 纯 ASCII 区间保持不变
    assert preview_service.align_text_range(str(p), 6, 7) == (6, 7)


def test_preview_range_beyond_size(client):
    """超出文件大小的范围返回 416"""
    file_id = _upload(client, b'01234', 'small.txt')
    resp = client.get(f'/api/files/{file_id}/preview', headers={'Range': 'bytes=100-200'})
    assert resp.status_code == 416


def test_preview_unsupported_type(client):
    """不支持的类型返回 415 与说明"""
    file_id = _upload(client, b'binary-bytes', 'data.zip')
    resp = client.get(f'/api/files/{file_id}/preview')
    assert resp.status_code == 415
    assert '不支持在线预览' in resp.get_json()['error']


def test_preview_not_found(client):
    resp = client.get('/api/files/missing/preview')
    assert resp.status_code == 404


def test_preview_missing_on_disk(client, db_conn):
    file_id = _upload(client, b'hello', 'ghost-preview.txt')
    cursor = db_conn.cursor()
    cursor.execute('SELECT path FROM files WHERE id = ?', (file_id,))
    path = cursor.fetchone()['path']
    os.remove(path)

    resp = client.get(f'/api/files/{file_id}/preview')
    assert resp.status_code == 410


def test_preview_image_mime(client):
    """图片以正确的 MIME 返回"""
    # 极小的 1x1 PNG
    png = bytes.fromhex(
        '89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4'
        '890000000d494441789c63000100000500010d0a2db40000000049454e44ae426082'
    )
    file_id = _upload(client, png, 'pixel.png')

    resp = client.get(f'/api/files/{file_id}/preview')
    assert resp.status_code == 200
    assert resp.headers['Content-Type'] == 'image/png'
    assert resp.data == png


def test_preview_pdf_mime(client):
    file_id = _upload(client, b'%PDF-1.4 fake content', 'book.pdf')
    resp = client.get(f'/api/files/{file_id}/preview')
    assert resp.status_code == 200
    assert resp.headers['Content-Type'] == 'application/pdf'


def test_preview_html_served_as_plain_text(client):
    """HTML 以纯文本返回，避免在站点上下文中执行"""
    file_id = _upload(client, b'<script>alert(1)</script>', 'page.html')
    resp = client.get(f'/api/files/{file_id}/preview')
    assert resp.status_code == 200
    assert resp.headers['Content-Type'].startswith('text/plain')


def test_preview_empty_file(client):
    file_id = _upload(client, b'', 'empty.txt')
    resp = client.get(f'/api/files/{file_id}/preview')
    assert resp.status_code == 200
    assert resp.data == b''


# ---------- 既有能力回归 ----------

def test_existing_upload_download_share_still_work(client, auth_token):
    """取件、入库、协作链路在新增预览后保持可用"""
    file_id = _upload(client, b'regression check', 'reg.txt')

    download = client.get(f'/api/download/{file_id}?token={auth_token}')
    assert download.status_code == 200
    assert download.data == b'regression check'

    share = client.post(
        '/api/share',
        json={'file_id': file_id, 'expire_hours': 24, 'max_downloads': 5},
        headers={'Authorization': f'Bearer {auth_token}'}
    )
    assert share.status_code == 200
    share_id = share.get_json()['share_id']

    share_download = client.get(f'/api/share/{share_id}/download')
    assert share_download.status_code == 200
    assert share_download.data == b'regression check'


def test_preview_consistent_after_data_change(client):
    """目录数据变化后重新获取元数据应反映最新状态"""
    file_id = _upload(client, b'v1 content', 'changing.txt')

    first = client.get(f'/api/files/{file_id}')
    assert first.get_json()['size'] == len(b'v1 content')

    # 模拟目录数据变化（如后台整理），元数据接口每次实时读取，重新进入应看到一致结果
    from database import get_db
    db = get_db()
    db.execute('UPDATE files SET size = ? WHERE id = ?', (999, file_id))
    db.commit()
    db.close()

    second = client.get(f'/api/files/{file_id}')
    assert second.get_json()['size'] == 999


# ---------- 服务层单元测试 ----------

def test_classify_file():
    assert preview_service.classify_file('a.txt') == 'text'
    assert preview_service.classify_file('a.PNG') == 'image'
    assert preview_service.classify_file('a.mp4') == 'video'
    assert preview_service.classify_file('a.mp3') == 'audio'
    assert preview_service.classify_file('a.pdf') == 'pdf'
    assert preview_service.classify_file('a.bin') == 'other'
    assert preview_service.classify_file('noext') == 'other'


def test_parse_range():
    assert preview_service.parse_range('bytes=0-9', 100) == (0, 9)
    assert preview_service.parse_range('bytes=50-', 100) == (50, 99)
    assert preview_service.parse_range('bytes=-20', 100) == (80, 99)
    assert preview_service.parse_range('bytes=90-500', 100) == (90, 99)
    assert preview_service.parse_range('bytes=200-300', 100) is None
    assert preview_service.parse_range('', 100) is None
    assert preview_service.parse_range('bytes=0-9,10-19', 100) is None


def test_path_traversal_blocked(client):
    """预览接口同样拒绝路径穿越"""
    file_id = _upload(client, b'x', 'safe.txt')
    from database import get_db
    db = get_db()
    db.execute("UPDATE files SET path = '/etc/passwd' WHERE id = ?", (file_id,))
    db.commit()
    db.close()

    resp = client.get(f'/api/files/{file_id}/preview')
    assert resp.status_code == 403
