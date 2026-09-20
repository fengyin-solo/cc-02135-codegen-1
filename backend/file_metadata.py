"""文件元数据与预览内容服务

负责文件类型分类、内容摘要生成与预览内容读取，
供元数据接口与预览接口复用，保证目录、详情看到的类型/摘要一致。
"""
import os

# 文本类可直接预览的扩展名
TEXT_EXTENSIONS = {
    'txt', 'md', 'markdown', 'log', 'csv', 'json', 'xml', 'yaml', 'yml',
    'ini', 'conf', 'cfg', 'html', 'htm', 'css', 'js', 'ts', 'sql',
    'java', 'c', 'h', 'cpp', 'go', 'rs', 'rb', 'sh',
}
IMAGE_EXTENSIONS = {'jpg', 'jpeg', 'png', 'gif', 'webp', 'svg', 'bmp'}
PDF_EXTENSIONS = {'pdf'}
AUDIO_EXTENSIONS = {'mp3', 'wav', 'ogg', 'm4a', 'flac'}
VIDEO_EXTENSIONS = {'mp4', 'webm', 'avi', 'mov', 'mkv'}
ARCHIVE_EXTENSIONS = {'zip', 'rar', '7z', 'gz', 'tar', 'bz2'}
DOCUMENT_EXTENSIONS = {'doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx'}

# 预览接口最多读取的字节数（约 64KB）
PREVIEW_MAX_BYTES = 64 * 1024
# 摘要最多保留的字符数
SUMMARY_MAX_CHARS = 120

# 分类 -> 中文类型名 / 是否可在线预览 / 预览失败说明
CATEGORY_INFO = {
    'text': ('文本文件', True, None),
    'image': ('图片', True, None),
    'pdf': ('PDF 文档', True, None),
    'audio': ('音频', True, None),
    'video': ('视频', True, None),
    'archive': ('压缩包', False, '该类型为归档压缩文件，不支持在线预览，请下载后查看'),
    'document': ('办公文档', False, '在线预览暂不支持此文档格式，请下载后使用对应软件打开'),
    'other': ('未知类型', False, '暂不支持该文件类型的在线预览，请下载后查看'),
}


def get_extension(filename):
    """获取小写扩展名（不含点），无扩展名返回空串"""
    if '.' in filename:
        return filename.rsplit('.', 1)[1].lower()
    return ''


def classify_file(filename):
    """按扩展名返回文件分类"""
    ext = get_extension(filename)
    if ext in TEXT_EXTENSIONS:
        return 'text'
    if ext in IMAGE_EXTENSIONS:
        return 'image'
    if ext in PDF_EXTENSIONS:
        return 'pdf'
    if ext in AUDIO_EXTENSIONS:
        return 'audio'
    if ext in VIDEO_EXTENSIONS:
        return 'video'
    if ext in ARCHIVE_EXTENSIONS:
        return 'archive'
    if ext in DOCUMENT_EXTENSIONS:
        return 'document'
    return 'other'


def get_type_info(filename):
    """返回 (分类, 中文类型名, 可否在线预览, 预览失败说明)"""
    category = classify_file(filename)
    type_name, previewable, unsupported_msg = CATEGORY_INFO[category]
    return category, type_name, previewable, unsupported_msg


def guess_mime(filename):
    """为可内联预览的文件推断 MIME 类型，无法确定返回通用二进制类型

    只给主类型，charset 由 Flask 对文本类型自动补充，避免重复。
    """
    ext = get_extension(filename)
    mime_map = {
        'txt': 'text/plain', 'md': 'text/plain', 'markdown': 'text/plain',
        'log': 'text/plain', 'csv': 'text/plain',
        'json': 'application/json', 'xml': 'application/xml',
        'html': 'text/html', 'htm': 'text/html', 'css': 'text/css',
        'js': 'text/javascript',
        'pdf': 'application/pdf',
        'jpg': 'image/jpeg', 'jpeg': 'image/jpeg', 'png': 'image/png',
        'gif': 'image/gif', 'webp': 'image/webp', 'svg': 'image/svg+xml',
        'bmp': 'image/bmp',
        'mp3': 'audio/mpeg', 'wav': 'audio/wav', 'ogg': 'audio/ogg',
        'm4a': 'audio/mp4', 'flac': 'audio/flac',
        'mp4': 'video/mp4', 'webm': 'video/webm', 'avi': 'video/x-msvideo',
        'mov': 'video/quicktime',
    }
    return mime_map.get(ext, 'application/octet-stream')


def read_text_preview(path):
    """读取文本文件开头内容，返回 (文本, 是否截断)；解码失败返回 None"""
    try:
        with open(path, 'rb') as f:
            raw = f.read(PREVIEW_MAX_BYTES + 1)
    except OSError:
        return None, False

    truncated = len(raw) > PREVIEW_MAX_BYTES
    raw = raw[:PREVIEW_MAX_BYTES]
    for encoding in ('utf-8', 'gb18030', 'latin-1'):
        try:
            return raw.decode(encoding), truncated
        except (UnicodeDecodeError, LookupError):
            continue
    return None, False


def get_image_dimensions(path, ext):
    """轻量解析 PNG/GIF/JPEG 的图片宽高，失败返回 None"""
    import struct
    try:
        if ext == 'png':
            with open(path, 'rb') as f:
                head = f.read(24)
            if head[:8] != b'\x89PNG\r\n\x1a\n' or len(head) < 24:
                return None
            width, height = struct.unpack('>II', head[16:24])
            return width, height

        if ext == 'gif':
            with open(path, 'rb') as f:
                head = f.read(10)
            if head[:6] not in (b'GIF87a', b'GIF89a') or len(head) < 10:
                return None
            width, height = struct.unpack('<HH', head[6:10])
            return width, height

        if ext in ('jpg', 'jpeg'):
            with open(path, 'rb') as f:
                if f.read(2) != b'\xff\xd8':
                    return None
                while True:
                    byte = f.read(1)
                    while byte and byte != b'\xff':
                        byte = f.read(1)
                    marker = f.read(1)
                    while marker == b'\xff':
                        marker = f.read(1)
                    if not marker:
                        return None
                    if 0xC0 <= marker[0] <= 0xCF and marker[0] not in (0xC4, 0xC8, 0xCC):
                        f.read(3)
                        data = f.read(4)
                        if len(data) < 4:
                            return None
                        height, width = struct.unpack('>HH', data)
                        return width, height
                    size_data = f.read(2)
                    if len(size_data) < 2:
                        return None
                    size = struct.unpack('>H', size_data)[0]
                    f.seek(size - 2, 1)
    except (OSError, ValueError, struct.error):
        return None
    return None


def build_summary(filename, path, size):
    """生成内容摘要：文本取首行，媒体取尺寸/时长占位说明，其余给类型描述"""
    category = classify_file(filename)
    ext = get_extension(filename)

    if category == 'text':
        text, truncated = read_text_preview(path)
        if text is None:
            return '文本内容无法读取'
        first_line = next((line.strip() for line in text.splitlines() if line.strip()), '')
        if not first_line:
            return '空文本文件'
        suffix = '…' if truncated or len(first_line) > SUMMARY_MAX_CHARS else ''
        return f'开头内容：{first_line[:SUMMARY_MAX_CHARS]}{suffix}'

    if category == 'image':
        dimensions = get_image_dimensions(path, ext)
        if dimensions:
            return f'图片，尺寸 {dimensions[0]} × {dimensions[1]} 像素'
        return '图片文件，可在线查看'

    if category == 'pdf':
        return 'PDF 文档，可在浏览器中直接预览'
    if category == 'audio':
        return '音频文件，可在线播放'
    if category == 'video':
        return '视频文件，可在线播放'
    if category == 'archive':
        return '压缩归档文件，需下载后解压查看'
    if category == 'document':
        return '办公文档，需下载后使用办公软件查看'
    return f'大小 {size} 字节，暂不支持在线预览的文件'


def build_preview(filename, path):
    """构建预览数据：(previewable, unsupported_msg, payload)

    payload 按类型不同：
      text -> {'kind': 'text', 'content', 'truncated'}
      image/pdf/audio/video -> {'kind': ...}，前端通过 content_url 内联加载
      不可预览 -> None
    读取失败返回 (False, 失败说明, None)
    """
    category, _type_name, previewable, unsupported_msg = get_type_info(filename)

    if not previewable:
        return False, unsupported_msg, None

    if category == 'text':
        content, truncated = read_text_preview(path)
        if content is None:
            return False, '文件内容读取失败，文件可能已损坏或被移动', None
        return True, None, {'kind': 'text', 'content': content, 'truncated': truncated}

    if category == 'image':
        return True, None, {'kind': 'image'}
    if category == 'pdf':
        return True, None, {'kind': 'pdf'}
    if category == 'audio':
        return True, None, {'kind': 'audio'}
    if category == 'video':
        return True, None, {'kind': 'video'}

    return False, unsupported_msg, None
