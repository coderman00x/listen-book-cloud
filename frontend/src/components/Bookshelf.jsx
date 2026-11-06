import React, { useEffect, useRef, useState } from 'react';
import { Box, Grid, Typography } from '@mui/material';
import { useApp } from '../App.jsx';
import api from '../api/client.js';
import BookCard from './BookCard.jsx';

// 书架列表容器：展示所有书籍卡片。
// 定时轮询：对生成中/排队中的书实时拉取进度（每 1.5s），
// 并周期性刷新列表以更新状态（pending -> done/failed）。
export default function Bookshelf() {
  const { books, refreshBooks } = useApp();
  const booksRef = useRef(books);
  booksRef.current = books;

  const [liveProgress, setLiveProgress] = useState({});

  useEffect(() => {
    const timer = setInterval(async () => {
      const active = booksRef.current.filter(
        (b) => b.status === 'generating' || b.status === 'pending'
      );
      if (active.length === 0) return;
      try {
        // 实时进度（内存map，比落盘元数据更即时）
        const next = {};
        await Promise.all(
          active.map(async (b) => {
            try {
              const p = await api.getProgress(b.id);
              next[b.id] = p.progress;
            } catch (e) {
              /* 忽略单本轮询失败 */
            }
          })
        );
        setLiveProgress((prev) => ({ ...prev, ...next }));
        // 同时刷新列表状态（便于 pending -> done 切换）
        await refreshBooks();
      } catch (e) {
        /* 忽略轮询错误 */
      }
    }, 1500);
    return () => clearInterval(timer);
  }, [refreshBooks]);

  return (
    <Box sx={{ mt: 3 }}>
      <Typography variant="h6" sx={{ mb: 2 }}>
        书架
      </Typography>
      {books.length === 0 ? (
        <Typography color="text.secondary">
          还没有书籍，先导入一些 txt 吧。
        </Typography>
      ) : (
        <Grid container spacing={2}>
          {books.map((book) => (
            <Grid item xs={12} sm={6} key={book.id}>
              <BookCard
                book={book}
                progress={liveProgress[book.id] ?? book.progress}
              />
            </Grid>
          ))}
        </Grid>
      )}
    </Box>
  );
}
