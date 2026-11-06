import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
} from 'react';
import {
  Alert,
  AppBar,
  Box,
  Button,
  Container,
  Snackbar,
  Toolbar,
  Typography,
} from '@mui/material';
import SettingsIcon from '@mui/icons-material/Settings';
import QrCodeIcon from '@mui/icons-material/QrCode2';
import ImportZone from './components/ImportZone.jsx';
import Bookshelf from './components/Bookshelf.jsx';
import PlayerDrawer from './components/PlayerDrawer.jsx';
import SettingsPanel from './components/SettingsPanel.jsx';
import NetworkInfo from './components/NetworkInfo.jsx';
import api from './api/client.js';

// 全局 Context：集中管理 books / playing / settings / 通知 等共享状态
const AppContext = createContext(null);
export const useApp = () => useContext(AppContext);

export default function App() {
  const [books, setBooks] = useState([]);
  const [settings, setSettings] = useState({
    default_voice: 'zh-CN-XiaoxiaoNeural',
    default_rate: '+0%',
  });
  const [voices, setVoices] = useState([]);
  const [playing, setPlaying] = useState(null); // 当前播放的 Book
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [networkOpen, setNetworkOpen] = useState(false);
  const [snack, setSnack] = useState({ open: false, message: '', severity: 'info' });

  const notify = useCallback((message, severity = 'info') => {
    setSnack({ open: true, message, severity });
  }, []);

  const refreshBooks = useCallback(async () => {
    try {
      const res = await api.listBooks();
      setBooks(res.books || []);
    } catch (e) {
      notify(e.message, 'error');
    }
  }, [notify]);

  const loadSettings = useCallback(async () => {
    try {
      const s = await api.getSettings();
      if (s) setSettings(s);
    } catch (e) {
      /* 忽略，使用默认 */
    }
  }, []);

  const loadVoices = useCallback(async () => {
    try {
      const res = await api.listVoices();
      setVoices(res.voices || []);
    } catch (e) {
      notify(e.message, 'error');
    }
  }, [notify]);

  const importFiles = useCallback(
    async (files) => {
      try {
        const res = await api.importBooks(files);
        notify(`已加入 ${res.books.length} 本书`, 'success');
        await refreshBooks();
      } catch (e) {
        notify(e.message, 'error');
      }
    },
    [notify, refreshBooks]
  );

  const deleteBook = useCallback(
    async (id) => {
      try {
        await api.deleteBook(id);
        if (playing && playing.id === id) setPlaying(null);
        notify('已删除（仅应用内数据，原始文件不受影响）', 'success');
        await refreshBooks();
      } catch (e) {
        notify(e.message, 'error');
      }
    },
    [notify, playing, refreshBooks]
  );

  const retryBook = useCallback(
    async (id) => {
      try {
        await api.retry(id);
        notify('已重新加入生成队列', 'info');
        await refreshBooks();
      } catch (e) {
        notify(e.message, 'error');
      }
    },
    [notify, refreshBooks]
  );

  const playBook = useCallback(async (book) => {
    // 透传该书对象（含 playback/bookmarks）：优先取服务端最新元数据，失败回退本地对象
    try {
      const fresh = await api.getBook(book.id);
      setPlaying(fresh);
    } catch (e) {
      setPlaying(book);
    }
  }, []);

  const saveSettings = useCallback(
    async (payload) => {
      try {
        const s = await api.putSettings(payload);
        setSettings(s);
        notify('设置已保存，新导入书籍将套用', 'success');
      } catch (e) {
        notify(e.message, 'error');
      }
    },
    [notify]
  );

  // 首屏加载：设置 / 音色 / 书架
  useEffect(() => {
    loadSettings();
    loadVoices();
    refreshBooks();
  }, [loadSettings, loadVoices, refreshBooks]);

  const ctx = {
    books,
    settings,
    voices,
    playing,
    notify,
    refreshBooks,
    importFiles,
    deleteBook,
    retryBook,
    playBook,
    saveSettings,
    setSettingsOpen,
  };

  return (
    <AppContext.Provider value={ctx}>
      <Box
        sx={{
          minHeight: '100%',
          pb: playing ? 14 : 4,
          bgcolor: 'background.default',
        }}
      >
        <AppBar position="static">
          <Toolbar>
            <Typography variant="h6" sx={{ flexGrow: 1 }}>
              听书宝 listen_book
            </Typography>
            <Button
              color="inherit"
              startIcon={<QrCodeIcon />}
              onClick={() => setNetworkOpen(true)}
            >
              手机访问
            </Button>
            <Button
              color="inherit"
              startIcon={<SettingsIcon />}
              onClick={() => setSettingsOpen(true)}
            >
              设置
            </Button>
          </Toolbar>
        </AppBar>

        <Container maxWidth="md" sx={{ mt: 3 }}>
          <ImportZone />
          <Bookshelf />
        </Container>

        <PlayerDrawer />
        <SettingsPanel open={settingsOpen} onClose={() => setSettingsOpen(false)} />
        <NetworkInfo open={networkOpen} onClose={() => setNetworkOpen(false)} />

        <Snackbar
          open={snack.open}
          autoHideDuration={3500}
          onClose={() => setSnack((s) => ({ ...s, open: false }))}
          anchorOrigin={{ vertical: 'bottom', horizontal: 'center' }}
        >
          <Alert
            severity={snack.severity}
            variant="filled"
            onClose={() => setSnack((s) => ({ ...s, open: false }))}
          >
            {snack.message}
          </Alert>
        </Snackbar>
      </Box>
    </AppContext.Provider>
  );
}
