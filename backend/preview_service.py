"""文件预览服务

集中管理文件预览相关逻辑：
- 文件类型识别（文本 / 图片 / 音频 / 视频 / PDF / 不支持预览）
- 元数据组装（统一供文件详情接口与文件列表使用）
- 文本内容摘要提取
- HTTP Range 解析（支持读取中断后从断点继续）

该模块只处理普通磁盘文件，不改变上传、下载、分享等既有流程。
"""
import os

# 各分类允许在线预览的扩展名（保持精简，规避可执行/脚本类内容）
TEXT_EXTENSIONS = {
    'txt', 'md', 'log', 'csv', 'json', 'xml', 'yaml', 'yml',
    'ini', 'conf', 'cfg', 'sql', 'js', 'css', 'html', 'htm'
}
IMAGE_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp'}
AUDIO_EXTENSIONS = {'mp3', 'wav', 'ogg', 'flac', 'm4a'}
VIDEO_EXTENSIONS = {'mp4', 'webm', 'mov'}
PDF_EXTENSIONS = {'pdf'}

# 浏览器可直接渲染的 MIME 类型
MIME_TYPES = {
    'txt': 'text/plain; charset=utf-8',
    'md': 'text/plain; charset=utf-8',
    'log': 'text/plain; charset=utf-8',
    'csv': 'text/plain; charset=utf-8',
    'json': 'application/json; charset=utf-8',
    'xml': 'application/xml; charset=utf-8',
    'yaml': 'text/plain; charset=utf-8',
    'yml': 'text/plain; charset=utf-8',
    'ini': 'text/plain; charset=utf-8',
    'conf': 'text/plain; charset=utf-8',
    'cfg': 'text/plain; charset=utf-8',
    'sql': 'text/plain; charset=utf-8',
    'js': 'text/javascript; charset=utf-8',
    'css': 'text/css; charset=utf-8',
    # HTML 以纯文本返回，避免在当前站点上下文中直接渲染造成脚本注入
    'html': 'text/plain; charset=utf-8',
    'htm': 'text/plain; charset=utf-8',
    'png': 'image/png',
    'jpg': 'image/jpeg',
    'jpeg': 'image/jpeg',
    'gif': 'image/gif',
    'webp': 'image/webp',
    'bmp': 'image/bmp',
    'mp3': 'audio/mpeg',
    'wav': 'audio/wav',
    'ogg': 'audio/ogg',
    'flac': 'audio/flac',
    'm4a': 'audio/mp4',
    'mp4': 'video/mp4',
    'webm': 'video/webm',
    'mov': 'video/quicktime',
    'pdf': 'application/pdf',
}

# 面向用户的类型名称
TYPE_LABELS = {
    'text': '文本文件',
    'image': '图片',
    'audio': '音频',
    'video': '视频',
    'pdf': 'PDF 文档',
    'other': '不支持在线预览',
}

# 可在浏览器中直接呈现内容的类型
PREVIEWABLE_TYPES = {'text', 'image', 'audio', 'video', 'pdf'}

# 摘要最多读取的字节数（仅读取文件头部，避免大文件开销）
SUMMARY_READ_LIMIT = 8192
# 摘要展示的最大字符数
SUMMARY_TEXT_LIMIT = 2000
# 单次预览读取上限（与上传大小限制保持同一量级）
MAX_PREVIEW_BYTES = 50 * 1024 * 1024


def get_extension(filename):
    """从文件名中提取小写扩展名，无扩展名时返回空字符串"""
    if '.' not in filename:
        return ''
    return filename.rsplit('.', 1)[1].lower()


def classify_file(filename):
    """按扩展名返回预览类型分类：text/image/audio/video/pdf/other"""
    ext = get_extension(filename)
    if ext in TEXT_EXTENSIONS:
        return 'text'
    if ext in IMAGE_EXTENSIONS:
        return 'image'
    if ext in AUDIO_EXTENSIONS:
        return 'audio'
    if ext in VIDEO_EXTENSIONS:
        return 'video'
    if ext in PDF_EXTENSIONS:
        return 'pdf'
    return 'other'


def get_mime_type(filename):
    """返回适合浏览器渲染的 Content-Type，未知类型回退为下载流"""
    return MIME_TYPES.get(get_extension(filename), 'application/octet-stream')


def get_type_label(filename):
    """返回面向用户的文件类型名称"""
    return TYPE_LABELS[classify_file(filename)]


def is_previewable(filename):
    """该文件是否支持在线预览"""
    return classify_file(filename) in PREVIEWABLE_TYPES


def _decode_text(data):
    """尝试将字节解码为文本，无法解码时返回 None"""
    try:
        return data.decode('utf-8')
    except UnicodeDecodeError:
        pass
    for encoding in ('gb18030', 'latin-1'):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return None


def build_summary(filename, filepath, file_type):
    """生成内容摘要

    - 文本：返回开头片段及行/字符统计
    - 图片/音频/视频/PDF：返回类型说明
    - 其他：提示不支持预览，可下载后查看
    """
    if file_type in ('image', 'audio', 'video', 'pdf'):
        return {
            'kind': file_type,
            'text': None,
            'truncated': False,
            'lines': None,
            'chars': None,
            'message': f'{TYPE_LABELS[file_type]}，可在下方直接预览'
        }

    if file_type == 'other':
        return {
            'kind': 'other',
            'text': None,
            'truncated': False,
            'lines': None,
            'chars': None,
            'message': '该格式暂不支持在线预览，请下载后使用对应软件打开'
        }

    # 文本类型：读取文件头部判断是否为真正的文本
    try:
        with open(filepath, 'rb') as f:
            head = f.read(SUMMARY_READ_LIMIT)
    except OSError:
        return {
            'kind': 'other',
            'text': None,
            'truncated': False,
            'lines': None,
            'chars': None,
            'message': '文件读取失败，请稍后重试'
        }

    # NUL 字节通常意味着二进制内容
    if b'\x00' in head:
        return {
            'kind': 'other',
            'text': None,
            'truncated': False,
            'lines': None,
            'chars': None,
            'message': '文件内容不是可读文本，无法在线预览，请下载后查看'
        }

    text = _decode_text(head)
    if text is None:
        return {
            'kind': 'other',
            'text': None,
            'truncated': False,
            'lines': None,
            'chars': None,
            'message': '文件编码无法识别，请下载后查看'
        }

    size = os.path.getsize(filepath)
    lines = text.count('\n') + (0 if text.endswith('\n') or not text else 1)
    truncated = size > len(head) or len(text) > SUMMARY_TEXT_LIMIT
    snippet = text[:SUMMARY_TEXT_LIMIT].rstrip()

    return {
        'kind': 'text',
        'text': snippet,
        'truncated': truncated,
        'lines': lines,
        'chars': len(text),
        'message': None
    }


def build_file_metadata(file_row, storage_path):
    """根据数据库记录与磁盘路径组装文件元数据

    storage_path 为磁盘上的真实路径，记录缺失或文件丢失时仍然返回元数据，
    但 available/stored 会标记为 False，供界面给出一致的失败说明。
    """
    filename = file_row['name']
    file_type = classify_file(filename)
    exists = bool(storage_path) and os.path.exists(storage_path)

    metadata = {
        'id': file_row['id'],
        'name': filename,
        'size': file_row['size'],
        'created_at': file_row['uploaded_at'],
        'file_type': file_type,
        'type_label': TYPE_LABELS[file_type],
        'extension': get_extension(filename),
        'mime_type': get_mime_type(filename),
        'previewable': file_type in PREVIEWABLE_TYPES,
        'stored': exists,
        'available': exists,
        'actions': ['download', 'share'],
        'summary': None,
    }

    if exists:
        metadata['summary'] = build_summary(filename, storage_path, file_type)
    else:
        metadata['summary'] = {
            'kind': 'missing',
            'text': None,
            'truncated': False,
            'lines': None,
            'chars': None,
            'message': '文件数据缺失或已被移除，暂时无法预览，可稍后重试'
        }

    return metadata


def parse_range(range_header, file_size):
    """解析 HTTP Range 头

    返回 (start, end) 闭区间，遵循 RFC 7233 的字节范围语义。
    仅支持单区间；无法解析时返回 None。
    """
    if not range_header or not range_header.startswith('bytes='):
        return None

    spec = range_header[len('bytes='):].strip()
    if ',' in spec:
        return None

    try:
        if spec.startswith('-'):
            suffix_length = int(spec[1:])
            if suffix_length <= 0:
                return None
            start = max(0, file_size - suffix_length)
            return start, file_size - 1
        if spec.endswith('-'):
            start = int(spec[:-1])
            if start < 0 or start >= file_size:
                return None
            return start, file_size - 1
        start_str, end_str = spec.split('-', 1)
        start = int(start_str)
        end = int(end_str)
    except (ValueError, IndexError):
        return None

    if start < 0 or end < start or start >= file_size:
        return None
    return start, min(end, file_size - 1)


def read_range(filepath, start, end):
    """读取文件 [start, end] 闭区间内容"""
    with open(filepath, 'rb') as f:
        f.seek(start)
        return f.read(end - start + 1)


def _is_utf8_lead(byte):
    """该字节是否为 UTF-8 字符起始字节（ASCII 或 11xxxxxx）"""
    return byte & 0xC0 != 0x80


def align_text_range(filepath, start, end):
    """将字节区间对齐到 UTF-8 字符边界

    分块读取文本时区间可能切断多字节字符：
    - 起点向后移到所属字符的下一边界（不返回半个起始字符）
    - 终点向前移到所属字符的最后一个字节（不返回半个结尾字符）
    对齐后相邻分块在字符边界处首尾相接，各自都能独立正确解码。
    """
    try:
        with open(filepath, 'rb') as f:
            # 起点对齐：从 start 向前找到所在字符的起始字节
            if start > 0:
                f.seek(max(0, start - 3))
                probe_start = f.tell()
                probe = f.read((start - probe_start) + 1)
                lead_index = None
                for i in range(len(probe) - 1, -1, -1):
                    if _is_utf8_lead(probe[i]):
                        lead_index = i
                        break
                if lead_index is not None:
                    lead_pos = probe_start + lead_index
                    first = probe[lead_index]
                    if first >= 0xF0:
                        char_len = 4
                    elif first >= 0xE0:
                        char_len = 3
                    elif first >= 0xC0:
                        char_len = 2
                    else:
                        char_len = 1
                    # 仅当字符起始严格位于 start 之前、而 start 仍落在该字符内部时跳过
                    if lead_pos < start < lead_pos + char_len:
                        start = lead_pos + char_len

            # 终点对齐：向前回退到包含 end 的字符起始，再补齐该字符全部字节
            f.seek(end)
            cur = f.read(1)
            if cur and not _is_utf8_lead(cur[0]):
                # end 落在某个多字节字符中部，向前找到其起始字节
                while cur and not _is_utf8_lead(cur[0]) and end > start:
                    end -= 1
                    f.seek(end)
                    cur = f.read(1)
            if cur and _is_utf8_lead(cur[0]) and cur[0] >= 0xC0:
                first = cur[0]
                if first >= 0xF0:
                    char_len = 4
                elif first >= 0xE0:
                    char_len = 3
                else:
                    char_len = 2
                # 补齐到该字符末尾（不越界由上层 file_size 保证）
                end = end + char_len - 1
    except OSError:
        return start, end

    return start, end
