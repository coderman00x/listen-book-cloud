// 听书宝前端 API 客户端。
//
// 约定（见 docs/ARCHITECTURE.md 第 7 节）：
// - baseURL 取 import.meta.env.VITE_API_BASE || '/api'
//   开发态由 Vite proxy 将 /api 转发到 http://localhost:8000；
//   运行态后端同源托管，无需切换。
// - 统一响应信封 { code, data, message }，code==0 成功；非 0 抛错（含 message）。
// - 所有错误统一抛出携带 message 的 Error，由上层（Snackbar）提示。

const BASE_URL = import.meta.env.VITE_API_BASE || '/api';

// ---- v1.3 增量：访问口令管理（localStorage 明文存储，轻量防护非加密）----
const TOKEN_KEY = 'listenbook_token';

/** 读取已保存的访问口令（空串表示未设置）。 */
export const getToken = () => localStorage.getItem(TOKEN_KEY) || '';

/** 保存/清除访问口令：传入空值则清除。 */
export const setToken = (t) =>
  t ? localStorage.setItem(TOKEN_KEY, t) : localStorage.removeItem(TOKEN_KEY);

/** 清除访问口令。 */
export const clearToken = () => localStorage.removeItem(TOKEN_KEY);

/**
 * 给媒体/下载类 URL 追加 ?token=。
 * <audio src> 与 <a download> 这类浏览器原生请求无法附加自定义 Header，
 * 故其 token 必须以查询参数形式携带。
 * 已带 ? 时改用 & 连接；并对 token 做 URL 编码。
 */
export const withToken = (url) => {
  const t = getToken();
  if (!t) return url;
  const sep = url.includes('?') ? '&' : '?';
  return `${url}${sep}token=${encodeURIComponent(t)}`;
};

/**
 * 底层请求封装。
 * @param {string} method HTTP 方法
 * @param {string} path 接口路径（不含 baseURL）
 * @param {object} [options]
 * @param {any} [options.body] JSON 请求体（isForm=false 时序列化）
 * @param {boolean} [options.isForm] 是否为 FormData（multipart）
 * @returns {Promise<any>} 解析后的 data 字段
 */
async function request(method, path, options = {}) {
  const { body, isForm = false } = options;
  const headers = {};
  // v1.3 增量：若已保存口令，所有 fetch 类 /api 请求自动附加 X-Access-Token
  const token = getToken();
  if (token) headers['X-Access-Token'] = token;
  let payload;
  if (isForm) {
    payload = body; // FormData，浏览器自动设置 Content-Type
  } else if (body !== undefined) {
    headers['Content-Type'] = 'application/json';
    payload = JSON.stringify(body);
  }

  let resp;
  try {
    resp = await fetch(`${BASE_URL}${path}`, { method, headers, body: payload });
  } catch (e) {
    const err = new Error(`网络错误：${e.message}`);
    err.code = -1;
    throw err;
  }

  const contentType = resp.headers.get('content-type') || '';
  let result = null;
  if (contentType.includes('application/json')) {
    result = await resp.json();
  }

  if (!resp.ok || (result && result.code !== 0)) {
    const message = (result && result.message) || `请求失败 (${resp.status})`;
    const err = new Error(message);
    err.code = result ? result.code : resp.status;
    err.status = resp.status;
    throw err;
  }
  return result ? result.data : null;
}

export const api = {
  health: () => request('GET', '/health'),

  // 导入多本 txt：files 为 File[]，以 multipart files[] 上传（仅内容被读取）
  importBooks: (files) => {
    const form = new FormData();
    files.forEach((f) => form.append('files', f));
    return request('POST', '/books/import', { body: form, isForm: true });
  },

  listBooks: () => request('GET', '/books'),
  getBook: (id) => request('GET', `/books/${id}`),
  getProgress: (id) => request('GET', `/books/${id}/progress`),

  // 章节列表：返回 { chapters: [...] }（含 index/title/duration_sec/size_bytes）
  getChapters: (id) => request('GET', `/books/${id}/chapters`),

  generate: (id, payload) =>
    request('POST', `/books/${id}/generate`, { body: payload || {} }),
  retry: (id) => request('POST', `/books/${id}/retry`),
  deleteBook: (id) => request('DELETE', `/books/${id}`),

  // 音频流地址（用于 <audio src>），支持 Range（v1.3：自动带 ?token=）
  getAudioUrl: (id) => withToken(`${BASE_URL}/books/${id}/audio`),
  // 按章音频流地址（id + 0-based 章索引）（v1.3：自动带 ?token=）
  getChapterAudioUrl: (id, idx) =>
    withToken(`${BASE_URL}/books/${id}/chapters/${idx}/audio`),

  listVoices: () => request('GET', '/voices'),
  getSettings: () => request('GET', '/settings'),
  putSettings: (payload) => request('PUT', '/settings', { body: payload }),

  // ---- v1.2 增量：导出 / 断点续听 / 书签 ----
  // 整本导出下载地址（用于 <a download> 或 window.open；后端返回 audio/mpeg + attachment）
  // v1.3 增量：自动带 ?token=，否则启用口令后下载会 401
  exportBookUrl: (id) => withToken(`${BASE_URL}/books/${id}/export`),
  // v1.4 增量：分章 zip 导出下载地址（每章一个 mp3，可逐章跳转）；同样自动带 ?token=
  exportChaptersUrl: (id) =>
    withToken(`${BASE_URL}/books/${id}/export?mode=chapters`),

  // v1.3 增量：网络访问信息（免 token 白名单，但也可带 token）
  networkInfo: () => request('GET', '/network/info'),
  // 上报/更新断点续听位置
  postPosition: (id, chapter, time) =>
    request('POST', `/books/${id}/position`, { body: { chapter, time } }),
  // 书签列表
  listBookmarks: (id) => request('GET', `/books/${id}/bookmarks`),
  // 新增书签：payload = { chapter, time, label }
  addBookmark: (id, payload) =>
    request('POST', `/books/${id}/bookmarks`, { body: payload }),
  // 删除书签
  deleteBookmark: (id, bkId) =>
    request('DELETE', `/books/${id}/bookmarks/${bkId}`),
};

export default api;
