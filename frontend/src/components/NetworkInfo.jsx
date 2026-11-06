import React, { useEffect, useState } from 'react';
import {
  Alert,
  Box,
  Button,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  List,
  ListItem,
  ListItemText,
  TextField,
  Typography,
} from '@mui/material';
import QRCode from 'qrcode';
import api, { getToken, setToken } from '../api/client.js';

// 手机访问 / 扫码面板（v1.3 增量；v2.0 增加公网模式分支）。
// 拉取 /api/network/info（免 token）：
// - mode === 'public'：显示公网 HTTPS 地址，隐藏容器内网 IP 与二维码（对手机无意义），
//   并单独给出「导出 mp3 到手机离线听」引导；口令输入保持共用。
// - 其它（mode === 'lan' 或旧版无 mode）：完全保持 v1.4 局域网版内容与行为。
export default function NetworkInfo({ open, onClose }) {
  const [info, setInfo] = useState(null);
  const [qr, setQr] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [tokenInput, setTokenInput] = useState('');
  const [tokenMsg, setTokenMsg] = useState('');

  useEffect(() => {
    if (!open) return;
    setLoading(true);
    setError('');
    setTokenMsg('');
    setInfo(null);
    setQr('');
    api
      .networkInfo()
      .then((data) => {
        setInfo(data);
        // 公网模式不生成二维码：容器内网 IP 手机扫不开，也没有扫码的必要
        if (data && data.mode === 'public') return '';
        return QRCode.toDataURL(data.access_url);
      })
      .then((url) => {
        if (url) setQr(url);
      })
      .catch((e) => setError(e.message || '获取网络信息失败'))
      .finally(() => setLoading(false));
  }, [open]);

  const handleSaveToken = async () => {
    setTokenMsg('');
    if (!tokenInput) {
      setTokenMsg('请输入访问口令');
      return;
    }
    setToken(tokenInput);
    try {
      // 用带 token 的请求验证口令是否正确
      await api.listBooks();
      setTokenMsg('口令已保存并验证通过，请刷新页面使全部请求生效。');
    } catch (e) {
      setToken(''); // 验证失败回滚
      setTokenMsg(`口令验证失败：${e.message}`);
    }
  };

  const tokenFailed = !!tokenMsg && tokenMsg.includes('失败');
  const isPublic = !!info && info.mode === 'public';
  const publicUrl = (info && info.public_url) || window.location.origin;

  return (
    <Dialog open={open} onClose={onClose} maxWidth="xs" fullWidth>
      <DialogTitle>
        {isPublic ? '☁️ 云端听书 · 传到手机' : '手机访问 / 扫码'}
      </DialogTitle>
      <DialogContent>
        {loading && (
          <Box sx={{ display: 'flex', justifyContent: 'center', py: 2 }}>
            <CircularProgress size={28} />
          </Box>
        )}
        {error && (
          <Alert severity="error" sx={{ mb: 1 }}>
            {error}
          </Alert>
        )}

        {/* ---- 局域网 / 本地分支：保持 v1.4 原样 ---- */}
        {info && !isPublic && (
          <Box sx={{ textAlign: 'center' }}>
            <Typography variant="body2" color="text.secondary">
              局域网可访问地址
            </Typography>
            <Typography variant="subtitle1" sx={{ wordBreak: 'break-all' }}>
              {info.access_url}
            </Typography>

            {qr && (
              <Box sx={{ my: 2 }}>
                <img
                  src={qr}
                  alt="访问二维码"
                  style={{ width: 200, height: 200 }}
                />
              </Box>
            )}

            <Typography variant="caption" color="text.secondary">
              手机连同一 WiFi 后，扫码或访问上方地址即可打开本应用。
            </Typography>
          </Box>
        )}

        {/* ---- 公网分支：只显示公网地址，不渲染内网 IP / 二维码 ---- */}
        {isPublic && (
          <Box sx={{ textAlign: 'center' }}>
            <Typography variant="body2" color="text.secondary">
              公网 HTTPS 地址（手机可直接打开）
            </Typography>
            <Typography variant="subtitle1" sx={{ wordBreak: 'break-all' }}>
              {publicUrl}
            </Typography>
            <Typography
              variant="caption"
              color="text.secondary"
              sx={{ display: 'block', mt: 1 }}
            >
              手机 Safari / 浏览器打开此地址即可，无需与电脑同一 WiFi，电脑可以关机。
            </Typography>
            {info.hint && (
              <Typography
                variant="caption"
                color="text.secondary"
                sx={{ display: 'block', mt: 1 }}
              >
                {info.hint}
              </Typography>
            )}
          </Box>
        )}

        {info && !info.access_token_required && (
          <Alert severity="warning" sx={{ mt: 2 }}>
            {isPublic
              ? '公网模式未设置 ACCESS_TOKEN：任何人都能访问本服务，请立即在平台环境变量配置口令。'
              : '未设访问口令，服务对局域网开放，仅在信任 WiFi 下使用。'}
          </Alert>
        )}

        {info && info.access_token_required && (
          <Box sx={{ mt: 2 }}>
            <Typography variant="body2" sx={{ mb: 1 }}>
              本服务已启用访问口令，请输入：
            </Typography>
            <TextField
              size="small"
              fullWidth
              type="password"
              value={tokenInput}
              placeholder="访问口令"
              onChange={(e) => setTokenInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') handleSaveToken();
              }}
            />
            <Button
              sx={{ mt: 1 }}
              variant="contained"
              onClick={handleSaveToken}
            >
              保存口令
            </Button>
            {tokenMsg && (
              <Alert severity={tokenFailed ? 'error' : 'success'} sx={{ mt: 1 }}>
                {tokenMsg}
              </Alert>
            )}
            {getToken() && !tokenFailed && (
              <Typography
                variant="caption"
                color="text.secondary"
                sx={{ display: 'block', mt: 1 }}
              >
                当前已保存口令，后续请求将自动携带。
              </Typography>
            )}
          </Box>
        )}

        {/* ---- 公网分支：导出到手机离线听（v2.0 独立实现）---- */}
        {isPublic && (
          <Box sx={{ mt: 2, p: 1.5, border: '1px solid', borderColor: 'divider', borderRadius: 1 }}>
            <Typography variant="subtitle2" sx={{ mb: 1 }}>
              📱 导出 mp3 到手机离线听
            </Typography>
            <List dense disablePadding>
              <ListItem sx={{ display: 'list-item' }}>
                <ListItemText
                  primary="1. 导入书并等生成完成"
                  secondary="在手机上导入 txt/epub/pdf，生成全程在云端进行；手机无需电脑，电脑可以关机。"
                />
              </ListItem>
              <ListItem sx={{ display: 'list-item' }}>
                <ListItemText
                  primary="2. 点书上的「导出 ▾」"
                  secondary="选择「整本 mp3」或「分章 zip」，文件即开始下载。"
                />
              </ListItem>
              <ListItem sx={{ display: 'list-item' }}>
                <ListItemText
                  primary="3. iPhone 存到「文件」App"
                  secondary="若自动播放而非下载，点「分享」→「存储到文件」保存到“文件”App。"
                />
              </ListItem>
              <ListItem sx={{ display: 'list-item' }}>
                <ListItemText
                  primary="4. 离线收听"
                  secondary="用“文件”App 或任意播放器离线听；导出后电脑与云端都不需要。"
                />
              </ListItem>
              <ListItem sx={{ display: 'list-item' }}>
                <ListItemText
                  primary="5. 免费层会休眠"
                  secondary="云端空闲会休眠、重启后书架可能清空，但已导出的 mp3 在手机里不受影响。"
                />
              </ListItem>
            </List>
          </Box>
        )}

        {/* ---- 局域网 / 本地分支：保持 v1.4 原引导不动 ---- */}
        {info && !isPublic && (
          <Box sx={{ mt: 2, p: 1.5, border: '1px solid', borderColor: 'divider', borderRadius: 1 }}>
            <Typography variant="subtitle2" sx={{ mb: 1 }}>
              📱 传到手机听书
            </Typography>
            <List dense disablePadding>
              <ListItem sx={{ display: 'list-item' }}>
                <ListItemText
                  primary="1. 电脑端生成"
                  secondary="在电脑上导入并生成完成（生成时电脑需保持开机）。"
                />
              </ListItem>
              <ListItem sx={{ display: 'list-item' }}>
                <ListItemText
                  primary="2. 手机连同一 WiFi"
                  secondary="手机连接与电脑相同的 WiFi，扫码或访问上方地址打开本应用。"
                />
              </ListItem>
              <ListItem sx={{ display: 'list-item' }}>
                <ListItemText
                  primary="3. 手机上导出"
                  secondary="在手机上点书籍的「导出整本」或「导出分章」，文件即开始下载。"
                />
              </ListItem>
              <ListItem sx={{ display: 'list-item' }}>
                <ListItemText
                  primary="4. iPhone 存到文件"
                  secondary="若点击后自动播放而非下载，点右上角「分享」→「存储到文件」存到“文件”App。"
                />
              </ListItem>
              <ListItem sx={{ display: 'list-item' }}>
                <ListItemText
                  primary="5. 离线收听"
                  secondary="用“文件”App 或任意播放器离线听；导出到手机后电脑即可关闭。"
                />
              </ListItem>
            </List>
          </Box>
        )}
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>关闭</Button>
      </DialogActions>
    </Dialog>
  );
}
