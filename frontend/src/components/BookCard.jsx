import React, { useState } from 'react';
import {
  Box,
  Button,
  Card,
  CardContent,
  Chip,
  LinearProgress,
  Menu,
  MenuItem,
  Stack,
  Typography,
} from '@mui/material';
import PlayArrowIcon from '@mui/icons-material/PlayArrow';
import DeleteIcon from '@mui/icons-material/Delete';
import RefreshIcon from '@mui/icons-material/Refresh';
import DownloadIcon from '@mui/icons-material/Download';
import { useApp } from '../App.jsx';
import api from '../api/client.js';

const STATUS_LABEL = {
  pending: '排队中',
  generating: '生成中',
  done: '已完成',
  failed: '失败',
};

// 单本书卡片：展示书名/状态/进度条，并按状态提供操作按钮。
export default function BookCard({ book, progress }) {
  const { playBook, deleteBook, retryBook } = useApp();
  const pct = progress != null ? progress : book.progress;

  // v1.4 增量：导出菜单（整本 / 分章）的锚点状态
  const [anchorEl, setAnchorEl] = useState(null);
  const exportMenuOpen = Boolean(anchorEl);
  const handleExportClick = (e) => setAnchorEl(e.currentTarget);
  const handleExportClose = () => setAnchorEl(null);

  const handleDelete = (e) => {
    e.stopPropagation();
    if (
      window.confirm(
        `确定删除《${book.title}》？仅删除应用内数据，不影响原始文件。`
      )
    ) {
      deleteBook(book.id);
    }
  };

  return (
    <Card variant="outlined">
      <CardContent>
        <Stack
          direction="row"
          justifyContent="space-between"
          alignItems="center"
          spacing={1}
        >
          <Typography variant="subtitle1" noWrap title={book.title}>
            {book.title}
          </Typography>
          <Chip
            size="small"
            label={STATUS_LABEL[book.status] || book.status}
            color={
              book.status === 'done'
                ? 'success'
                : book.status === 'failed'
                  ? 'error'
                  : 'default'
            }
          />
        </Stack>

        {(book.status === 'generating' || book.status === 'pending') && (
          <Box sx={{ mt: 1 }}>
            <LinearProgress variant="determinate" value={pct || 0} />
            <Typography variant="caption" color="text.secondary">
              {pct || 0}%
            </Typography>
          </Box>
        )}

        {book.status === 'failed' && book.error && (
          <Typography
            variant="caption"
            color="error"
            sx={{ display: 'block', mt: 1 }}
          >
            错误：{book.error}
          </Typography>
        )}

        {book.status === 'done' && book.duration_sec != null && (
          <Typography variant="caption" color="text.secondary" display="block" sx={{ mt: 1 }}>
            {book.chapter_count > 0 ? `${book.chapter_count} 章 · ` : ''}
            时长约 {Math.round(book.duration_sec)} 秒 · {book.char_count || 0} 字
          </Typography>
        )}

        <Stack direction="row" spacing={1} sx={{ mt: 2 }}>
          {book.status === 'done' && (
            <Button
              size="small"
              variant="contained"
              startIcon={<PlayArrowIcon />}
              onClick={() => playBook(book)}
            >
              播放
            </Button>
          )}
          {book.status === 'done' && (
            <>
              <Button
                size="small"
                variant="outlined"
                startIcon={<DownloadIcon />}
                onClick={handleExportClick}
                aria-controls={exportMenuOpen ? 'export-menu' : undefined}
                aria-haspopup="true"
                aria-expanded={exportMenuOpen ? 'true' : undefined}
              >
                导出 ▾
              </Button>
              <Menu
                id="export-menu"
                anchorEl={anchorEl}
                open={exportMenuOpen}
                onClose={handleExportClose}
              >
                <MenuItem
                  component="a"
                  href={api.exportBookUrl(book.id)}
                  download
                  onClick={handleExportClose}
                >
                  导出整本 mp3（单文件）
                </MenuItem>
                <MenuItem
                  component="a"
                  href={api.exportChaptersUrl(book.id)}
                  download
                  onClick={handleExportClose}
                >
                  导出分章 mp3（zip，可逐章跳转）
                </MenuItem>
              </Menu>
            </>
          )}
          {book.status === 'failed' && (
            <Button
              size="small"
              variant="outlined"
              startIcon={<RefreshIcon />}
              onClick={() => retryBook(book.id)}
            >
              重试
            </Button>
          )}
          <Button
            size="small"
            color="error"
            startIcon={<DeleteIcon />}
            onClick={handleDelete}
          >
            删除
          </Button>
        </Stack>
      </CardContent>
    </Card>
  );
}
