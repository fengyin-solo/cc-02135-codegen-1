// 从配置文件获取API地址
const API_BASE = CONFIG.API_BASE;

let currentShareFileId = null;
let currentShareLink = null;

// ===== 文件预览控制 =====
// 每次进入预览生成新的会话编号；过期会话的异步结果一律丢弃，
// 保证连续打开不同文件时不会残留上一份结果。
const PreviewController = {
    session: 0,
    fileId: null,
    metadata: null,
    textOffset: 0,
    textTotal: null,
    textBuffer: '',
    textAbort: null,
    mediaUrl: null,

    reset() {
        this.session++;
        this.fileId = null;
        this.metadata = null;
        this.textOffset = 0;
        this.textTotal = null;
        this.textBuffer = '';
        this.abortTextLoad();
        this.revokeMediaUrl();
    },

    abortTextLoad() {
        if (this.textAbort) {
            this.textAbort.abort();
            this.textAbort = null;
        }
    },

    revokeMediaUrl() {
        if (this.mediaUrl) {
            window.URL.revokeObjectURL(this.mediaUrl);
            this.mediaUrl = null;
        }
    }
};

// 将预览相关的展示节点恢复到初始（隐藏）状态
function resetPreviewDom() {
    ['previewLoading', 'previewError', 'previewDetail',
     'previewContentLoading', 'previewContentInterrupted',
     'previewTextContent', 'previewImageContent', 'previewVideoContent',
     'previewAudioContent', 'previewPdfContent', 'previewContentNotice',
     'previewSummaryText', 'previewSummaryMessage', 'previewSummaryStats'
    ].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.style.display = 'none';
    });
    const img = document.getElementById('previewImageContent');
    const video = document.getElementById('previewVideoContent');
    const audio = document.getElementById('previewAudioContent');
    const pdf = document.getElementById('previewPdfContent');
    if (img) img.removeAttribute('src');
    if (video) { video.removeAttribute('src'); video.load(); }
    if (audio) { audio.removeAttribute('src'); audio.load(); }
    if (pdf) pdf.removeAttribute('src');
    document.getElementById('previewTextContent').textContent = '';
}

// 目录视图与预览视图切换
function showDirectoryView() {
    document.body.classList.remove('preview-mode');
    document.getElementById('previewSection').style.display = 'none';
}

function showPreviewView() {
    document.body.classList.add('preview-mode');
    const section = document.getElementById('previewSection');
    section.style.display = 'block';
    window.scrollTo(0, 0);
}

// 从文件目录进入预览
function openPreview(fileId) {
    window.location.hash = `preview/${encodeURIComponent(fileId)}`;
}

// 返回文件目录
function goBackToDirectory() {
    // 统一通过清空 hash 回到目录，避免在直接打开预览链接时 history.back() 离开站点
    if (window.location.hash) {
        window.location.hash = '';
    } else {
        showDirectoryView();
    }
}

// 预览页“下载”：复用既有取件流程（含身份验证弹窗）
function requestDownloadFromPreview() {
    if (PreviewController.fileId) {
        requestDownload(PreviewController.fileId);
    }
}

// 预览页“分享”：复用既有协作能力
function shareFromPreview() {
    if (!PreviewController.metadata) return;
    openShareModal(PreviewController.metadata.id, PreviewController.metadata.name);
}

// 元数据加载失败后的整页重试
function retryPreview() {
    if (PreviewController.fileId) {
        loadPreview(PreviewController.fileId);
    }
}

// 读取中断后从当前位置继续
function resumePreview() {
    if (PreviewController.metadata && PreviewController.metadata.file_type === 'text') {
        loadTextPreview(PreviewController.session, PreviewController.metadata);
    }
}

// 显示预览整页错误/空态
function showPreviewError(title, message, icon = '⚠️', retryable = true) {
    resetPreviewDom();
    document.getElementById('previewLoading').style.display = 'none';
    document.getElementById('previewError').style.display = 'block';
    document.getElementById('previewErrorTitle').textContent = title;
    document.getElementById('previewErrorMessage').textContent = message;
    document.getElementById('previewErrorIcon').textContent = icon;
    const retryBtn = document.querySelector('#previewError button');
    if (retryBtn) retryBtn.style.display = retryable ? 'inline-block' : 'none';
}

// 加载文件元数据与摘要
async function loadPreview(fileId) {
    const session = PreviewController.session + 1;
    PreviewController.reset();
    PreviewController.session = session;
    PreviewController.fileId = fileId;

    showPreviewView();
    resetPreviewDom();
    document.getElementById('previewLoading').style.display = 'block';
    document.getElementById('previewLoadingText').textContent = '正在加载文件信息...';

    let metadata;
    try {
        const response = await fetch(`${API_BASE}/files/${encodeURIComponent(fileId)}`, {
            cache: 'no-store'
        });
        if (session !== PreviewController.session) return;

        if (response.status === 404) {
            showPreviewError('文件不存在', '该文件可能已被删除，请返回文件库查看最新列表', '📂', false);
            return;
        }
        if (!response.ok) {
            const result = await response.json().catch(() => ({}));
            showPreviewError('无法预览', result.error || `文件信息加载失败（HTTP ${response.status}）`);
            return;
        }
        metadata = await response.json();
    } catch (error) {
        if (session !== PreviewController.session) return;
        showPreviewError('加载失败', `无法加载文件信息：${error.message}，请检查网络后重试`);
        return;
    }

    if (session !== PreviewController.session) return;
    renderPreviewMetadata(session, metadata);
}

// 渲染元数据、摘要与可用操作
async function renderPreviewMetadata(session, metadata) {
    PreviewController.metadata = metadata;

    resetPreviewDom();
    document.getElementById('previewLoading').style.display = 'none';
    document.getElementById('previewError').style.display = 'none';
    document.getElementById('previewDetail').style.display = 'block';

    document.getElementById('previewFileIcon').textContent = getFileIcon(metadata.name);
    document.getElementById('previewFileName').textContent = metadata.name;
    document.getElementById('previewFileSize').textContent = formatSize(metadata.size);
    document.getElementById('previewFileType').textContent = metadata.type_label;
    document.getElementById('previewCreatedAt').textContent = formatCreatedAt(metadata.created_at);
    document.getElementById('previewFileSizeMeta').textContent = formatSize(metadata.size);

    renderSummary(metadata.summary);

    // 可用操作：下载始终可用（沿用鉴权流程），分享仅登录用户可见
    const isLoggedIn = !!(TokenManager.get() && (await TokenManager.isValid()));
    if (session !== PreviewController.session) return;
    document.getElementById('previewShareBtn').style.display = isLoggedIn ? 'inline-flex' : 'none';

    // 文件数据缺失：展示一致的失败说明，不发起内容读取
    if (!metadata.available) {
        showContentNotice('🗂️', metadata.summary && metadata.summary.message
            ? metadata.summary.message
            : '文件数据缺失或已被移除，暂时无法预览');
        return;
    }

    loadPreviewContent(session, metadata);
}

function renderSummary(summary) {
    if (!summary) return;
    const textEl = document.getElementById('previewSummaryText');
    const msgEl = document.getElementById('previewSummaryMessage');
    const statsEl = document.getElementById('previewSummaryStats');

    if (summary.text) {
        textEl.style.display = 'block';
        textEl.textContent = summary.text + (summary.truncated ? '\n…' : '');
    }

    const message = summary.message || (summary.kind === 'text' && summary.text === '' ? '文件内容为空' : null);
    if (message) {
        msgEl.style.display = 'block';
        msgEl.textContent = message;
    }

    if (summary.kind === 'text' && summary.lines !== null) {
        statsEl.style.display = 'block';
        statsEl.textContent = `共 ${summary.lines} 行 · ${summary.chars} 字符${summary.truncated ? ' · 仅展示文件开头部分' : ''}`;
    }
}

function showContentNotice(icon, text) {
    document.getElementById('previewContentLoading').style.display = 'none';
    document.getElementById('previewContentInterrupted').style.display = 'none';
    document.getElementById('previewContentNotice').style.display = 'flex';
    document.getElementById('previewNoticeIcon').textContent = icon;
    document.getElementById('previewNoticeText').textContent = text;
}

// 根据文件类型加载预览内容
function loadPreviewContent(session, metadata) {
    if (metadata.size === 0) {
        showContentNotice('📄', '文件内容为空');
        return;
    }
    switch (metadata.file_type) {
        case 'text':
            PreviewController.textOffset = 0;
            PreviewController.textTotal = null;
            PreviewController.textBuffer = '';
            loadTextPreview(session, metadata);
            break;
        case 'image':
            loadDirectMedia(session, metadata, 'previewImageContent', '🖼️');
            break;
        case 'video':
            loadDirectMedia(session, metadata, 'previewVideoContent', '🎬');
            break;
        case 'audio':
            loadDirectMedia(session, metadata, 'previewAudioContent', '🎵');
            break;
        case 'pdf':
            ensurePreviewAvailable(session, metadata, 'previewPdfContent', '📄');
            break;
        default:
            showContentNotice('📦', '该文件类型暂不支持在线预览，请点击下方“下载”获取文件');
    }
}

// 每块读取 256KB，配合 Range 请求实现中断保留位置
const TEXT_CHUNK_BYTES = 256 * 1024;

// 文本预览：按字节分块读取；中断后保留已读位置，可从断点重试
async function loadTextPreview(session, metadata) {
    const loadingEl = document.getElementById('previewContentLoading');
    const interruptedEl = document.getElementById('previewContentInterrupted');
    const textEl = document.getElementById('previewTextContent');

    interruptedEl.style.display = 'none';
    loadingEl.style.display = 'block';
    document.getElementById('previewContentLoadingText').textContent =
        PreviewController.textOffset > 0 ? '正在从断点继续读取...' : '正在读取内容...';

    const start = PreviewController.textOffset;
    const end = start + TEXT_CHUNK_BYTES - 1;
    const controller = new AbortController();
    PreviewController.textAbort = controller;

    try {
        const response = await fetch(
            `${API_BASE}/files/${encodeURIComponent(metadata.id)}/preview`,
            {
                cache: 'no-store',
                signal: controller.signal,
                headers: { 'Range': `bytes=${start}-${end}` }
            }
        );
        if (session !== PreviewController.session) return;

        if (!response.ok && response.status !== 206) {
            const result = await response.json().catch(() => ({}));
            throw new Error(result.error || `读取失败（HTTP ${response.status}）`);
        }

        const chunk = await response.text();
        if (session !== PreviewController.session) return;

        const total = parseInt(response.headers.get('X-Content-Total') || '0', 10);
        const chunkStart = parseInt(response.headers.get('X-Content-Start') || String(start), 10);
        const chunkEnd = parseInt(response.headers.get('X-Content-End') || '-1', 10);
        PreviewController.textTotal = total;
        PreviewController.textBuffer += chunk;
        PreviewController.textOffset = chunkEnd >= 0
            ? chunkEnd + 1
            : chunkStart + new Blob([chunk]).size;

        loadingEl.style.display = 'none';
        textEl.style.display = 'block';
        const hasMore = PreviewController.textTotal !== null
            ? PreviewController.textOffset < PreviewController.textTotal
            : chunk.length >= TEXT_CHUNK_BYTES;
        textEl.textContent = PreviewController.textBuffer + (hasMore ? '\n…' : '');

        if (hasMore) {
            // 继续读取下一块，直到读完
            loadTextPreview(session, metadata);
        }
    } catch (error) {
        if (session !== PreviewController.session) return;
        if (error.name === 'AbortError') return;

        // 读取中断：保留当前位置（textOffset 不变），已读内容仍可见，可从断点重试
        loadingEl.style.display = 'none';
        if (PreviewController.textBuffer) {
            textEl.style.display = 'block';
            textEl.textContent = PreviewController.textBuffer + '\n…';
        }
        interruptedEl.style.display = 'flex';
        document.getElementById('previewInterruptedText').textContent =
            `读取中断（已读取 ${formatSize(PreviewController.textOffset)}${
                PreviewController.textTotal ? ' / ' + formatSize(PreviewController.textTotal) : ''
            }）：${error.message}`;
    } finally {
        if (PreviewController.textAbort === controller) {
            PreviewController.textAbort = null;
        }
    }
}

// 图片/音视频：直接以接口地址作为媒体源，浏览器原生支持 Range 缓冲与拖动续读
function loadDirectMedia(session, metadata, elementId, icon) {
    const loadingEl = document.getElementById('previewContentLoading');
    loadingEl.style.display = 'block';
    document.getElementById('previewContentLoadingText').textContent = '正在加载预览内容...';

    const el = document.getElementById(elementId);
    const url = `${API_BASE}/files/${encodeURIComponent(metadata.id)}/preview`;

    const onReady = () => {
        if (session !== PreviewController.session) return;
        loadingEl.style.display = 'none';
        el.style.display = 'block';
    };
    const onError = () => {
        if (session !== PreviewController.session) return;
        loadingEl.style.display = 'none';
        showContentNotice(icon, '预览加载失败，可返回重试或下载后查看');
    };

    // img/iframe 使用 load/error；audio/video 使用 loadeddata/error
    el.onload = onReady;
    el.onerror = onError;
    if (el.tagName === 'VIDEO' || el.tagName === 'AUDIO') {
        el.onload = null;
        el.addEventListener('loadeddata', onReady, { once: true });
        el.addEventListener('error', onError, { once: true });
    }

    el.style.display = 'none';
    el.src = url;
}

// iframe（PDF）无统一错误事件，先探测接口可用性再交给浏览器内置查看器
async function ensurePreviewAvailable(session, metadata, elementId, icon) {
    const loadingEl = document.getElementById('previewContentLoading');
    loadingEl.style.display = 'block';
    document.getElementById('previewContentLoadingText').textContent = '正在加载 PDF...';

    const controller = new AbortController();
    PreviewController.textAbort = controller;
    try {
        const response = await fetch(
            `${API_BASE}/files/${encodeURIComponent(metadata.id)}/preview`,
            { method: 'HEAD', cache: 'no-store', signal: controller.signal }
        );
        if (session !== PreviewController.session) return;
        if (!response.ok) {
            const result = await response.json().catch(() => ({}));
            throw new Error(result.error || `HTTP ${response.status}`);
        }
        loadingEl.style.display = 'none';
        loadDirectMedia(session, metadata, elementId, icon);
    } catch (error) {
        if (session !== PreviewController.session) return;
        if (error.name === 'AbortError') return;
        loadingEl.style.display = 'none';
        showContentNotice(icon, `PDF 预览加载失败：${error.message}`);
    } finally {
        if (PreviewController.textAbort === controller) {
            PreviewController.textAbort = null;
        }
    }
}

// 格式化文件创建时间（兼容 SQLite 的 "YYYY-MM-DD HH:MM:SS" UTC 时间）
function formatCreatedAt(value) {
    if (!value) return '未知';
    let date;
    if (typeof value === 'number') {
        date = new Date(value * 1000);
    } else if (typeof value === 'string' && value.includes(' ') && !value.includes('T')) {
        date = new Date(value.replace(' ', 'T') + 'Z');
    } else {
        date = new Date(value);
    }
    if (isNaN(date.getTime())) return String(value);
    return date.toLocaleString('zh-CN', {
        year: 'numeric', month: '2-digit', day: '2-digit',
        hour: '2-digit', minute: '2-digit'
    });
}

// 基于 hash 的简单路由：#preview/<fileId> 进入预览，其余为目录
function handleRoute() {
    const match = window.location.hash.match(/^#preview\/(.+)$/);
    if (match) {
        const fileId = decodeURIComponent(match[1]);
        // 同一文件重复进入（如目录数据变化后）也重新拉取，保证元数据一致
        loadPreview(fileId);
    } else {
        const wasInPreview = PreviewController.fileId !== null;
        PreviewController.reset();
        showDirectoryView();
        // 从预览返回目录时静默刷新，确保目录与最新数据一致
        if (wasInPreview) loadFileList(true);
    }
}

window.addEventListener('hashchange', handleRoute);
window.addEventListener('pageshow', () => {
    if (window.location.hash.startsWith('#preview/')) {
        handleRoute();
    }
});

// Token 管理
const TokenManager = {
    TOKEN_KEY: 'auth_token',
    USER_KEY: 'auth_user',
    
    save(token, username) {
        localStorage.setItem(this.TOKEN_KEY, token);
        localStorage.setItem(this.USER_KEY, username);
    },
    
    get() {
        return localStorage.getItem(this.TOKEN_KEY);
    },
    
    getUser() {
        return localStorage.getItem(this.USER_KEY);
    },
    
    clear() {
        localStorage.removeItem(this.TOKEN_KEY);
        localStorage.removeItem(this.USER_KEY);
    },
    
    async isValid() {
        const token = this.get();
        if (!token) return false;
        
        try {
            const response = await fetch(`${API_BASE}/refresh-token?token=${token}`, {
                method: 'POST'
            });
            return response.ok;
        } catch {
            return false;
        }
    }
};

// 更新用户状态栏
async function updateUserBar() {
    const userBar = document.getElementById('userBar');
    const currentUser = document.getElementById('currentUser');
    const userAvatar = document.getElementById('userAvatar');
    const user = TokenManager.getUser();
    
    if (user && TokenManager.get() && await TokenManager.isValid()) {
        currentUser.textContent = user;
        userAvatar.textContent = user.charAt(0).toUpperCase();
        userBar.classList.remove('hidden');
        loadMyShares();
    } else {
        userBar.classList.add('hidden');
        const shareSection = document.getElementById('mySharesSection');
        if (shareSection) {
            shareSection.style.display = 'none';
        }
    }
}

// 退出登录
function logout() {
    TokenManager.clear();
    updateUserBar();
}

// 页面加载时获取文件列表和更新用户状态
document.addEventListener('DOMContentLoaded', async () => {
    // 检查token是否有效，无效则清除
    if (TokenManager.get() && !(await TokenManager.isValid())) {
        TokenManager.clear();
    }
    await updateUserBar();
    // 若直接以 #preview/<id> 打开，则由路由进入预览（目录列表仍在后台加载）
    handleRoute();
    loadFileList();
});

// 验证文件
function validateFile(file) {
    if (file.size > CONFIG.MAX_FILE_SIZE) {
        return `文件大小超过限制（最大${CONFIG.MAX_FILE_SIZE / 1024 / 1024}MB）`;
    }
    return null;
}

// 上传文件处理函数
async function uploadFile(file) {
    const validationError = validateFile(file);
    if (validationError) {
        document.getElementById('uploadStatus').textContent = `❌ ${validationError}`;
        return;
    }

    showLoading('上传中...');
    
    const formData = new FormData();
    formData.append('file', file);

    try {
        const response = await fetch(`${API_BASE}/upload`, {
            method: 'POST',
            body: formData
        });
        const result = await response.json();
        
        if (response.ok) {
            document.getElementById('uploadStatus').textContent = `✅ ${file.name} 上传成功！`;
            loadFileList();
        } else {
            document.getElementById('uploadStatus').textContent = `❌ 上传失败: ${result.error}`;
        }
    } catch (error) {
        document.getElementById('uploadStatus').textContent = `❌ 上传失败: ${error.message}`;
    } finally {
        hideLoading();
    }
}

// 文件选择上传
document.getElementById('fileInput').addEventListener('change', async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    await uploadFile(file);
    e.target.value = '';
});

// 拖拽上传
const uploadZone = document.querySelector('.upload-zone');

uploadZone.addEventListener('dragover', (e) => {
    e.preventDefault();
    uploadZone.classList.add('drag-over');
});

uploadZone.addEventListener('dragleave', (e) => {
    e.preventDefault();
    uploadZone.classList.remove('drag-over');
});

uploadZone.addEventListener('drop', async (e) => {
    e.preventDefault();
    uploadZone.classList.remove('drag-over');
    
    const file = e.dataTransfer.files[0];
    if (file) {
        await uploadFile(file);
    }
});

// 加载文件列表
async function loadFileList(silent = false) {
    if (!silent) showLoading('加载文件列表...');

    try {
        const response = await fetch(`${API_BASE}/files`);
        const files = await response.json();

        const fileList = document.getElementById('fileList');
        const isLoggedIn = TokenManager.get() && (await TokenManager.isValid());

        if (files.length === 0) {
            fileList.innerHTML = '<p class="empty-msg">暂无可下载文件</p>';
        } else {
            fileList.innerHTML = files.map(file => `
                <div class="file-item">
                    <div class="file-info">
                        <div class="file-icon">${getFileIcon(file.name)}</div>
                        <div class="file-details">
                            <div class="file-name">${escapeHtml(file.name)}</div>
                            <div class="file-size">${formatSize(file.size)}</div>
                        </div>
                    </div>
                    <div class="file-actions">
                        <button class="preview-btn" onclick="openPreview('${escapeHtml(file.id)}')" title="预览文件与元数据">
                            预览
                        </button>
                        ${isLoggedIn ? `<button class="share-btn" onclick="openShareModal('${escapeHtml(file.id)}', '${escapeHtml(file.name)}')">分享</button>` : ''}
                        <button class="download-btn" onclick="requestDownload('${escapeHtml(file.id)}')">
                            下载
                        </button>
                    </div>
                </div>
            `).join('');
        }
    } catch (error) {
        document.getElementById('fileList').innerHTML =
            `<p class="empty-msg">加载失败: ${escapeHtml(error.message)}</p>`;
    } finally {
        if (!silent) hideLoading();
    }
}

// HTML转义防止XSS
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// 请求下载 - 检查token是否有效，有效则直接下载
async function requestDownload(fileId) {
    showLoading('检查授权...');
    
    // 检查是否有有效的token
    if (await TokenManager.isValid()) {
        // token有效，使用 fetch + Authorization 头下载
        document.getElementById('loadingText').textContent = '正在下载...';
        try {
            const response = await fetch(`${API_BASE}/download/${fileId}`, {
                method: 'GET',
                headers: {
                    'Authorization': `Bearer ${TokenManager.get()}`
                }
            });
            if (response.ok) {
                const blob = await response.blob();
                const contentDisposition = response.headers.get('Content-Disposition');
                let filename = 'download';
                if (contentDisposition) {
                    const match = contentDisposition.match(/filename\*?=(?:UTF-8'')?["']?([^"';\n]+)/i);
                    if (match) filename = decodeURIComponent(match[1]);
                }
                const url = window.URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url;
                a.download = filename;
                document.body.appendChild(a);
                a.click();
                window.URL.revokeObjectURL(url);
                a.remove();
            } else {
                const result = await response.json();
                alert(`下载失败: ${result.error || '未知错误'}`);
            }
        } catch (error) {
            alert(`下载失败: ${error.message}`);
        } finally {
            hideLoading();
        }
        return;
    }
    
    // token无效或不存在，弹出登录框
    hideLoading();
    TokenManager.clear();
    document.getElementById('downloadFileId').value = fileId;
    document.getElementById('authModal').classList.add('active');
    document.getElementById('authError').textContent = '';
    document.getElementById('username').value = '';
    document.getElementById('password').value = '';
    document.getElementById('username').focus();
}

// 关闭验证弹窗
function closeAuthModal() {
    document.getElementById('authModal').classList.remove('active');
}

// 身份验证表单提交
document.getElementById('authForm').addEventListener('submit', async (e) => {
    e.preventDefault();
    
    const username = document.getElementById('username').value.trim();
    const password = document.getElementById('password').value;
    const fileId = document.getElementById('downloadFileId').value;

    if (!username || !password) {
        document.getElementById('authError').textContent = '请输入用户名和密码';
        return;
    }

    showLoading('验证身份...');
    
    try {
        const response = await fetch(`${API_BASE}/auth`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ username, password })
        });
        
        const result = await response.json();
        
        if (response.ok && result.success) {
            // 保存token和用户名到本地
            TokenManager.save(result.token, username);
            await updateUserBar();
            loadFileList();
            
            closeAuthModal();
            document.getElementById('loadingText').textContent = '验证成功，正在下载...';
            
            // 使用 fetch + Authorization 头下载
            try {
                const downloadResponse = await fetch(`${API_BASE}/download/${fileId}`, {
                    method: 'GET',
                    headers: {
                        'Authorization': `Bearer ${result.token}`
                    }
                });
                if (downloadResponse.ok) {
                    const blob = await downloadResponse.blob();
                    const contentDisposition = downloadResponse.headers.get('Content-Disposition');
                    let filename = 'download';
                    if (contentDisposition) {
                        const match = contentDisposition.match(/filename\*?=(?:UTF-8'')?["']?([^"';\n]+)/i);
                        if (match) filename = decodeURIComponent(match[1]);
                    }
                    const url = window.URL.createObjectURL(blob);
                    const a = document.createElement('a');
                    a.href = url;
                    a.download = filename;
                    document.body.appendChild(a);
                    a.click();
                    window.URL.revokeObjectURL(url);
                    a.remove();
                } else {
                    const errResult = await downloadResponse.json();
                    document.getElementById('authError').textContent = `下载失败: ${errResult.error || '未知错误'}`;
                }
            } catch (downloadError) {
                document.getElementById('authError').textContent = `下载失败: ${downloadError.message}`;
            } finally {
                hideLoading();
            }
        } else if (response.status === 429) {
            hideLoading();
            document.getElementById('authError').textContent = '请求过于频繁，请稍后再试';
        } else {
            hideLoading();
            document.getElementById('authError').textContent = result.error || '验证失败，请检查账号密码';
        }
    } catch (error) {
        hideLoading();
        document.getElementById('authError').textContent = `验证失败: ${error.message}`;
    }
});

// 显示加载动画
function showLoading(text = '加载中...') {
    document.getElementById('loadingText').textContent = text;
    document.getElementById('loadingOverlay').classList.add('active');
}

// 隐藏加载动画
function hideLoading() {
    document.getElementById('loadingOverlay').classList.remove('active');
}

// 获取文件图标
function getFileIcon(filename) {
    const ext = filename.split('.').pop().toLowerCase();
    const icons = {
        pdf: '📄', doc: '📝', docx: '📝', txt: '📃',
        jpg: '🖼️', jpeg: '🖼️', png: '🖼️', gif: '🖼️',
        mp3: '🎵', wav: '🎵', mp4: '🎬', avi: '🎬',
        zip: '📦', rar: '📦', '7z': '📦',
        js: '💻', py: '🐍', html: '🌐', css: '🎨'
    };
    return icons[ext] || '📁';
}

// 格式化文件大小
function formatSize(bytes) {
    if (bytes === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
}

// 格式化时间戳
function formatTimestamp(timestamp) {
    if (!timestamp) return '永久有效';
    const date = new Date(timestamp * 1000);
    return date.toLocaleString('zh-CN', {
        year: 'numeric',
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit'
    });
}

// 格式化剩余时间
function formatRemainingTime(expiresAt) {
    if (!expiresAt) return '永久';
    const remaining = expiresAt - (Date.now() / 1000);
    if (remaining <= 0) return '已过期';
    
    const hours = Math.floor(remaining / 3600);
    const minutes = Math.floor((remaining % 3600) / 60);
    
    if (hours > 24) {
        const days = Math.floor(hours / 24);
        return `${days} 天 ${hours % 24} 小时`;
    } else if (hours > 0) {
        return `${hours} 小时 ${minutes} 分钟`;
    } else {
        return `${minutes} 分钟`;
    }
}

// 打开分享设置弹窗
function openShareModal(fileId, fileName) {
    currentShareFileId = fileId;
    document.getElementById('shareFileName').textContent = fileName;
    document.getElementById('shareError').textContent = '';
    document.getElementById('expireHours').value = '24';
    document.getElementById('maxDownloads').value = '10';
    document.getElementById('shareModal').classList.add('active');
}

// 关闭分享设置弹窗
function closeShareModal() {
    document.getElementById('shareModal').classList.remove('active');
    currentShareFileId = null;
}

// 确认创建分享链接
async function confirmCreateShare() {
    if (!currentShareFileId) return;
    
    const expireHours = parseInt(document.getElementById('expireHours').value);
    const maxDownloads = parseInt(document.getElementById('maxDownloads').value);
    
    showLoading('生成分享链接...');
    document.getElementById('shareError').textContent = '';
    
    try {
        const response = await fetch(`${API_BASE}/share`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${TokenManager.get()}`
            },
            body: JSON.stringify({
                file_id: currentShareFileId,
                expire_hours: expireHours,
                max_downloads: maxDownloads
            })
        });
        
        const result = await response.json();
        
        if (response.ok && result.success) {
            closeShareModal();
            showShareSuccessModal(result);
            loadMyShares();
        } else {
            document.getElementById('shareError').textContent = result.error || '生成分享链接失败';
        }
    } catch (error) {
        document.getElementById('shareError').textContent = `错误: ${error.message}`;
    } finally {
        hideLoading();
    }
}

// 显示分享成功弹窗
function showShareSuccessModal(result) {
    currentShareLink = `${window.location.origin}/share.html#${result.share_id}`;
    
    document.getElementById('shareLinkInput').value = currentShareLink;
    document.getElementById('shareInfoName').textContent = result.filename;
    document.getElementById('shareInfoExpire').textContent = formatTimestamp(result.expires_at);
    document.getElementById('shareInfoDownloads').textContent = result.max_downloads ? `${result.max_downloads} 次` : '无限制';
    document.getElementById('copyBtnText').textContent = '复制';
    
    const copyBtn = document.querySelector('.copy-btn');
    copyBtn.classList.remove('copied');
    
    document.getElementById('shareSuccessModal').classList.add('active');
}

// 关闭分享成功弹窗
function closeShareSuccessModal() {
    document.getElementById('shareSuccessModal').classList.remove('active');
    currentShareLink = null;
}

// 复制分享链接
async function copyShareLink() {
    const linkInput = document.getElementById('shareLinkInput');
    const copyBtnText = document.getElementById('copyBtnText');
    const copyBtn = document.querySelector('.copy-btn');
    
    try {
        await navigator.clipboard.writeText(linkInput.value);
        copyBtnText.textContent = '已复制';
        copyBtn.classList.add('copied');
        
        setTimeout(() => {
            copyBtnText.textContent = '复制';
            copyBtn.classList.remove('copied');
        }, 2000);
    } catch (error) {
        linkInput.select();
        document.execCommand('copy');
        copyBtnText.textContent = '已复制';
        copyBtn.classList.add('copied');
        
        setTimeout(() => {
            copyBtnText.textContent = '复制';
            copyBtn.classList.remove('copied');
        }, 2000);
    }
}

// 加载我的分享列表
async function loadMyShares() {
    const section = document.getElementById('mySharesSection');
    const list = document.getElementById('mySharesList');
    
    if (!(await TokenManager.isValid())) {
        section.style.display = 'none';
        return;
    }
    
    section.style.display = 'block';
    
    try {
        const response = await fetch(`${API_BASE}/shares`, {
            headers: {
                'Authorization': `Bearer ${TokenManager.get()}`
            }
        });
        
        const shares = await response.json();
        
        if (shares.length === 0) {
            list.innerHTML = '<p class="empty-msg">暂无分享链接</p>';
            return;
        }
        
        list.innerHTML = shares.map(share => {
            const statusClass = share.is_valid ? 'valid' : 'invalid';
            const statusText = share.is_valid ? '有效' : (share.error_msg || '无效');
            
            return `
                <div class="share-item">
                    <div class="share-item-header">
                        <span class="share-item-filename">${escapeHtml(share.filename)}</span>
                        <span class="share-item-status ${statusClass}">${statusText}</span>
                    </div>
                    <div class="share-item-details">
                        <div class="share-item-detail">
                            <span class="share-item-detail-label">剩余时间</span>
                            <span class="share-item-detail-value">${formatRemainingTime(share.expires_at)}</span>
                        </div>
                        <div class="share-item-detail">
                            <span class="share-item-detail-label">已下载</span>
                            <span class="share-item-detail-value">${share.download_count} / ${share.max_downloads || '∞'}</span>
                        </div>
                        <div class="share-item-detail">
                            <span class="share-item-detail-label">创建时间</span>
                            <span class="share-item-detail-value">${new Date(share.created_at).toLocaleString('zh-CN')}</span>
                        </div>
                    </div>
                    <div class="share-item-actions">
                        <button class="copy-link-btn" onclick="copyShareLinkFromList('${share.share_id}')">
                            🔗 复制链接
                        </button>
                        <button class="delete-share-btn" onclick="deleteShare('${share.share_id}')">
                            🗑️ 删除
                        </button>
                    </div>
                </div>
            `;
        }).join('');
    } catch (error) {
        list.innerHTML = `<p class="empty-msg">加载失败: ${escapeHtml(error.message)}</p>`;
    }
}

// 从分享列表复制链接
async function copyShareLinkFromList(shareId) {
    const link = `${window.location.origin}/share.html#${shareId}`;
    try {
        await navigator.clipboard.writeText(link);
        alert('分享链接已复制到剪贴板');
    } catch (error) {
        prompt('请手动复制链接:', link);
    }
}

// 删除分享链接
async function deleteShare(shareId) {
    if (!confirm('确定要删除此分享链接吗？删除后链接将立即失效。')) {
        return;
    }
    
    showLoading('删除中...');
    
    try {
        const response = await fetch(`${API_BASE}/share/${shareId}`, {
            method: 'DELETE',
            headers: {
                'Authorization': `Bearer ${TokenManager.get()}`
            }
        });
        
        if (response.ok) {
            loadMyShares();
        } else {
            const result = await response.json();
            alert(`删除失败: ${result.error || '未知错误'}`);
        }
    } catch (error) {
        alert(`删除失败: ${error.message}`);
    } finally {
        hideLoading();
    }
}


