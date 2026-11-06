import React, { useRef, useState } from 'react';
import { Box, Paper, Typography } from '@mui/material';
import UploadFileIcon from '@mui/icons-material/UploadFile';
import { useApp } from '../App.jsx';

// 导入区：点击选择或拖拽多个 .txt / .epub / .pdf。
// 仅将文件内容经 multipart 上传，原始文件不会被读改写删（见架构红线）。
const SUPPORTED = ['.txt', '.epub', '.pdf'];

export default function ImportZone() {
  const { importFiles } = useApp();
  const inputRef = useRef(null);
  const [dragOver, setDragOver] = useState(false);
  const [count, setCount] = useState(0);

  const handleFiles = (fileList) => {
    const files = Array.from(fileList).filter((f) =>
      SUPPORTED.some((ext) => f.name.toLowerCase().endsWith(ext))
    );
    if (files.length === 0) return;
    setCount(files.length);
    importFiles(files);
    if (inputRef.current) inputRef.current.value = '';
  };

  const onDrop = (e) => {
    e.preventDefault();
    setDragOver(false);
    handleFiles(e.dataTransfer.files);
  };

  return (
    <Paper
      variant="outlined"
      sx={{
        p: 3,
        textAlign: 'center',
        borderStyle: 'dashed',
        borderColor: dragOver ? 'primary.main' : 'divider',
        bgcolor: dragOver ? 'action.hover' : 'background.paper',
        cursor: 'pointer',
      }}
      onClick={() => inputRef.current && inputRef.current.click()}
      onDragOver={(e) => {
        e.preventDefault();
        setDragOver(true);
      }}
      onDragLeave={() => setDragOver(false)}
      onDrop={onDrop}
    >
      <UploadFileIcon color="primary" sx={{ fontSize: 40 }} />
      <Typography variant="body1" sx={{ mt: 1 }}>
        点击选择，或将多个 .txt / .epub / .pdf 文件拖拽到此处
      </Typography>
      <Typography variant="caption" color="text.secondary" display="block">
        支持 TXT / EPUB / PDF（仅读取内容，原始文件不会被修改、删除或移动）
      </Typography>
      {count > 0 && (
        <Typography variant="body2" color="primary" sx={{ mt: 1 }}>
          已加入 {count} 个文件
        </Typography>
      )}
      <input
        ref={inputRef}
        type="file"
        accept=".txt,.epub,.pdf"
        multiple
        hidden
        onChange={(e) => handleFiles(e.target.files)}
      />
    </Paper>
  );
}
