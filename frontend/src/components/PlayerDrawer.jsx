import React, { useEffect, useRef, useState } from 'react';
import {
  Box,
  Button,
  Divider,
  FormControl,
  IconButton,
  List,
  ListItemButton,
  ListItemText,
  MenuItem,
  Paper,
  Select,
  Slider,
  Stack,
  TextField,
  ToggleButton,
  ToggleButtonGroup,
  Typography,
} from '@mui/material';
import PlayArrowIcon from '@mui/icons-material/PlayArrow';
import PauseIcon from '@mui/icons-material/Pause';
import SkipPreviousIcon from '@mui/icons-material/SkipPrevious';
import SkipNextIcon from '@mui/icons-material/SkipNext';
import BookmarkIcon from '@mui/icons-material/Bookmark';
import BookmarkAddIcon from '@mui/icons-material/BookmarkAdd';
import DeleteIcon from '@mui/icons-material/Delete';
import { useApp } from '../App.jsx';
import api from '../api/client.js';

// 播放倍速档位（PLY-002）：仅作用于 <audio playbackRate>，不影响已生成文件
const SPEEDS = [0.5, 1, 1.25, 1.5, 2];

// 书签上限（与后端一致，仅前端提示用）
const BOOKMARK_LIMIT = 200;

// 进度上报节流间隔（ms）：每 4s 上报一次（RES-001）
const REPORT_INTERVAL = 4000;

// 格式化秒数为 m:ss
function fmtTime(sec) {
  const s = Math.max(0, Math.floor(sec || 0));
  const m = Math.floor(s / 60);
  const r = s % 60;
  return `${m}:${String(r).padStart(2, '0')}`;
}

// 底部常驻播放器：播放/暂停/进度拖动/倍速切换，并支持按章切换与跳转。
// 音频经 /api/books/{id}/chapters/{idx}/audio 流式加载，支持 Range（拖动 seek）。
// v1.2 增量：断点续听恢复（playback）、进度上报（postPosition）、书签 CRUD。
export default function PlayerDrawer() {
  const { playing, notify } = useApp();
  const audioRef = useRef(null);
  const pendingSeekRef = useRef(null); // 待应用的续听/书签跳转秒数（loadedmetadata 后生效）
  const [isPlaying, setIsPlaying] = useState(false);
  const [current, setCurrent] = useState(0);
  const [duration, setDuration] = useState(0);
  const [speed, setSpeed] = useState(1);
  const [chapters, setChapters] = useState([]); // 章节列表 [{index,title,...}]
  const [cur, setCur] = useState(0);            // 当前章索引（0-based）
  const [bookmarks, setBookmarks] = useState([]); // 该书书签列表
  const [bookmarkLabel, setBookmarkLabel] = useState('');
  const [showBookmarks, setShowBookmarks] = useState(false);

  // 切换书本时重置播放态，并拉取章节列表、书签、恢复断点续听位置
  useEffect(() => {
    setIsPlaying(false);
    setCurrent(0);
    setDuration(0);
    setSpeed(1);
    setCur(0);
    setChapters([]);
    setBookmarks([]);
    setBookmarkLabel('');
    setShowBookmarks(false);
    pendingSeekRef.current = null;
    if (audioRef.current) audioRef.current.playbackRate = 1;
    if (playing) {
      // 恢复断点：默认 0/0，章不存在或越界安全回退（RES-003）
      const pb = playing.playback;
      let targetChapter = 0;
      let targetTime = 0;
      const chapterCount = playing.chapters ? playing.chapters.length : 0;
      if (pb && Number.isFinite(pb.current_chapter)) {
        const idx = pb.current_chapter;
        targetChapter = idx >= 0 && idx < chapterCount ? idx : 0;
      }
      if (pb && Number.isFinite(pb.current_time)) {
        targetTime = pb.current_time >= 0 ? pb.current_time : 0;
      }
      pendingSeekRef.current = targetTime;
      setCur(targetChapter);

      api
        .getChapters(playing.id)
        .then((res) => setChapters(res.chapters || []))
        .catch(() => setChapters([]));
      api
        .listBookmarks(playing.id)
        .then((res) => setBookmarks(res.bookmarks || []))
        .catch(() => setBookmarks([]));
    }
  }, [playing?.id]);

  // 当前章音频地址（无章节时按第 0 章兜底）
  const url = playing ? api.getChapterAudioUrl(playing.id, cur) : '';

  // 绑定 <audio> 事件
  useEffect(() => {
    const audio = audioRef.current;
    if (!audio) return;
    const onTime = () => setCurrent(audio.currentTime);
    const onDur = () => {
      setDuration(audio.duration || 0);
      // pending seek：元数据就绪后再定位，避免失效（RES-003 / 书签跳转）
      if (pendingSeekRef.current != null) {
        const t = pendingSeekRef.current;
        pendingSeekRef.current = null;
        try {
          audio.currentTime = Math.min(t, audio.duration || 0);
          setCurrent(audio.currentTime);
        } catch (e) {
          /* 部分浏览器对未播放音频 seek 可能抛错，忽略 */
        }
      }
    };
    const onPlay = () => setIsPlaying(true);
    const onPause = () => {
      setIsPlaying(false);
      // 暂停即上报一次当前位置（避免跨章丢失末位位置）
      if (playing && audioRef.current) {
        api
          .postPosition(playing.id, cur, audioRef.current.currentTime)
          .catch(() => {});
      }
    };
    const onEnd = () => setIsPlaying(false);
    audio.addEventListener('timeupdate', onTime);
    audio.addEventListener('loadedmetadata', onDur);
    audio.addEventListener('play', onPlay);
    audio.addEventListener('pause', onPause);
    audio.addEventListener('ended', onEnd);
    return () => {
      audio.removeEventListener('timeupdate', onTime);
      audio.removeEventListener('loadedmetadata', onDur);
      audio.removeEventListener('play', onPlay);
      audio.removeEventListener('pause', onPause);
      audio.removeEventListener('ended', onEnd);
    };
  }, [url, playing?.id, cur]);

  // 进度上报（节流每 4s）+ 卸载时立即上报（RES-001）
  useEffect(() => {
    if (!playing) return;
    const timer = setInterval(() => {
      const audio = audioRef.current;
      if (!audio || audio.paused) return; // 仅播放中持续上报，暂停已单独处理
      api.postPosition(playing.id, cur, audio.currentTime).catch(() => {});
    }, REPORT_INTERVAL);
    return () => {
      clearInterval(timer);
      const audio = audioRef.current;
      if (audio && playing) {
        api.postPosition(playing.id, cur, audio.currentTime).catch(() => {});
      }
    };
  }, [playing?.id, cur]);

  const togglePlay = () => {
    const audio = audioRef.current;
    if (!audio) return;
    if (audio.paused) audio.play();
    else audio.pause();
  };

  const onSeek = (e, val) => {
    const audio = audioRef.current;
    if (audio && duration) {
      audio.currentTime = (val / 100) * duration;
      setCurrent(audio.currentTime);
    }
  };

  // 倍速即时生效（仅影响播放，不改文件）
  const onSpeed = (e, val) => {
    if (val == null) return;
    setSpeed(val);
    if (audioRef.current) audioRef.current.playbackRate = val;
  };

  // 切换到指定章节：更新 <audio src> 并重置进度后播放
  const gotoChapter = (idx) => {
    if (idx < 0 || idx >= chapters.length) return;
    setCur(idx);
    setCurrent(0);
    setDuration(0);
    pendingSeekRef.current = null;
    const audio = audioRef.current;
    if (audio) {
      audio.load();
      audio.play().catch(() => {});
    }
  };

  // 跳转到书签：切章 + pending seek 到书签时间
  const gotoBookmark = (bm) => {
    if (bm.chapter < 0 || bm.chapter >= chapters.length) return;
    setCur(bm.chapter);
    setCurrent(0);
    setDuration(0);
    pendingSeekRef.current = bm.time;
    const audio = audioRef.current;
    if (audio) {
      audio.load();
      audio.play().catch(() => {});
    }
  };

  // 新增书签（记录当前章 + 当前秒 + 可选标签）
  const addBookmark = () => {
    const audio = audioRef.current;
    if (!audio || !playing) return;
    if (bookmarks.length >= BOOKMARK_LIMIT) {
      notify(`书签已达上限 ${BOOKMARK_LIMIT}`, 'warning');
      return;
    }
    const t = audio.currentTime;
    api
      .addBookmark(playing.id, { chapter: cur, time: t, label: bookmarkLabel })
      .then((bm) => {
        setBookmarks((prev) => [...prev, bm]);
        setBookmarkLabel('');
        notify('已添加书签', 'success');
      })
      .catch((e) => notify(e.message, 'error'));
  };

  // 删除书签
  const removeBookmark = (bkId) => {
    if (!playing) return;
    api
      .deleteBookmark(playing.id, bkId)
      .then(() => setBookmarks((prev) => prev.filter((b) => b.id !== bkId)))
      .catch((e) => notify(e.message, 'error'));
  };

  if (!playing) return null;

  const pct = duration ? (current / duration) * 100 : 0;
  const hasChapters = chapters.length > 0;

  return (
    <Paper
      elevation={6}
      sx={{
        position: 'fixed',
        bottom: 0,
        left: 0,
        right: 0,
        zIndex: 1200,
        p: 2,
        borderTop: '1px solid',
        borderColor: 'divider',
      }}
    >
      <Box sx={{ maxWidth: 900, mx: 'auto' }}>
        <audio ref={audioRef} src={url} preload="metadata" />
        {/* 书签面板 */}
        {showBookmarks && (
          <Box
            sx={{
              mb: 2,
              bgcolor: 'background.paper',
              borderRadius: 1,
              p: 1,
              border: '1px solid',
              borderColor: 'divider',
            }}
          >
            <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 1 }}>
              <TextField
                size="small"
                label="书签备注（可选）"
                value={bookmarkLabel}
                onChange={(e) => setBookmarkLabel(e.target.value)}
                sx={{ flexGrow: 1 }}
              />
              <Button
                size="small"
                variant="contained"
                startIcon={<BookmarkAddIcon />}
                onClick={addBookmark}
              >
                加书签
              </Button>
            </Stack>
            {bookmarks.length === 0 ? (
              <Typography variant="caption" color="text.secondary">
                暂无书签
              </Typography>
            ) : (
              <List dense sx={{ maxHeight: 160, overflow: 'auto' }}>
                {bookmarks.map((bm) => (
                  <ListItemButton
                    key={bm.id}
                    onClick={() => gotoBookmark(bm)}
                    sx={{ borderRadius: 1 }}
                  >
                    <ListItemText
                      primary={
                        bm.label
                          ? `${bm.label}（第 ${bm.chapter + 1} 章 · ${fmtTime(bm.time)}）`
                          : `第 ${bm.chapter + 1} 章 · ${fmtTime(bm.time)}`
                      }
                      secondary="点击跳转到该位置"
                    />
                    <IconButton
                      edge="end"
                      size="small"
                      aria-label="删除书签"
                      onClick={(e) => {
                        e.stopPropagation();
                        removeBookmark(bm.id);
                      }}
                    >
                      <DeleteIcon fontSize="small" />
                    </IconButton>
                  </ListItemButton>
                ))}
              </List>
            )}
            <Divider />
          </Box>
        )}

        <Stack direction="row" spacing={2} alignItems="center">
          <IconButton color="primary" onClick={togglePlay}>
            {isPlaying ? <PauseIcon /> : <PlayArrowIcon />}
          </IconButton>

          {hasChapters && (
            <Stack direction="row" spacing={0.5} alignItems="center">
              <IconButton
                size="small"
                disabled={cur <= 0}
                onClick={() => gotoChapter(cur - 1)}
                aria-label="上一章"
              >
                <SkipPreviousIcon />
              </IconButton>
              <FormControl size="small" sx={{ minWidth: 160 }}>
                <Select
                  value={cur}
                  onChange={(e) => gotoChapter(Number(e.target.value))}
                  displayEmpty
                  inputProps={{ 'aria-label': '选择章节' }}
                >
                  {chapters.map((c) => (
                    <MenuItem key={c.index} value={c.index}>
                      {`${c.index + 1}. ${c.title}`}
                    </MenuItem>
                  ))}
                </Select>
              </FormControl>
              <IconButton
                size="small"
                disabled={cur >= chapters.length - 1}
                onClick={() => gotoChapter(cur + 1)}
                aria-label="下一章"
              >
                <SkipNextIcon />
              </IconButton>
            </Stack>
          )}

          <Box sx={{ flexGrow: 1, minWidth: 0 }}>
            <Typography variant="body2" noWrap>
              {playing.title}
              {hasChapters ? ` · ${chapters[cur]?.title || ''}` : ''}
            </Typography>
            <Slider
              value={pct}
              onChange={onSeek}
              size="small"
              aria-label="播放进度"
            />
          </Box>
          <Stack direction="row" spacing={0.5} alignItems="center">
            <IconButton
              color={showBookmarks ? 'primary' : 'default'}
              onClick={() => setShowBookmarks((v) => !v)}
              aria-label="书签"
            >
              <BookmarkIcon />
            </IconButton>
            <Typography variant="caption" color="text.secondary" sx={{ mr: 1 }}>
              倍速
            </Typography>
            <ToggleButtonGroup size="small" value={speed} exclusive onChange={onSpeed}>
              {SPEEDS.map((s) => (
                <ToggleButton
                  key={s}
                  value={s}
                  sx={{ px: 1, py: 0.25, fontSize: 12 }}
                >
                  {s}x
                </ToggleButton>
              ))}
            </ToggleButtonGroup>
          </Stack>
        </Stack>
      </Box>
    </Paper>
  );
}
